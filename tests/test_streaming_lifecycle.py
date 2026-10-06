"""K-001/K-004: deterministic queue pressure, cooperative stop and late-result accounting."""

from __future__ import annotations

import queue
import threading
import time

import numpy as np
import pytest

from lingua_relay.asr.streaming import StreamingAsrEngine
from lingua_relay.asr.types import AsrEvent, AsrResult, InferenceRequest
from lingua_relay.audio.types import AudioChunk, AudioLevel
from lingua_relay.config import AsrSettings, TranslationSettings
from lingua_relay.mt.streaming import StreamingTranslationEngine
from lingua_relay.mt.types import TranslationResult
from lingua_relay.translation import TranslationRouteRegistry


class ControlledModel:
    def __init__(self) -> None:
        self.started = threading.Event()
        self.release = threading.Event()
        self.calls = 0

    def _wait(self) -> None:
        self.calls += 1
        if self.calls == 1:
            self.started.set()
            if not self.release.wait(3):
                raise TimeoutError("test did not release model")

    def transcribe(self, samples, *, language, vad_filter=None):
        self._wait()
        return AsrResult("test", language, 1.0, 0.1)

    def translate(self, text, *, source, target):
        self._wait()
        return TranslationResult("测试", source, target, 0.1)


def event(segment: str) -> AsrEvent:
    return AsrEvent(
        text="test",
        stable_text="test",
        unstable_text="",
        newly_stable_text="test",
        language="en",
        state="final",
        segment_id=segment,
        revision=1,
        started_at_ms=1,
        ended_at_ms=2,
        emitted_at_ns=time.monotonic_ns(),
    )


def make_engine(kind: str, model: ControlledModel, *, output_timeout: float = 0.05):
    if kind == "asr":
        return StreamingAsrEngine(
            model,
            AsrSettings(inference_queue_capacity=2, event_queue_capacity=2),
            output_timeout=output_timeout,
        )
    registry = TranslationRouteRegistry()
    registry.register("en", "zh", "controlled", model)
    return StreamingTranslationEngine(
        registry,
        TranslationSettings(queue_capacity=2, event_queue_capacity=2),
        output_timeout=output_timeout,
    )


def submit(engine, segment: str, *, timeout: float = 0.0):
    if isinstance(engine, StreamingAsrEngine):
        engine._submit(
            InferenceRequest(
                samples=np.zeros(16, dtype=np.float32),
                language="en",
                state="final",
                segment_id=segment,
                revision=1,
                started_at_ns=1_000_000,
                ended_at_ns=2_000_000,
                submitted_at_ns=time.monotonic_ns(),
            ),
            timeout=timeout,
        )
        return True
    return engine.submit(event(segment), target="zh", timeout=timeout)


@pytest.mark.parametrize("kind", ["asr", "mt"])
def test_full_final_admission_is_bounded_and_rejection_is_counted(kind):
    model = ControlledModel()
    engine = make_engine(kind, model)
    engine.start()
    try:
        assert submit(engine, "in-flight")
        assert model.started.wait(1)
        assert submit(engine, "queued-1")
        assert submit(engine, "queued-2")
        started = time.monotonic()
        if kind == "asr":
            with pytest.raises(TimeoutError, match="final request"):
                submit(engine, "rejected")
        else:
            assert not submit(engine, "rejected")
        assert time.monotonic() - started < 0.5
        assert engine.snapshot().final_submit_rejections == 1
        assert engine.snapshot().final_requests_added == 3
    finally:
        engine.abort()
        model.release.set()
        engine.finish_stop(1)
    snapshot = engine.snapshot()
    assert snapshot.final_requests_aborted == 3
    assert snapshot.stale_results_dropped == 1
    assert not snapshot.worker_alive


@pytest.mark.parametrize("kind", ["asr", "mt"])
def test_full_final_output_enters_visible_overload_and_keeps_published_finals(kind):
    model = ControlledModel()
    engine = make_engine(kind, model)
    # Both queues have capacity two. No consumer is allowed to rescue the output.
    assert engine._events.put(event("published-1"), timeout=0)
    assert engine._events.put(event("published-2"), timeout=0)
    engine.start()
    try:
        assert submit(engine, "blocked-output")
        assert model.started.wait(1)
        assert submit(engine, "queued-1")
        assert submit(engine, "queued-2")
        engine.request_stop()
        model.release.set()
        engine.finish_stop(1)
        snapshot = engine.snapshot()
        assert snapshot.overloaded
        assert snapshot.final_outputs_rejected == 1
        assert snapshot.final_requests_aborted == 2
        assert snapshot.final_events_aborted == 0
        assert model.calls == 1
        assert engine.get_event(timeout=0).segment_id == "published-1"
        assert engine.get_event(timeout=0).segment_id == "published-2"
        with pytest.raises(queue.Empty):
            engine.get_event(timeout=0)
    finally:
        engine.abort()
        model.release.set()
        engine.finish_stop(1)


