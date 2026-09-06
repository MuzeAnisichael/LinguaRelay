"""Opt-in, budget-reserved evaluation of synthetic captions (never reads app history)."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import random
import time
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

from lingua_relay import __version__
from lingua_relay.config import CorrectionSettings
from lingua_relay.correction.prompt import SYSTEM_PROMPT, build_messages
from lingua_relay.correction.provider import OpenAICompatibleProvider
from lingua_relay.correction.types import CorrectionRequest, GlossaryEntry
from lingua_relay.events import CaptionEvent

MODELS = ("qwen/qwen3-30b-a3b-instruct-2507", "google/gemini-2.5-flash-lite")
PRICE_CAP = 1.0  # USD / million tokens; enforced on both input/output by OpenRouter.
MAX_TOKENS = 384


def make_request(case: dict) -> CorrectionRequest:
    source_language, target_language = case.get("route", "en-zh").split("-")
    state = case.get("state", "final")
    event = CaptionEvent(
        case["source"],
        case["fast"],
        source_language,
        target_language,
        state,
        0,
        segment_id=case["id"],
    )
    context = tuple(
        CaptionEvent(source, target, source_language, target_language, "final", 0)
        for source, target in case.get("context", [])
    )
    glossary = tuple(GlossaryEntry(source, target) for source, target in case.get("glossary", []))
    return CorrectionRequest(event, context, glossary, state, case["id"], 0, time.monotonic_ns())


def reservation_usd(request: CorrectionRequest) -> float:
    # UTF-8 byte count is deliberately much larger than normal token count.
    # 1024 extra tokens cover framing. Reserve *every* attempt, even timeout/error;
    # never reclaim unused reservations based on a delayed/absent usage response.
    size = len(json.dumps(build_messages(request), ensure_ascii=False).encode("utf-8"))
    return (size + 1024 + MAX_TOKENS) * PRICE_CAP / 1_000_000


def percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    return round(ordered[max(0, math.ceil(len(ordered) * fraction) - 1)], 2)


def summary(rows: list[dict]) -> dict:
    result = {}
    for model in MODELS:
        attempts = [row for row in rows if row["requested_model"] == model]
        successful = [row for row in attempts if row.get("result")]
        durations = [row["elapsed_ms"] for row in successful if "elapsed_ms" in row]
        result[model] = {
            "attempts": len(attempts),
            "successes": len(successful),
            "failures": sum("error_type" in row for row in attempts),
            "pending_attempts": sum(
                "result" not in row and "error_type" not in row for row in attempts
            ),
            "p50_complete_response_ms": percentile(durations, 0.5),
            "p95_complete_response_ms": percentile(durations, 0.95),
            "first_request_ms": attempts[0].get("elapsed_ms") if attempts else None,
            "success_within_2_seconds": sum(value <= 2000 for value in durations),
            "reported_cost_usd": sum(
                (row["result"].get("usage") or {}).get("cost", 0) for row in successful
            ),
            "unknown_cost_attempts": sum(
                "cost" not in (row.get("result", {}).get("usage") or {}) for row in attempts
            ),
        }
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--budget-usd", type=float, default=1.0)
    parser.add_argument("--limit", type=int, default=200)
    parser.add_argument("--routing", choices=["latency", "price", "default"], default="latency")
    parser.add_argument(
        "--transport-label",
        default="httpx-pooled",
        help="Descriptive report label only; does not change the HTTP client.",
    )
    parser.add_argument("--allow-paid-api", action="store_true")
    args = parser.parse_args()
    if not args.allow_paid_api:
        parser.error("real calls require --allow-paid-api and explicit user budget approval")
    if not math.isfinite(args.budget_usd) or not 0 < args.budget_usd <= 1:
        parser.error("this evaluation is restricted to a budget in (0, 1] USD")
    if args.output.exists():
        parser.error("refusing to overwrite an existing paid-run report")
    if not os.environ.get("OPENROUTER_API_KEY", "").strip():
        parser.error("OPENROUTER_API_KEY is not configured")
    corpus = json.loads(args.corpus.read_text(encoding="utf-8"))
    if corpus.get("provenance") != "project-authored-synthetic-CC0":
        parser.error("only explicitly project-authored synthetic corpora are accepted")
    cases = corpus["cases"]
    random.Random(20260907).shuffle(cases)
    providers = {
        model: OpenAICompatibleProvider(
            CorrectionSettings(
                provider="openai_compatible",
                endpoint="https://openrouter.ai/api/v1",
                api_key_env="OPENROUTER_API_KEY",
                model=model,
                timeout_seconds=12,
                max_tokens=MAX_TOKENS,
                temperature=0,
                openrouter_provider_sort="" if args.routing == "default" else args.routing,
            ),
            openrouter_price_cap=PRICE_CAP,
        )
        for model in MODELS
    }
    report = {
        "created_at": datetime.now(UTC).isoformat(),
        "app_version": __version__,
        "transport": args.transport_label,
        "system_prompt_sha256": hashlib.sha256(SYSTEM_PROMPT.encode("utf-8")).hexdigest(),
        "corpus": args.corpus.name,
        "provenance": corpus["provenance"],
        "method": "interleaved sequential complete-response calls; no streaming; no ASR/audio",
        "baseline": corpus.get("baseline", "synthetic controlled fast translations"),
        "routing": args.routing,
        "temperature": 0,
        "max_tokens": MAX_TOKENS,
        "budget_usd": args.budget_usd,
        "price_cap_per_million_usd": PRICE_CAP,
        "reserved_upper_bound_usd": 0.0,
        "rows": [],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    report["summary"] = summary([])
    with args.output.open("x", encoding="utf-8") as output:
        json.dump(report, output, ensure_ascii=False, indent=2)
    failures = 0
    for index, case in enumerate(cases):
        for model in MODELS if index % 2 == 0 else tuple(reversed(MODELS)):
            request = make_request(case)
            reservation = reservation_usd(request)
            if (
                report["reserved_upper_bound_usd"] + reservation > args.budget_usd
                or len(report["rows"]) >= args.limit
                or failures >= 3
            ):
                print("Stopped at request, budget, or consecutive-error limit.", flush=True)
                return 0
            report["reserved_upper_bound_usd"] += reservation
            row = {
                "case_id": case["id"],
                "route": case.get("route", "en-zh"),
                "category": case["category"],
                "source": case["source"],
                "fast": case["fast"],
                "reference": case["reference"],
                "requested_model": model,
                "reserved_usd": reservation,
            }
            report["rows"].append(row)
            # Persist reservation before sending, so interruption cannot hide paid attempts.
            args.output.write_text(
                json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            started = time.monotonic()
            try:
                result = providers[model].revise(request)
                row["result"] = asdict(result)
                # Stop without assuming an unreported call was free.
                failures = 3 if result.usage is None or "cost" not in result.usage else 0
            except Exception as error:
                # Do not serialize headers, tokens, environment, or remote error bodies.
                row["error_type"] = type(error).__name__
                failures += 1
            row["elapsed_ms"] = round((time.monotonic() - started) * 1000, 2)
            report["summary"] = summary(report["rows"])
            args.output.write_text(
                json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            print(
                f"{len(report['rows'])}: {case['id']} / {model}: "
                f"{row['elapsed_ms']:.0f} ms, {'ok' if 'result' in row else 'error'}",
                flush=True,
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
