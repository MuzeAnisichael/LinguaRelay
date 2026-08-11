from __future__ import annotations

import json
import platform
import statistics
import sys
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from lingua_relay.config import TranslationSettings
from lingua_relay.languages import translation_routes
from lingua_relay.mt.m2m100 import M2M100Translator


def run_benchmark(
    settings: TranslationSettings,
    corpus_path: str | Path,
    *,
    latency_threshold_ms: float = 1_800.0,
) -> dict[str, Any]:
    try:
        import sacrebleu
    except ImportError as error:
        raise RuntimeError("install LinguaRelay's 'benchmark' extra") from error

    corpus = json.loads(Path(corpus_path).read_text(encoding="utf-8"))
    samples = corpus["samples"]
    translator = M2M100Translator(settings)
    translator.load()
    routes: dict[str, Any] = {}
    all_latencies: list[float] = []
    for source, target in translation_routes():
        hypotheses: list[str] = []
        references: list[str] = []
        latencies: list[float] = []
        details: list[dict[str, Any]] = []
        for sample in samples:
            source_text = str(sample[source])
            reference = str(sample[target])
            result = translator.translate(source_text, source=source, target=target)
            hypotheses.append(result.text)
            references.append(reference)
            latencies.append(result.inference_ms)
            details.append(
                {
                    "id": sample["id"],
                    "source": source_text,
                    "reference": reference,
                    "hypothesis": result.text,
                    "latency_ms": round(result.inference_ms, 3),
                }
            )
        p50 = _percentile(latencies, 50)
        p95 = _percentile(latencies, 95)
        route_name = f"{source}->{target}"
        routes[route_name] = {
            "source": source,
            "target": target,
            "sample_count": len(samples),
            "latency_ms": {"p50": round(p50, 3), "p95": round(p95, 3)},
            "quality": {
                "chrf_pp": round(
                    sacrebleu.corpus_chrf(hypotheses, [references], word_order=2).score, 3
                ),
                "bleu": round(sacrebleu.corpus_bleu(hypotheses, [references]).score, 3),
            },
            "passed_latency": p50 <= latency_threshold_ms,
            "samples": details,
        }
        all_latencies.extend(latencies)

    return {
        "schema_version": 1,
        "milestone": "M3",
        "created_at": datetime.now(UTC).isoformat(),
        "corpus": {
            "path": str(Path(corpus_path)),
            "name": corpus.get("name", "unknown"),
            "license": corpus.get("license", "unknown"),
            "sample_count": len(samples),
        },
        "model": {
            "provider": settings.provider,
            "name": settings.model,
            "revision": settings.revision,
            "path": str(settings.model_path),
            "load_ms": round(translator.load_ms, 3),
            "runtime": asdict(translator.runtime),
        },
        "host": {
            "platform": platform.platform(),
            "python": sys.version.split()[0],
        },
        "acceptance": {
            "required_routes": len(translation_routes()),
            "measured_routes": len(routes),
            "p50_threshold_ms": latency_threshold_ms,
            "all_routes_present": len(routes) == 12,
            "all_routes_passed_latency": all(route["passed_latency"] for route in routes.values()),
        },
        "aggregate_latency_ms": {
            "mean": round(statistics.fmean(all_latencies), 3),
            "p50": round(_percentile(all_latencies, 50), 3),
            "p95": round(_percentile(all_latencies, 95), 3),
        },
        "routes": routes,
    }


def write_report(report: dict[str, Any], path: str | Path) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return target


def _percentile(values: list[float], percentile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    rank = (len(ordered) - 1) * percentile / 100
    lower = int(rank)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = rank - lower
    return ordered[lower] * (1 - fraction) + ordered[upper] * fraction