@pytest.mark.parametrize("kind", ["asr", "mt"])
def test_native_stop_timeout_retains_worker_and_suppresses_late_result(kind):
    model = ControlledModel()
    engine = make_engine(kind, model)
    engine.start()
    try:
        assert submit(engine, "native")
        assert model.started.wait(1)
        started = time.monotonic()
        with pytest.raises(TimeoutError, match="did not stop"):
            engine.stop(timeout=0.02)
        assert time.monotonic() - started < 0.5
        assert engine.worker_alive
        assert engine._thread is not None
        with pytest.raises(RuntimeError, match="cannot restart"):
            engine.start()
    finally:
        model.release.set()
        engine.finish_stop(1)
    assert engine.snapshot().stale_results_dropped == 1
    assert engine.snapshot().final_requests_aborted == 1
    assert not engine.worker_alive
    with pytest.raises(queue.Empty):
        engine.get_event(timeout=0)


@pytest.mark.parametrize("kind", ["asr", "mt"])
def test_two_phase_stop_drains_every_accepted_final_once(kind):
    model = ControlledModel()
    engine = make_engine(kind, model, output_timeout=1)
    engine.start()
    try:
        assert submit(engine, "a")
        assert model.started.wait(1)
        assert submit(engine, "b")
        assert submit(engine, "c")
        engine.request_stop()
        model.release.set()
        observed = [engine.get_event(timeout=1).segment_id for _ in range(3)]
        engine.finish_stop(1)
        assert observed == ["a", "b", "c"]
        snapshot = engine.snapshot()
        assert snapshot.events_emitted == 3
        assert snapshot.final_requests_aborted == snapshot.final_outputs_rejected == 0
        assert not snapshot.overloaded
    finally:
        engine.abort()
        model.release.set()
        engine.finish_stop(1)


@pytest.mark.parametrize("kind", ["asr", "mt"])
def test_abort_counts_already_published_unconsumed_finals(kind):
    model = ControlledModel()
    engine = make_engine(kind, model)
    assert engine._events.put(event("a"), timeout=0)
    assert engine._events.put(event("b"), timeout=0)
    engine.abort()
    engine.abort()
    assert engine.snapshot().final_events_aborted == 2
    with pytest.raises(queue.Empty):
        engine.get_event(timeout=0)


def test_asr_stop_flush_rejection_still_closes_admission_and_allows_drain():
    model = ControlledModel()
    engine = make_engine("asr", model, output_timeout=1)
    engine.start()
    try:
        # The active partial is in flight; its final does not fit in the queue.
        engine.submit_chunk(
            AudioChunk(
                samples=np.full(5120, 0.1, np.float32),
                sequence=0,
                captured_at_ns=time.monotonic_ns(),
                sample_rate=16000,
                device_id="fake",
                device_name="fake",
                level=AudioLevel(0.1, 0.1, -20, False),
            ),
            language="en",
        )
        assert model.started.wait(1)
        assert submit(engine, "queued-1")
        assert submit(engine, "queued-2")
        started = time.monotonic()
        with pytest.raises(TimeoutError, match="final request"):
            engine.request_stop()
        assert time.monotonic() - started < 0.5
        assert not engine.snapshot().running
        assert engine.snapshot().final_submit_rejections == 1
        model.release.set()
        engine.finish_stop(1)
        # The partial may be replaced; both accepted finals must survive the flush failure.
        results = [engine.get_event(timeout=0) for _ in range(2)]
        assert [item.segment_id for item in results] == ["queued-1", "queued-2"]
        assert engine.snapshot().final_requests_aborted == 0
    finally:
        engine.abort()
        model.release.set()
        engine.finish_stop(1)


class TraceRecorder:
    def __init__(self):
        self.events = []

    def record(self, segment_id, revision, stage, at_ns=None):
        self.events.append((segment_id, revision, stage, at_ns))
        return True


@pytest.mark.parametrize("kind", ["asr", "mt"])
def test_optional_trace_records_inference_stages_and_suppressed_late_result(kind):
    model = ControlledModel()
    engine = make_engine(kind, model)
    trace = TraceRecorder()
    engine._trace = trace
    engine.start()
    try:
        assert submit(engine, "tracked")
        assert model.started.wait(1)
        engine.abort()
        model.release.set()
        engine.finish_stop(1)
        stages = {item[2] for item in trace.events}
        assert {f"{kind}_submitted", f"{kind}_started", f"{kind}_completed", "suppressed"} <= stages
        assert {item[:2] for item in trace.events} == {("tracked", 1)}
        if kind == "asr":
            anchors = {item[2]: item[3] for item in trace.events}
            assert anchors["audio_start"] == 1_000_000
            assert anchors["audio_end"] == 2_000_000
    finally:
        engine.abort()
        model.release.set()
        engine.finish_stop(1)
