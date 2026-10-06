"""Measure the current local pipeline with one licensed FLEURS WAV per language.

Explicit existing model directories only; no downloads, capture devices, cloud,
user configuration/history, or visible windows. This is a new paced-file baseline,
not a comparison against historical 24-second-window measurements.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import time
from dataclasses import asdict, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
from replay_metadata import source_metadata

from lingua_relay.asr.faster_whisper import FasterWhisperRecognizer
from lingua_relay.asr.metrics import error_rate
from lingua_relay.asr.streaming import StreamingAsrEngine
from lingua_relay.audio.processing import measure_level
from lingua_relay.audio.types import AudioChunk
from lingua_relay.config import AsrSettings, Settings
from lingua_relay.mt.m2m100 import M2M100Translator
from lingua_relay.mt.streaming import StreamingTranslationEngine
from lingua_relay.service import RealtimeCaptionService
from lingua_relay.telemetry import (
    GateObservation,
    TraceCollector,
    configuration_fingerprint,
    evaluate_gates,
)
from lingua_relay.translation import build_m2m100_registry

TARGETS = {"en": "zh", "zh": "en", "ja": "ko", "ko": "ja"}
ASR_FILES = ("model.bin", "config.json", "tokenizer.json", "vocabulary.txt")
MT_FILES = (
    "model.bin",
    "config.json",
    "sentencepiece.bpe.model",
    "shared_vocabulary.json",
    "special_tokens_map.json",
    "tokenizer_config.json",
    "vocab.json",
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def check_model_directory(path: Path, required: tuple[str, ...]) -> Path:
    resolved = path.resolve(strict=True)
    if not resolved.is_dir() or any(not (resolved / name).is_file() for name in required):
        raise ValueError("local model directory is incomplete; no download is permitted")
    return resolved


def read_fixture_wav(path: Path) -> np.ndarray:
    """Accept only bounded mono 16 kHz PCM16/IEEE-float32 WAVs, without conversion."""
    import av

    blocks = []
    count = 0
    with av.open(str(path), format="wav") as container:
        streams = list(container.streams.audio)
        if len(streams) != 1:
            raise ValueError("fixtures must have exactly one audio stream")
        stream = streams[0]
        context = stream.codec_context
        if (
            context.name not in {"pcm_s16le", "pcm_f32le"}
            or context.sample_rate != 16000
            or len(context.layout.channels) != 1
        ):
            raise ValueError("fixtures must be mono PCM16/float32 16 kHz WAVs <= 60 seconds")
        for frame in container.decode(stream):
            if frame.sample_rate != 16000 or len(frame.layout.channels) != 1:
                raise ValueError("fixture audio layout changed while decoding")
            count += frame.samples
            if count > 60 * 16000:
                raise ValueError("fixtures must be <= 60 seconds")
            values = frame.to_ndarray().reshape(-1)
            values = values.astype(np.float32) / 32768.0 if values.dtype == np.int16 else values
            if values.dtype != np.float32 or not np.isfinite(values).all():
                raise ValueError("fixture decoded to invalid PCM samples")
            blocks.append(values)
    if count == 0:
        raise ValueError("fixtures must be nonempty")
    return np.concatenate(blocks)


def load_fixtures(manifest: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    manifest = manifest.resolve(strict=True)
    data = json.loads(manifest.read_text(encoding="utf-8"))
    if (
        data.get("dataset") != "google/fleurs"
        or data.get("license") != "CC-BY-4.0"
        or not data.get("revision")
        or data.get("sampling_rate") != 16000
    ):
        raise ValueError("this bounded replay requires the licensed 16 kHz FLEURS manifest")
    selected = {}
    for item in data.get("samples", []):
        language = item.get("language")
        if language not in TARGETS or language in selected:
            continue
        path = (manifest.parent / item["path"]).resolve(strict=True)
        if not path.is_relative_to(manifest.parent):
            raise ValueError("fixture path escapes the explicit corpus directory")
        if not isinstance(item.get("reference"), str) or not item["reference"].strip():
            raise ValueError("fixture reference is missing")
        if re.fullmatch(r"[0-9]{1,20}", str(item.get("id", ""))) is None:
            raise ValueError("expected public numeric FLEURS sample ID")
        selected[language] = {**item, "path": path, "decoded_samples": read_fixture_wav(path)}
    if set(selected) != set(TARGETS):
        raise ValueError("one existing WAV is required for each of the four source languages")
    attribution = {
        "dataset": "google/fleurs",
        "license": "CC-BY-4.0",
        "dataset_url": "https://huggingface.co/datasets/google/fleurs",
        "revision": data["revision"],
        "manifest_sha256": sha256_file(manifest),
        "selection": "first existing manifest entry per language; four directions only",
    }
    return attribution, [selected[language] for language in TARGETS]


def make_local_recognizer(settings: AsrSettings) -> FasterWhisperRecognizer:
    # The normal loader retries download on local failure. The injected factory
    # has no such fallback and also forbids tokenizer downloads explicitly.
    from faster_whisper import WhisperModel

    def local_factory(model, **kwargs):
        return WhisperModel(model, local_files_only=True, **kwargs)

    recognizer = FasterWhisperRecognizer(settings, model_factory=local_factory)
    recognizer.load()
    return recognizer


def _replay_fixture(fixture, settings, recognizer, translator, application, overlay):
    source, target = fixture["language"], TARGETS[fixture["language"]]
    trace = TraceCollector(capacity=2048)
    trace.observe_rss()
    final_sources: dict[str, str] = {}
    final_keys: set[tuple[str, int]] = set()
    captions = 0
    failed_captions = 0

    def on_transcript(event, target_language):
        overlay.publish_transcript(event, target_language)
        service.acknowledge_ui(event)
        if event.state == "final":
            final_sources[event.segment_id] = event.text
            final_keys.add((hashlib.sha256(event.segment_id.encode()).hexdigest(), event.revision))

    def on_caption(event):
        nonlocal captions, failed_captions
        captions += 1
        failed_captions += bool(event.error)
        overlay.publish(event)
        service.acknowledge_ui(event)

    settings = replace(
        settings,
        app=replace(
            settings.app, source_language=source, target_language=target, history_enabled=False
        ),
    )
    service = RealtimeCaptionService(
        settings, on_caption=on_caption, on_transcript=on_transcript, trace=trace
    )
    asr = StreamingAsrEngine(recognizer, settings.asr, trace=trace)
    mt = StreamingTranslationEngine(
        build_m2m100_registry(translator), settings.translation, trace=trace
    )
    service._asr, service._mt = asr, mt
    audio = fixture["decoded_samples"]
    chunk_samples = settings.audio.chunk_ms * 16
    # Padding and a measured silence tail allow normal endpointing without an
    # early abort flush; both are disclosed, not counted as original audio.
    padding = (-len(audio)) % chunk_samples
    silence = settings.asr.min_silence_ms * 16 + chunk_samples
    replay_audio = np.pad(audio, (0, padding + silence))
    start_ns = time.monotonic_ns()
    deadline = time.monotonic() + len(replay_audio) / 16000 + 60
    submission_failed = False
    timed_out = False

    def pump():
        service.pump_once()
        application.processEvents()

    try:
        asr.start()
        mt.start()
        for sequence, offset in enumerate(range(0, len(replay_audio), chunk_samples)):
            values = replay_audio[offset : offset + chunk_samples].copy()
            values.setflags(write=False)
            captured_ns = start_ns + round(offset * 1e9 / 16000)
            due = (captured_ns + round(len(values) * 1e9 / 16000)) / 1e9
            while time.monotonic() < due and time.monotonic() < deadline:
                pump()
                time.sleep(min(0.002, max(0.0, due - time.monotonic())))
            if time.monotonic() >= deadline:
                timed_out = True
                break
            try:
                asr.submit_chunk(
                    AudioChunk(
                        values,
                        sequence,
                        captured_ns,
                        16000,
                        "licensed_file",
                        "licensed_file",
                        measure_level(values, settings.audio.silence_dbfs),
                    ),
                    language=source,
                )
            except (TimeoutError, RuntimeError):
                submission_failed = True
                trace.increment("input_admission_failures")
                break
            pump()
            trace.observe_rss()
        while time.monotonic() < deadline:
            pump()
            rows = trace.snapshot()["traces"]
            translated = {
                (row["trace_id"], row["revision"])
                for row in rows
                if "mt_completed" in row["stages"] or "failed" in row["stages"]
            }
            expected = asr.snapshot().final_requests_added
            if (
                expected > 0
                and len(final_keys) == expected
                and final_keys <= translated
                and mt.snapshot().event_queue_depth == 0
                and service.telemetry_snapshot()["pipeline"]["pending_finals"] == 0
            ):
                break
            time.sleep(0.005)
        else:
            timed_out = True
    finally:
        service._stop_deadline = time.monotonic() + 10.0
        service._shutdown_workers()
        trace.observe_rss()
    trace_result = service.telemetry_snapshot()
    hypothesis = " ".join(final_sources.values())
    errors, units, rate, metric = error_rate(fixture["reference"], hypothesis, source)
    return {
        "source": source,
        "target": target,
        "sample_id": str(fixture["id"]),
        "audio_sha256": sha256_file(fixture["path"]),
        "audio_duration_ms": len(audio) / 16,
        "padding_samples": padding,
        "silence_tail_samples": silence,
        "elapsed_ms": (time.monotonic_ns() - start_ns) / 1e6,
        "final_asr_segments": len(final_keys),
        "caption_events_adopted": captions,
        "failed_captions": failed_captions,
        "submission_failed": submission_failed,
        "timed_out": timed_out,
        "workers_stopped": not asr.worker_alive and not mt.worker_alive,
        "asr_reference_measurement": {
            "metric": metric,
            "errors": errors,
            "units": units,
            "error_rate": rate,
            "sample_count": 1,
        },
        "trace": trace_result,
    }


def run_local_replay(
    manifest: Path,
    asr_directory: Path,
    mt_directory: Path,
    *,
    device: str = "cpu",
    compute_type: str = "int8",
) -> dict[str, Any]:
    asr_directory = check_model_directory(asr_directory, ASR_FILES)
    mt_directory = check_model_directory(mt_directory, MT_FILES)
    attribution, fixtures = load_fixtures(manifest)
    files = {
        "asr": {name: sha256_file(asr_directory / name) for name in ASR_FILES},
        "mt": {name: sha256_file(mt_directory / name) for name in MT_FILES},
    }
    original_environment = {
        name: os.environ.get(name)
        for name in ("HF_HUB_OFFLINE", "TRANSFORMERS_OFFLINE", "QT_QPA_PLATFORM")
    }
    os.environ["HF_HUB_OFFLINE"] = os.environ["TRANSFORMERS_OFFLINE"] = "1"
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    overlay = None
    try:
        from PySide6.QtWidgets import QApplication

        from lingua_relay.ui.overlay import CaptionOverlay

        defaults = Settings()
        settings = replace(
            defaults,
            app=replace(defaults.app, history_enabled=False),
            asr=replace(
                defaults.asr, model=str(asr_directory), device=device, compute_type=compute_type
            ),
            translation=replace(
                defaults.translation,
                model_path=mt_directory,
                device=device,
                compute_type=compute_type,
                cache_size=0,
            ),
        )
        settings.validate()
        load_started = time.monotonic_ns()
        recognizer = make_local_recognizer(settings.asr)
        translator = M2M100Translator(settings.translation)
        translator.load(warmup=False)
        model_load_ms = (time.monotonic_ns() - load_started) / 1e6
        application = QApplication.instance() or QApplication([])
        overlay = CaptionOverlay(settings.overlay)
        results = [
            _replay_fixture(fixture, settings, recognizer, translator, application, overlay)
            for fixture in fixtures
        ]
        configuration = {
            "scope": "local_paced_file_replay",
            "routes": TARGETS,
            "asr": {**asdict(settings.asr), "model": "explicit_local_directory"},
            "mt": {**asdict(settings.translation), "model_path": "explicit_local_directory"},
            "audio": {
                "sample_rate": 16000,
                "chunk_ms": settings.audio.chunk_ms,
                "silence_dbfs": settings.audio.silence_dbfs,
            },
            "asr_runtime": asdict(recognizer.runtime),
            "mt_runtime": asdict(translator.runtime),
            "model_file_sha256": files,
            "corpus_manifest_sha256": attribution["manifest_sha256"],
            "qt": "hidden_widget_update_not_paint",
            "model_warmup": False,
            "models_reused_between_languages": True,
        }
        config_id = configuration_fingerprint(configuration)
        observations = []
        for result in results:
            source = result["source"]
            trace = result["trace"]
            checks = {
                "finals_observed": result["final_asr_segments"] > 0,
                "no_submission_failure": not result["submission_failed"],
                "no_caption_errors": result["failed_captions"] == 0,
                "within_watchdog": not result["timed_out"],
                "workers_stopped": result["workers_stopped"],
                "window_complete": trace["evicted_trace_entries"] == 0,
                "no_failed_traces": trace["outcomes"]["failed"] == 0,
                "no_overload": not trace["pipeline"]["overloaded"],
                "no_invalid_timestamp_pairs": not any(
                    metric["invalid_order"] for metric in trace["latencies"].values()
                ),
            }
            observations.extend(
                GateObservation("functional", f"{source}_{name}", config_id, value)
                for name, value in checks.items()
            )
            for name, metric in trace["latencies"].items():
                if metric["p95_ms"] is not None:
                    observations.append(
                        GateObservation(
                            "performance",
                            f"{source}_{name}",
                            config_id,
                            metric["p95_ms"],
                            sample_count=metric["measured"],
                        )
                    )
            observations.append(
                GateObservation(
                    "quality",
                    f"{source}_reference_error_rate",
                    config_id,
                    result["asr_reference_measurement"]["error_rate"],
                )
            )
        return {
            "schema_version": 1,
            "created_at": datetime.now(UTC).isoformat(),
            "source": source_metadata(),
            "scope": "local_paced_file_replay",
            "configuration": configuration,
            "configuration_id": config_id,
            "corpus": attribution,
            "model_load_ms": model_load_ms,
            "runtime": {"python": platform.python_version(), "platform": platform.system()},
            "results": results,
            "gates": evaluate_gates(observations),
            "limitations": [
                "New current-configuration baseline, not a before/after improvement claim.",
                "One public sample per language; four routes, not all twelve directions.",
                "ASR references measured separately; no MT semantic or human quality review.",
                "No approved performance/quality thresholds; those gates remain not_evaluated.",
                "1x file injection bypasses physical capture/audio routing and recording.",
                "Hidden Qt widget updates are not measured physical display or paint events.",
                "No model warmup; first fixture includes cold inference; models reused thereafter.",
                "Short corpus and sampled RSS do not prove sustained or peak-resource performance.",
            ],
        }
    finally:
        if overlay is not None:
            overlay.close()
            overlay.deleteLater()
        for name, value in original_environment.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--asr-directory", type=Path, required=True)
    parser.add_argument("--mt-directory", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--device", choices=("cpu", "cuda"), default="cpu")
    parser.add_argument("--compute-type", default="int8")
    args = parser.parse_args()
    if args.output.exists():
        parser.error("output exists; choose a new path to preserve earlier evidence")
    report = run_local_replay(
        args.manifest,
        args.asr_directory,
        args.mt_directory,
        device=args.device,
        compute_type=args.compute_type,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")
    print(json.dumps({name: item["status"] for name, item in report["gates"].items()}))
    return 0 if report["gates"]["functional"]["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
