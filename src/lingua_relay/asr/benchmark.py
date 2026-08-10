from __future__ import annotations

import json
import math
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import numpy as np

from lingua_relay.asr.faster_whisper import FasterWhisperRecognizer
from lingua_relay.asr.metrics import error_rate
from lingua_relay.config import AsrSettings
from lingua_relay.languages import SUPPORTED_LANGUAGES


@dataclass(frozen=True, slots=True)
class Fixture:
    sample_id: str
    language: str
    path: Path
    reference: str
    duration_ms: float


def load_manifest(path: Path) -> tuple[Fixture, ...]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    base = path.parent
    fixtures = tuple(
        Fixture(
            sample_id=str(item["id"]),
            language=str(item["language"]),
            path=(base / item["path"]).resolve(),
            reference=str(item["reference"]),
            duration_ms=float(item["duration_ms"]),
        )
        for item in raw["samples"]
    )
    if not fixtures:
        raise ValueError("benchmark manifest contains no samples")
    unknown = {fixture.language for fixture in fixtures} - set(SUPPORTED_LANGUAGES)
    if unknown:
        raise ValueError(f"manifest contains unsupported languages: {sorted(unknown)}")
    missing = [str(fixture.path) for fixture in fixtures if not fixture.path.exists()]
    if missing:
        raise FileNotFoundError(f"missing benchmark audio: {missing[0]}")
    return fixtures


def run_benchmark(
    settings: AsrSettings,
    manifest_path: Path,
    *,
    limit_per_language: int | None = None,
    sustain_audio_minutes: float = 0,
    download_root: Path = Path("models"),
) -> dict[str, Any]:
    fixtures = _limit_by_language(load_manifest(manifest_path), limit_per_language)
    recognizer = FasterWhisperRecognizer(settings, download_root=str(download_root))
    recognizer.load()
    process = _process()
    rss_before = process.memory_info().rss if process is not None else None
    samples: list[dict[str, Any]] = []
    partial_latencies: list[float] = []

    for fixture in fixtures:
        audio = _load_audio(fixture.path)
        started = time.perf_counter()
        result = recognizer.transcribe(audio, language=fixture.language)
        wall_ms = (time.perf_counter() - started) * 1000
        errors, units, rate, metric = error_rate(fixture.reference, result.text, fixture.language)
        first_partial_ms, first_partial_text = _measure_first_partial(
            recognizer, audio, fixture.language, settings
        )
        partial_latencies.append(first_partial_ms)
        samples.append(
            {
                "id": fixture.sample_id,
                "language": fixture.language,
                "reference": fixture.reference,
                "hypothesis": result.text,
                "duration_ms": fixture.duration_ms,
                "wall_ms": wall_ms,
                "rtf": wall_ms / max(1, fixture.duration_ms),
                "metric": metric,
                "errors": errors,
                "units": units,
                "error_rate": rate,
                "first_partial_ms": first_partial_ms,
                "first_partial_text": first_partial_text,
            }
        )

    sustained = _run_sustain(recognizer, fixtures, sustain_audio_minutes)
    rss_after = process.memory_info().rss if process is not None else None
    language_metrics = _aggregate_languages(samples)
    return {
        "schema_version": 1,
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "model": settings.model,
        "model_revision": recognizer.revision,
        "runtime": asdict(recognizer.runtime),
        "load_ms": recognizer.load_ms,
        "manifest": str(manifest_path),
        "sample_count": len(samples),
        "settings": asdict(settings),
        "aggregate": {
            "audio_minutes": sum(sample["duration_ms"] for sample in samples) / 60_000,
            "wall_seconds": sum(sample["wall_ms"] for sample in samples) / 1000,
            "rtf": _weighted_rtf(samples),
            "first_partial_p50_ms": _percentile(partial_latencies, 50),
            "first_partial_p95_ms": _percentile(partial_latencies, 95),
            "rss_before_mib": _to_mib(rss_before),
            "rss_after_mib": _to_mib(rss_after),
            "rss_growth_mib": _to_mib(
                None if rss_before is None or rss_after is None else rss_after - rss_before
            ),
        },
        "languages": language_metrics,
        "sustain": sustained,
        "samples": samples,
    }


