from __future__ import annotations

import queue
import threading
from dataclasses import replace
from pathlib import Path

import pytest

from lingua_relay.asr.types import AsrEvent
from lingua_relay.config import TranslationSettings
from lingua_relay.history import JsonlHistory
from lingua_relay.mt.streaming import StreamingTranslationEngine
from lingua_relay.mt.types import TranslationResult
from lingua_relay.telemetry import TraceCollector
from lingua_relay.translation import TranslationRouteRegistry


class FakeTranslator:
    def translate(self, text: str, *, source: str, target: str) -> TranslationResult:
        return TranslationResult(f"{target}:{text}", source, target, 4.5)


class BrokenTranslator:
    def translate(self, text: str, *, source: str, target: str) -> TranslationResult:
        raise RuntimeError("offline")


def _asr_event(*, state: str = "final", revision: int = 1, text: str = "hello") -> AsrEvent:
    return AsrEvent(
        text=text,
        stable_text=text,
        unstable_text="",
        newly_stable_text="hello",
        language="en",
        state=state,  # type: ignore[arg-type]
        segment_id="segment-1",
        revision=revision,
        started_at_ms=10,
        ended_at_ms=20,
        emitted_at_ns=1,
        timings_ms={"asr": 7.0},
    )


def _registry(translator: object) -> TranslationRouteRegistry:
    registry = TranslationRouteRegistry()
    registry.register("en", "zh", "fake", translator)  # type: ignore[arg-type]
    return registry


def test_final_translation_is_emitted_and_written_to_history(tmp_path: Path) -> None:
    history = JsonlHistory(tmp_path / "history.jsonl")
    engine = StreamingTranslationEngine(
        _registry(FakeTranslator()), TranslationSettings(), history=history
    )
    engine.start()
    engine.submit(_asr_event(), target="zh")

    caption = engine.get_event(timeout=2)
    engine.stop()

    assert caption.translated_text == "zh:hello"
    assert caption.timings_ms["translation"] == 4.5
    assert tuple(history.read_all())[0]["translated_text"] == "zh:hello"


def test_translation_failure_keeps_source_for_overlay_fallback() -> None:
    engine = StreamingTranslationEngine(_registry(BrokenTranslator()), TranslationSettings())
    engine.start()
    engine.submit(_asr_event(), target="zh")

    caption = engine.get_event(timeout=2)
    engine.stop()

    assert caption.source_text == "hello"
    assert caption.translated_text == ""
    assert caption.error == "RuntimeError: offline"
    assert engine.snapshot().translation_errors == 1


@pytest.mark.parametrize("error_type", [OSError, PermissionError])
def test_history_write_failure_preserves_final_output_and_worker(error_type) -> None:
    class FailingHistory:
        def __init__(self) -> None:
            self.attempted = []
            self.saved = []
            self.completed = threading.Event()

        def append(self, event) -> None:
            self.attempted.append(event.segment_id)
            if len(self.attempted) <= 2:
                raise error_type("synthetic sensitive path must not enter diagnostics")
            self.saved.append(event)
            self.completed.set()

    history = FailingHistory()
    trace = TraceCollector()
    engine = StreamingTranslationEngine(
        _registry(FakeTranslator()),
        TranslationSettings(queue_capacity=3, event_queue_capacity=3),
        history=history,  # type: ignore[arg-type]
        trace=trace,
    )
    engine.start()
    try:
        for index in range(3):
            assert engine.submit(
                replace(_asr_event(text=f"text-{index}"), segment_id=f"final-{index}"),
                target="zh",
            )
        captions = [engine.get_event(timeout=1) for _ in range(3)]
        assert history.completed.wait(1)
        snapshot = engine.snapshot()
        assert snapshot.worker_alive and snapshot.running and not snapshot.overloaded
        assert snapshot.queue_depth == 0
        assert snapshot.events_emitted == snapshot.final_requests_added == 3
        assert snapshot.history_errors == 2
        assert snapshot.translation_errors == snapshot.final_requests_aborted == 0
        assert snapshot.final_outputs_rejected == snapshot.final_events_aborted == 0
        assert snapshot.last_error == f"History write failed: {error_type.__name__}"
        assert trace.snapshot()["counters"]["mt_history_errors"] == 2
        assert (
            [event.segment_id for event in captions]
            == history.attempted
            == [
                "final-0",
                "final-1",
                "final-2",
            ]
        )
        assert [event.translated_text for event in captions] == [
            "zh:text-0",
            "zh:text-1",
            "zh:text-2",
        ]
        assert all(event.error is None for event in captions)
        assert [event.segment_id for event in history.saved] == ["final-2"]
        with pytest.raises(queue.Empty):
            engine.get_event(timeout=0)
    finally:
        engine.stop(timeout=1)
    assert not engine.worker_alive


class BlockingTranslator:
    def __init__(self) -> None:
        self.started = threading.Event()
        self.release = threading.Event()
        self.calls = 0

    def translate(self, text: str, *, source: str, target: str) -> TranslationResult:
        self.calls += 1
        if self.calls == 1:
            self.started.set()
            assert self.release.wait(2)
        return TranslationResult(f"{target}:{text}", source, target, 1.0)


def test_completed_partial_translation_is_shown_while_newer_text_waits() -> None:
    translator = BlockingTranslator()
    engine = StreamingTranslationEngine(_registry(translator), TranslationSettings())
    engine.start()
    engine.submit(_asr_event(state="partial", revision=1, text="first"), target="zh")
    assert translator.started.wait(2)
    engine.submit(_asr_event(state="partial", revision=2, text="second"), target="zh")
    translator.release.set()

    first = engine.get_event(timeout=2)
    engine.stop()

    assert first.revision == 1
    assert first.translated_text == "zh:first"
    assert engine.snapshot().stale_results_dropped == 0
