from __future__ import annotations

import queue
import time
from pathlib import Path

import pytest

from lingua_relay.config import CorrectionSettings
from lingua_relay.correction.engine import AsynchronousRevisionEngine
from lingua_relay.correction.types import CorrectionRequest, RevisionResult
from lingua_relay.events import CaptionEvent
from lingua_relay.history import JsonlHistory


class SuccessProvider:
    name = "local"
    model = "mock"
    scope = "local"

    def revise(self, request: CorrectionRequest) -> RevisionResult:
        return RevisionResult(
            request.event.translated_text + "（已修正）", 1.0, self.name, self.model, self.scope
        )


class FailingProvider:
    name = "local"
    model = "offline"
    scope = "local"

    def revise(self, request: CorrectionRequest) -> RevisionResult:
        raise ConnectionError("provider offline")


def _settings(**overrides: object) -> CorrectionSettings:
    values = {
        "provider": "local",
        "model": "mock",
        "requests_per_minute": 100,
        "failure_threshold": 2,
        "recovery_seconds": 30.0,
    }
    values.update(overrides)
    return CorrectionSettings(**values)


def _event(index: int = 0, *, state: str = "final") -> CaptionEvent:
    return CaptionEvent(
        source_text=f"source {index}",
        translated_text=f"fast {index}",
        source_language="en",
        target_language="zh",
        state=state,  # type: ignore[arg-type]
        started_at_ms=index * 100,
        ended_at_ms=index * 100 + 50,
        segment_id=f"segment-{index}",
        revision=index,
    )


def test_emits_traceable_revision_and_keeps_original_history(tmp_path: Path) -> None:
    history = JsonlHistory(tmp_path / "history.jsonl")
    original = _event()
    history.append(original)
    engine = AsynchronousRevisionEngine(SuccessProvider(), _settings(), history=history)
    engine.start()
    try:
        assert engine.submit(original)
        revised = engine.get_event(timeout=2)
    finally:
        engine.stop()

    assert revised.state == "revised"
    assert revised.parent_revision == original.revision
    assert revised.original_translation == original.translated_text
    assert revised.segment_id == original.segment_id
    assert revised.processing_scope == "local"
    assert revised.correction_model == "mock"
    rows = tuple(history.read_all())
    assert [row["state"] for row in rows] == ["final", "revised"]
    assert rows[1]["original_translation"] == "fast 0"


def test_disconnected_provider_produces_no_revision_and_opens_circuit() -> None:
    statuses: list[tuple[str, str]] = []
    engine = AsynchronousRevisionEngine(
        FailingProvider(),
        _settings(),
        on_status=lambda state, message: statuses.append((state, message)),
    )
    engine.start()
    try:
        assert engine.submit(_event(1))
        assert engine.submit(_event(2))
        deadline = time.monotonic() + 2
        while engine.snapshot().provider_errors < 2 and time.monotonic() < deadline:
            time.sleep(0.01)
        assert engine.submit(_event(3))
        deadline = time.monotonic() + 2
        while engine.snapshot().circuit_rejected < 1 and time.monotonic() < deadline:
            time.sleep(0.01)
        with pytest.raises(queue.Empty):
            engine.get_event(timeout=0.05)
    finally:
        engine.stop()

    snapshot = engine.snapshot()
    assert snapshot.provider_errors == 2
    assert snapshot.circuit_state == "open"
    assert snapshot.circuit_rejected >= 1
    assert any("快译继续" in message for _state, message in statuses)


def test_rate_limit_skips_excess_work_without_blocking_submit() -> None:
    engine = AsynchronousRevisionEngine(
        SuccessProvider(), _settings(requests_per_minute=1, failure_threshold=3)
    )
    engine.start()
    try:
        started = time.monotonic()
        assert engine.submit(_event(1))
        assert engine.submit(_event(2))
        assert time.monotonic() - started < 0.1
        engine.get_event(timeout=2)
        deadline = time.monotonic() + 2
        while engine.snapshot().rate_limited < 1 and time.monotonic() < deadline:
            time.sleep(0.01)
    finally:
        engine.stop()

    assert engine.snapshot().rate_limited == 1


def test_context_zero_sends_no_previous_segments() -> None:
    contexts: list[tuple[CaptionEvent, ...]] = []

    class RecordingProvider(SuccessProvider):
        def revise(self, request: CorrectionRequest) -> RevisionResult:
            contexts.append(request.context)
            return super().revise(request)

    engine = AsynchronousRevisionEngine(
        RecordingProvider(), _settings(context_segments=0, requests_per_minute=100)
    )
    engine.start()
    try:
        engine.submit(_event(1))
        engine.get_event(timeout=2)
        engine.submit(_event(2))
        engine.get_event(timeout=2)
    finally:
        engine.stop()

    assert contexts == [(), ()]


def test_disabling_engine_drops_in_flight_revision() -> None:
    class SlowProvider(SuccessProvider):
        def revise(self, request: CorrectionRequest) -> RevisionResult:
            time.sleep(0.05)
            return super().revise(request)

    engine = AsynchronousRevisionEngine(SlowProvider(), _settings())
    engine.start()
    try:
        assert engine.submit(_event())
        time.sleep(0.01)
        engine.set_enabled(False)
        engine.stop()
        with pytest.raises(queue.Empty):
            engine.get_event(timeout=0)
    finally:
        engine.stop()


def test_context_does_not_cross_language_routes() -> None:
    contexts: list[tuple[CaptionEvent, ...]] = []

    class RecordingProvider(SuccessProvider):
        def revise(self, request: CorrectionRequest) -> RevisionResult:
            contexts.append(request.context)
            return super().revise(request)

    engine = AsynchronousRevisionEngine(RecordingProvider(), _settings(context_segments=6))
    first = _event(1)
    second = CaptionEvent("source", "fast", "ja", "ko", "final", 0, segment_id="ja-ko")
    engine.start()
    try:
        engine.submit(first)
        engine.get_event(timeout=2)
        engine.submit(second)
        engine.get_event(timeout=2)
    finally:
        engine.stop()

    assert contexts == [(), ()]
