"""Exercise real ASR/MT workers and service pumping with synthetic model doubles.

No capture devices, model loaders, user configuration/history, or API are used.
Optional hidden Qt widgets acknowledge updates, not rendering or display latency.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import platform
import time
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
from replay_metadata import source_metadata

from lingua_relay.asr.streaming import StreamingAsrEngine
from lingua_relay.asr.types import AsrEvent, AsrResult
from lingua_relay.audio.types import AudioChunk, AudioLevel
from lingua_relay.config import Settings
from lingua_relay.events import CaptionEvent
from lingua_relay.languages import SUPPORTED_LANGUAGES
from lingua_relay.mt.streaming import StreamingTranslationEngine
from lingua_relay.mt.types import TranslationResult
from lingua_relay.service import RealtimeCaptionService
from lingua_relay.telemetry import (
    GateObservation,
    TraceCollector,
    configuration_fingerprint,
    evaluate_gates,
)
from lingua_relay.translation import build_m2m100_registry


class SyntheticRecognizer:
    def transcribe(self, samples, *, language, vad_filter=None):
        return AsrResult("Synthetic source phrase", language, len(samples) / 16, 0.0)


class SyntheticTranslator:
    def translate(self, text, *, source, target):
        return TranslationResult("Synthetic translated phrase", source, target, 0.0)


def run_replay(
    *,
    segments: int = 8,
    chunk_ms: int = 80,
    source: str = "en",
    target: str = "zh",
    qt_ui: bool = False,
    timeout_seconds: float = 30.0,
    trace_capacity: int = 512,
) -> dict[str, Any]:
    if type(segments) is not int or not 1 <= segments <= 128:
        raise ValueError("segments must be between 1 and 128")
    if type(chunk_ms) is not int or chunk_ms not in {20, 80, 320}:
        raise ValueError("chunk_ms must be 20, 80 or 320")
    if source not in SUPPORTED_LANGUAGES or target not in SUPPORTED_LANGUAGES or source == target:
        raise ValueError("select two distinct supported languages")
    if not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
        raise ValueError("timeout_seconds must be positive and finite")
    trace = TraceCollector(capacity=trace_capacity)
    trace.observe_rss()
    defaults = Settings()
    settings = replace(
        defaults,
        app=replace(
            defaults.app, source_language=source, target_language=target, history_enabled=False
        ),
        audio=replace(defaults.audio, chunk_ms=chunk_ms),
        asr=replace(
            defaults.asr,
            min_speech_ms=chunk_ms,
            min_silence_ms=chunk_ms,
            preferred_silence_ms=chunk_ms,
            partial_interval_ms=chunk_ms,
            adaptive_partial_enabled=False,
            punctuation_boundary_enabled=False,
        ),
    )
    settings.validate()
    configuration = {
        "mode": "synthetic_pipeline_replay",
        "source_language": source,
        "target_language": target,
        "segments": segments,
        "chunk_ms": chunk_ms,
        "speech_chunks_per_segment": 2,
        "silence_chunks_per_segment": 1,
        "sample_rate": 16000,
        "asr_model": "synthetic_test_double",
        "mt_model": "synthetic_test_double",
        "llm": "off",
        "history": False,
        "adaptive_partial": False,
        "punctuation_boundary": False,
        "qt_widget_updates": qt_ui,
        "trace_capacity": trace_capacity,
        "asr_request_capacity": settings.asr.inference_queue_capacity,
        "asr_event_capacity": settings.asr.event_queue_capacity,
        "mt_request_capacity": settings.translation.queue_capacity,
        "mt_event_capacity": settings.translation.event_queue_capacity,
    }
    configuration_id = configuration_fingerprint(configuration)
    finals: set[str] = set()
    duplicate_finals = 0
    failed_captions = 0
    caption_count = 0
    application = overlay = None
    original_qt_platform = os.environ.get("QT_QPA_PLATFORM")
    if qt_ui:
        from PySide6.QtWidgets import QApplication

        from lingua_relay.ui.overlay import CaptionOverlay

        if QApplication.instance() is None:
            os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        application = QApplication.instance() or QApplication([])
        overlay = CaptionOverlay(settings.overlay)

    def on_transcript(event: AsrEvent, target_language: str) -> None:
        if overlay is not None:
            overlay.publish_transcript(event, target_language)
            service.acknowledge_ui(event)

    def on_caption(event: CaptionEvent) -> None:
        nonlocal duplicate_finals, failed_captions, caption_count
        caption_count += 1
        failed_captions += bool(event.error)
        if event.state == "final":
            duplicate_finals += event.segment_id in finals
            finals.add(event.segment_id)
        if overlay is not None:
            overlay.publish(event)
            service.acknowledge_ui(event)

    service = RealtimeCaptionService(
        settings, on_caption=on_caption, on_transcript=on_transcript, trace=trace
    )
    asr = StreamingAsrEngine(SyntheticRecognizer(), settings.asr, trace=trace)
    mt = StreamingTranslationEngine(
        build_m2m100_registry(SyntheticTranslator()), settings.translation, trace=trace
    )
    # Deliberately inject workers without calling start(): no model/capture loading.
    service._asr, service._mt = asr, mt
    started_ns = time.monotonic_ns()
    deadline = time.monotonic() + timeout_seconds
    timed_out = False
    input_samples = 0
    sequence = 0

    def pump() -> None:
        service.pump_once()
        if application is not None:
            application.processEvents()

    def wait_until(due: float) -> bool:
        while time.monotonic() < due:
            pump()
            remaining = min(due, deadline) - time.monotonic()
            if remaining <= 0:
                return False
            time.sleep(min(0.002, remaining))
        return time.monotonic() < deadline

    try:
        asr.start()
        mt.start()
        for segment_index in range(segments):
            for silent in (False, False, True):
                captured_at_ns = time.monotonic_ns()
                if not wait_until(captured_at_ns / 1e9 + chunk_ms / 1000):
                    timed_out = True
                    break
                samples = np.full(chunk_ms * 16, 0.0 if silent else 0.125, dtype=np.float32)
                samples.setflags(write=False)
                level = (
                    AudioLevel(0.0, 0.0, -120.0, True)
                    if silent
                    else AudioLevel(0.125, 0.125, -18.0, False)
                )
                asr.submit_chunk(
                    AudioChunk(
                        samples, sequence, captured_at_ns, 16000, "synthetic", "synthetic", level
                    ),
                    language=source,
                )
                input_samples += len(samples)
                sequence += 1
                pump()
                trace.observe_rss()
            if timed_out:
                break
            while len(finals) <= segment_index and time.monotonic() < deadline:
                pump()
                time.sleep(0.001)
            if len(finals) <= segment_index:
                timed_out = True
                break
    finally:
        # No service thread exists; explicitly use its normal worker cleanup.
        service._stop_deadline = time.monotonic() + 2.0
        service._shutdown_workers()
        if overlay is not None:
            overlay.close()
            overlay.deleteLater()
            application.processEvents()
        if qt_ui:
            if original_qt_platform is None:
                os.environ.pop("QT_QPA_PLATFORM", None)
            else:
                os.environ["QT_QPA_PLATFORM"] = original_qt_platform
    trace.observe_rss()
    snapshot = service.telemetry_snapshot()
    checks = {
        "final_segments_complete": len(finals) == segments,
        "final_segments_unique": duplicate_finals == 0,
        "no_caption_errors": failed_captions == 0,
        "completed_before_watchdog": not timed_out,
        "workers_stopped": not asr.worker_alive and not mt.worker_alive,
        "trace_window_complete": snapshot["evicted_trace_entries"] == 0,
        "no_inference_errors": asr.snapshot().inference_errors == 0,
        "no_translation_errors": mt.snapshot().translation_errors == 0,
        "no_invalid_timestamp_pairs": not any(
            metric["invalid_order"] for metric in snapshot["latencies"].values()
        ),
    }
    observations = [
        GateObservation("functional", name, configuration_id, result)
        for name, result in checks.items()
    ]
    for name, metric in snapshot["latencies"].items():
        if metric["p95_ms"] is not None:
            observations.append(
                GateObservation(
                    "performance",
                    name,
                    configuration_id,
                    metric["p95_ms"],
                    sample_count=metric["measured"],
                )
            )
    return {
        "schema_version": 1,
        "created_at": datetime.now(UTC).isoformat(),
        "source": source_metadata(),
        "scope": "synthetic_pipeline_replay",
        "configuration": configuration,
        "configuration_id": configuration_id,
        "runtime": {"python": platform.python_version(), "platform": platform.system()},
        "elapsed_ms": (time.monotonic_ns() - started_ns) / 1e6,
        "inputs": {
            "chunks_submitted": sequence,
            "samples_submitted": input_samples,
            "expected_final_segments": segments,
        },
        "results": {
            "final_segments": len(finals),
            "duplicate_finals": duplicate_finals,
            "caption_events": caption_count,
            "failed_captions": failed_captions,
            "missing_final_segments": segments - len(finals),
        },
        "trace": snapshot,
        "gates": evaluate_gates(observations),
        "limitations": [
            "Real worker queues and service pump; synthetic audio and model doubles only.",
            "No physical capture, recording, user models/configuration/history, or API calls.",
            "Synthetic pacing/segment settings are explicit, not the normal model benchmark.",
            "No accuracy evidence or approved performance thresholds; neither gate can pass.",
            "Optional hidden Qt widget updates do not prove painted or visible captions.",
            "Missing widget acknowledgement is not evidence of audio/recording loss.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--segments", type=int, default=8)
    parser.add_argument("--chunk-ms", type=int, choices=(20, 80, 320), default=80)
    parser.add_argument("--source", choices=tuple(SUPPORTED_LANGUAGES), default="en")
    parser.add_argument("--target", choices=tuple(SUPPORTED_LANGUAGES), default="zh")
    parser.add_argument("--qt-ui", action="store_true")
    args = parser.parse_args()
    if args.output.exists():
        parser.error("output already exists; preserve earlier evidence and choose a new path")
    report = run_replay(
        segments=args.segments,
        chunk_ms=args.chunk_ms,
        source=args.source,
        target=args.target,
        qt_ui=args.qt_ui,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")
    print(json.dumps({name: gate["status"] for name, gate in report["gates"].items()}))
    return 0 if report["gates"]["functional"]["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
