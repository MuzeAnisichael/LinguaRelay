from __future__ import annotations

import argparse
import json
import math
import statistics
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from lingua_relay.config import Settings
from lingua_relay.mt.m2m100 import M2M100Translator

TARGETS = {"zh": "en", "ja": "ko", "en": "zh", "ko": "ja"}
TERMS = ("LinguaRelay", "WASAPI", "CUDA", "OpenAI")
TERM_FIXTURES = {
    "zh": "LinguaRelay 支持 WASAPI、CUDA 和 OpenAI。",
    "ja": "LinguaRelay は WASAPI、CUDA、OpenAI をサポートします。",
    "en": "LinguaRelay supports WASAPI, CUDA, and OpenAI.",
    "ko": "LinguaRelay는 WASAPI, CUDA 및 OpenAI를 지원합니다.",
}


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Aggregate and execute the M5 release quality gate"
    )
    parser.add_argument("--asr-report", type=Path, required=True)
    parser.add_argument("--mt-report", type=Path, required=True)
    parser.add_argument("--correction-report", type=Path, required=True)
    parser.add_argument("--corpus-manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--device", choices=("cpu", "cuda"), default="cpu")
    parser.add_argument("--compute-type", default="int8")
    args = parser.parse_args()
    asr = _load(args.asr_report)
    mt = _load(args.mt_report)
    correction = _load(args.correction_report)
    corpus = _load(args.corpus_manifest)
    settings = Settings.load(None).translation
    settings = replace(
        settings,
        model_path=Path("models/m2m100_418m_ct2"),
        device=args.device,
        compute_type=args.compute_type,
    )
    translator = M2M100Translator(settings)
    translator.load()
    end_to_end = _measure_end_to_end(asr, translator)
    terminology = _measure_terms(translator)
    scenarios = sorted({str(sample["scenario"]) for sample in corpus["samples"]})
    languages = sorted({str(sample["language"]) for sample in corpus["samples"]})
    asr_errors = sum(int(sample["errors"]) for sample in asr["samples"])
    asr_units = sum(int(sample["units"]) for sample in asr["samples"])
    quality = {
        "mean_chrf_pp": round(
            statistics.fmean(route["quality"]["chrf_pp"] for route in mt["routes"].values()), 3
        ),
        "mean_bleu": round(
            statistics.fmean(route["quality"]["bleu"] for route in mt["routes"].values()), 3
        ),
    }
    gates = {
        "four_languages_present": languages == ["en", "ja", "ko", "zh"],
        "all_acoustic_scenarios_present": len(scenarios) == 5,
        "asr_error_rate_at_most_100_percent": asr_errors / max(1, asr_units) <= 1.0,
        "first_caption_p50_under_4_seconds": end_to_end["first_caption_p50_ms"] <= 4_000,
        "first_caption_p95_under_15_seconds": end_to_end["first_caption_p95_ms"] <= 15_000,
        "final_pipeline_rtf_under_1": end_to_end["final_pipeline_rtf"] <= 1.0,
        "terminology_hit_rate_at_least_75_percent": terminology["hit_rate"] >= 0.75,
        "all_12_translation_routes_measured": mt["acceptance"]["all_routes_present"],
        "translation_latency_gate_passed": mt["acceptance"]["all_routes_passed_latency"],
        "correction_fault_gates_passed": correction["acceptance"]["all_passed"],
    }
    report: dict[str, Any] = {
        "schema_version": 1,
        "milestone": "M5",
        "created_at": datetime.now(UTC).isoformat(),
        "release_candidate": "v0.1.0",
        "methodology": {
            "corpus": (
                "20 pinned CC-BY-4.0 FLEURS samples with deterministic CC0 acoustic "
                "simulations; see corpus manifest for limitations"
            ),
            "end_to_end": (
                "For each ASR sample, measured translation inference is added to measured "
                "first-partial and final ASR processing time on the same host."
            ),
            "translation_quality": "M3 CC0 four-language parallel corpus across all 12 routes.",
            "terminology": "Exact case-insensitive retention of four protected technical terms.",
        },
        "inputs": {
            "asr": str(args.asr_report),
            "translation": str(args.mt_report),
            "correction": str(args.correction_report),
            "corpus": str(args.corpus_manifest),
        },
        "corpus": {
            "languages": languages,
            "scenarios": scenarios,
            "samples": len(corpus["samples"]),
        },
        "asr": {
            "metric": "weighted WER/CER by language",
            "combined_error_rate": round(asr_errors / max(1, asr_units), 4),
            "languages": asr["languages"],
        },
        "translation_quality": quality,
        "end_to_end": end_to_end,
        "terminology": terminology,
        "gates": gates,
        "all_passed": all(gates.values()),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps({"all_passed": report["all_passed"], "gates": gates}, indent=2))
    return 0 if report["all_passed"] else 1


def _measure_end_to_end(asr: dict[str, Any], translator: M2M100Translator) -> dict[str, Any]:
    first_latencies, final_latencies, final_audio_ms, details = [], [], [], []
    for sample in asr["samples"]:
        source = str(sample["language"])
        target = TARGETS[source]
        partial = translator.translate(
            str(sample["first_partial_text"]), source=source, target=target
        )
        hypothesis = str(sample["hypothesis"])
        final_inference_ms = (
            translator.translate(hypothesis, source=source, target=target).inference_ms
            if hypothesis.strip()
            else 0.0
        )
        first_ms = float(sample["first_partial_ms"]) + partial.inference_ms
        final_ms = float(sample["wall_ms"]) + final_inference_ms
        first_latencies.append(first_ms)
        final_latencies.append(final_ms)
        final_audio_ms.append(float(sample["duration_ms"]))
        details.append(
            {
                "id": sample["id"],
                "route": f"{source}->{target}",
                "first_caption_ms": round(first_ms, 3),
                "final_pipeline_ms": round(final_ms, 3),
            }
        )
    return {
        "first_caption_p50_ms": round(_percentile(first_latencies, 50), 3),
        "first_caption_p95_ms": round(_percentile(first_latencies, 95), 3),
        "final_pipeline_p50_ms": round(_percentile(final_latencies, 50), 3),
        "final_pipeline_p95_ms": round(_percentile(final_latencies, 95), 3),
        "final_pipeline_rtf": round(sum(final_latencies) / max(1, sum(final_audio_ms)), 4),
        "samples": details,
    }


def _measure_terms(translator: M2M100Translator) -> dict[str, Any]:
    details, hits, total = [], 0, 0
    for source, source_text in TERM_FIXTURES.items():
        for target in TERM_FIXTURES:
            if source == target:
                continue
            hypothesis = translator.translate(source_text, source=source, target=target).text
            found = [term for term in TERMS if term.casefold() in hypothesis.casefold()]
            hits += len(found)
            total += len(TERMS)
            details.append(
                {
                    "route": f"{source}->{target}",
                    "hypothesis": hypothesis,
                    "matched": found,
                    "required": list(TERMS),
                }
            )
    return {
        "hits": hits,
        "opportunities": total,
        "hit_rate": round(hits / total, 4),
        "routes": details,
    }


def _percentile(values: list[float], percentile: float) -> float:
    ordered = sorted(values)
    rank = (len(ordered) - 1) * percentile / 100
    low = math.floor(rank)
    high = math.ceil(rank)
    if low == high:
        return ordered[low]
    return ordered[low] + (ordered[high] - ordered[low]) * (rank - low)


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    raise SystemExit(main())
