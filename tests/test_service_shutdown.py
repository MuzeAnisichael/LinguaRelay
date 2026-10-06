"""K-001: cross-worker cleanup, graceful final drain and correction-safe recovery."""

from __future__ import annotations

import threading
import time
from dataclasses import replace
from types import SimpleNamespace

import numpy as np
import pytest

from lingua_relay.asr.streaming import StreamingAsrEngine
from lingua_relay.asr.types import AsrResult, InferenceRequest
from lingua_relay.config import Settings
from lingua_relay.correction.engine import AsynchronousRevisionEngine
from lingua_relay.mt.streaming import StreamingTranslationEngine
from lingua_relay.mt.types import TranslationResult
from lingua_relay.service import RealtimeCaptionService
from lingua_relay.translation import TranslationRouteRegistry


class AudioStub:
    def __init__(self, pause_error: Exception | None = None):
        self.pause_error = pause_error
        self.enabled = False
        self.stop_calls = 0

    def set_realtime_enabled(self, enabled):
        if not enabled and self.pause_error is not None:
            raise self.pause_error
        self.enabled = enabled

    def stop(self, timeout=5):
        self.stop_calls += 1
        self.enabled = False

    def recording_snapshot(self):
        return "stopped", None

    def snapshot(self):
        return SimpleNamespace(realtime_inflight=False)


class LocalModel:
    def transcribe(self, samples, *, language, vad_filter=None):
        return AsrResult("test", language, 1.0, 0.1)

    def translate(self, text, *, source, target):
        return TranslationResult("测试", source, target, 0.1)


class MemoryHistory:
    def __init__(self):
        self.events = []

    def append(self, event):
        self.events.append(event)


class UnusedProvider:
    name = "test-local"
    model = "fake"
    scope = "local"

    def revise(self, request):
        raise AssertionError("idle correction provider must not be called")


def make_service(*, audio=None, history=None):
    settings = Settings()
    settings = replace(settings, app=replace(settings.app, history_enabled=False))
    service = RealtimeCaptionService(settings, on_caption=lambda _event: None)
    service._audio = audio if audio is not None else AudioStub()
    model = LocalModel()
    registry = TranslationRouteRegistry()
    registry.register("en", "zh", "fake", model)
    service._asr = StreamingAsrEngine(model, settings.asr, trace=service.trace)
    service._mt = StreamingTranslationEngine(
        registry, settings.translation, trace=service.trace, history=history
    )
    service._asr.start()
    service._mt.start()
    return service


def force_cleanup(service):
    for worker in (service._asr, service._mt):
        if worker is not None:
            worker.abort()
            worker.finish_stop(timeout=1)
    if service._correction is not None:
        service._correction.stop(timeout=1)
    if service._thread is not None:
        service._thread.join(1)
        assert not service._thread.is_alive()


@pytest.mark.parametrize("error_type", [TimeoutError, OSError])
def test_audio_pause_failure_does_not_skip_idle_workers_and_stop_is_retryable(error_type):
    audio = AudioStub(error_type("synthetic capture pause failure"))
    service = make_service(audio=audio)
    correction = AsynchronousRevisionEngine(UnusedProvider(), service.settings.correction)
    service._correction = correction
    correction.start()
    exceptions = []

    def shutdown_on_request():
        if not service._stop.wait(2):
            exceptions.append(AssertionError("test did not request stop"))
            return
        try:
            service._shutdown_workers()
        except Exception as error:
            exceptions.append(error)

    service._thread = threading.Thread(target=shutdown_on_request)
    service._thread.start()
    try:
        with pytest.raises(RuntimeError, match=f"audio: {error_type.__name__}"):
            service.stop(timeout=1)
        assert not exceptions
        assert not service._asr.worker_alive
        assert not service._mt.worker_alive
        assert not service._workers_alive()
        assert service.snapshot().state == "error"
        # An earlier audio notification failure must not make all future stops impossible.
        audio.pause_error = None
        service.stop(timeout=1)
        assert audio.stop_calls == 2
        assert not service._workers_alive()
        assert service.snapshot().state == "stopped"
        assert f"audio: {error_type.__name__}" in (service.snapshot().last_error or "")
        assert service.trace.snapshot()["counters"]["shutdown_error_recoveries"] == 1
    finally:
        force_cleanup(service)


def test_overload_resume_reuses_models_without_waiting_for_idle_correction_thread():
    service = make_service()
    correction = AsynchronousRevisionEngine(UnusedProvider(), service.settings.correction)
    service._correction = correction
    service._correction_mode = "asynchronous"
    correction.start()
    old_asr, old_mt = service._asr, service._mt
    correction_thread = correction._thread
    try:
        service._handle_overload("synthetic overload")
        old_asr.finish_stop(timeout=1)
        old_mt.finish_stop(timeout=1)
        assert correction_thread is not None and correction_thread.is_alive()
        service.resume()
        service._try_resume_overload()
        assert not service.snapshot().overloaded
        assert service.snapshot().state == "running"
        assert service._audio.enabled and not service.paused
        assert service._asr is not old_asr and service._mt is not old_mt
        assert service._asr.recognizer is old_asr.recognizer
        assert service._mt.registry is old_mt.registry
        assert service._correction is correction
        assert correction._thread is correction_thread and correction_thread.is_alive()
        assert correction._enabled.is_set()
        assert service._displayed_segment_id is None
    finally:
        force_cleanup(service)


def test_normal_service_shutdown_drains_all_accepted_finals_into_history_once():
    history = MemoryHistory()
    service = make_service(history=history)
    asr, mt = service._asr, service._mt
    try:
        for index in range(3):
            asr._submit(
                InferenceRequest(
                    samples=np.zeros(16, dtype=np.float32),
                    language="en",
                    state="final",
                    segment_id=f"final-{index}",
                    revision=1,
                    started_at_ns=1_000_000,
                    ended_at_ns=2_000_000,
                    submitted_at_ns=time.monotonic_ns(),
                ),
                timeout=0,
            )
        service._stop.set()
        service._stop_deadline = time.monotonic() + 2
        service._shutdown_workers()
        assert not service._workers_alive()
        assert [event.segment_id for event in history.events] == [
            "final-0",
            "final-1",
            "final-2",
        ]
        assert all(event.translated_text == "测试" for event in history.events)
        assert asr.snapshot().final_requests_added == mt.snapshot().final_requests_added == 3
        for snapshot in (asr.snapshot(), mt.snapshot()):
            assert snapshot.final_requests_aborted == 0
            assert snapshot.final_outputs_rejected == 0
            assert snapshot.final_events_aborted == 0
        assert service.snapshot().pending_finals == service.snapshot().finals_aborted == 0
    finally:
        force_cleanup(service)