def write_report(report: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _load_audio(path: Path) -> np.ndarray:
    try:
        from faster_whisper.audio import decode_audio
    except ImportError as error:
        raise RuntimeError("faster-whisper is required to decode benchmark audio") from error
    return np.asarray(decode_audio(str(path), sampling_rate=16_000), dtype=np.float32)


def _measure_first_partial(
    recognizer: FasterWhisperRecognizer,
    audio: np.ndarray,
    language: str,
    settings: AsrSettings,
) -> tuple[float, str]:
    active_audio = _trim_leading_silence(audio)
    step_samples = max(1, round(settings.partial_interval_ms * 16_000 / 1000))
    max_samples = min(len(active_audio), round(settings.max_window_seconds * 16_000))
    worker_ready_ms = 0.0
    for end in range(step_samples, max_samples + step_samples, step_samples):
        window = active_audio[: min(end, len(active_audio))]
        if len(window) < step_samples:
            window = np.pad(window, (0, step_samples - len(window)))
        result = recognizer.transcribe(window, language=language, vad_filter=False)
        available_ms = min(end, len(active_audio)) * 1000 / 16_000
        worker_ready_ms = max(available_ms, worker_ready_ms) + result.inference_ms
        if result.text:
            return worker_ready_ms, result.text
        if end >= max_samples:
            break
    return worker_ready_ms, ""


def _trim_leading_silence(audio: np.ndarray) -> np.ndarray:
    chunk_samples = 5_120
    threshold = 10 ** (-55 / 20)
    for start in range(0, len(audio), chunk_samples):
        chunk = audio[start : start + chunk_samples]
        if chunk.size and float(np.sqrt(np.mean(np.square(chunk)))) >= threshold:
            return audio[start:]
    return audio


def _limit_by_language(fixtures: tuple[Fixture, ...], limit: int | None) -> tuple[Fixture, ...]:
    if limit is None:
        return fixtures
    counts: dict[str, int] = {}
    selected: list[Fixture] = []
    for fixture in fixtures:
        count = counts.get(fixture.language, 0)
        if count < limit:
            selected.append(fixture)
            counts[fixture.language] = count + 1
    return tuple(selected)


def _aggregate_languages(samples: list[dict[str, Any]]) -> dict[str, Any]:
    output: dict[str, Any] = {}
    for language in SUPPORTED_LANGUAGES:
        selected = [sample for sample in samples if sample["language"] == language]
        if not selected:
            continue
        errors = sum(sample["errors"] for sample in selected)
        units = sum(sample["units"] for sample in selected)
        output[language] = {
            "metric": selected[0]["metric"],
            "error_rate": errors / max(1, units),
            "errors": errors,
            "units": units,
            "sample_count": len(selected),
            "rtf": _weighted_rtf(selected),
            "first_partial_p50_ms": _percentile(
                [sample["first_partial_ms"] for sample in selected], 50
            ),
            "first_partial_p95_ms": _percentile(
                [sample["first_partial_ms"] for sample in selected], 95
            ),
        }
    return output


def _run_sustain(
    recognizer: FasterWhisperRecognizer,
    fixtures: tuple[Fixture, ...],
    minutes: float,
) -> dict[str, Any] | None:
    if minutes <= 0:
        return None
    by_language = {
        language: [fixture for fixture in fixtures if fixture.language == language]
        for language in SUPPORTED_LANGUAGES
    }
    missing = [language for language, items in by_language.items() if not items]
    if missing:
        raise ValueError(f"sustain test has no fixtures for: {missing}")
    target_ms = minutes * 60_000
    process = _process()
    rss_before = process.memory_info().rss if process is not None else None
    started = time.perf_counter()
    report: dict[str, Any] = {}
    for language, language_fixtures in by_language.items():
        processed_ms = 0.0
        iterations = 0
        errors = 0
        while processed_ms < target_ms:
            fixture = language_fixtures[iterations % len(language_fixtures)]
            audio = _load_audio(fixture.path)
            try:
                recognizer.transcribe(audio, language=language)
            except Exception:
                errors += 1
            processed_ms += fixture.duration_ms
            iterations += 1
        report[language] = {
            "audio_minutes": processed_ms / 60_000,
            "iterations": iterations,
            "errors": errors,
        }
    wall_seconds = time.perf_counter() - started
    rss_after = process.memory_info().rss if process is not None else None
    return {
        "target_minutes_per_language": minutes,
        "languages": report,
        "wall_seconds": wall_seconds,
        "rss_before_mib": _to_mib(rss_before),
        "rss_after_mib": _to_mib(rss_after),
        "rss_growth_mib": _to_mib(
            None if rss_before is None or rss_after is None else rss_after - rss_before
        ),
        "passed": all(item["errors"] == 0 for item in report.values()),
    }


def _process() -> Any | None:
    try:
        import psutil
    except ImportError:
        return None
    return psutil.Process()


def _weighted_rtf(samples: list[dict[str, Any]]) -> float:
    return sum(sample["wall_ms"] for sample in samples) / max(
        1, sum(sample["duration_ms"] for sample in samples)
    )


def _percentile(values: list[float], percentile: int) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    rank = (len(ordered) - 1) * percentile / 100
    low = math.floor(rank)
    high = math.ceil(rank)
    if low == high:
        return ordered[low]
    return ordered[low] + (ordered[high] - ordered[low]) * (rank - low)


def _to_mib(value: int | None) -> float | None:
    return None if value is None else value / 1024 / 1024
