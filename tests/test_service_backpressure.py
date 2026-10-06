"""R-LIVE-01 / R-REC-01: bounded admission, final accounting and total stop budget."""

from __future__ import annotations

import queue
import threading
import time
from dataclasses import replace
from types import SimpleNamespace

import pytest

from lingua_relay.asr.types import AsrEvent
from lingua_relay.config import Settings
from lingua_relay.events import CaptionEvent
from lingua_relay.mt import StreamingTranslationEngine
from lingua_relay.service import RealtimeCaptionService
from lingua_relay.translation import TranslationRouteRegistry


def transcript(index: int) -> AsrEvent:
    return AsrEvent(
        "hello",
        "hello",
        "",
        "hello",
        "en",
        "final",
        f"segment-{index}",
        1,
        0,
        320,
        time.monotonic_ns(),
    )


class AsrEvents:
    def __init__(self, count=1):
        self.events = queue.Queue()
        for index in range(count):
            self.events.put(transcript(index))
        self.worker_alive = False

    def get_event(self, timeout=0):
        return self.events.get(timeout=timeout)

    def snapshot(self):
        return SimpleNamespace(overloaded=False, event_queue_depth=self.events.qsize())

    def abort(self):
        while not self.events.empty():
            self.events.get_nowait()


class AudioStub:
    def __init__(self):
        self.enabled = False

    def set_realtime_enabled(self, enabled):
        self.enabled = enabled

    def stop(self, timeout=5):
        pass

    def recording_snapshot(self):
        return "stopped", None

    def prepare(self):
        pass

    def snapshot(self):
        return SimpleNamespace(realtime_inflight=False)


def test_history_failure_warns_once_without_pausing_translation():
    messages = []
    service = RealtimeCaptionService(
        Settings(), on_caption=lambda _event: None, on_status=lambda *args: messages.append(args)
    )

    class Mt:
        errors = 2

        def get_event(self, timeout=0):
            raise queue.Empty

        def snapshot(self):
            return SimpleNamespace(overloaded=False, history_errors=self.errors)

    service._mt = Mt()
    service.pump_once()
    service.pump_once()
    assert len(messages) == 1
    assert "保存失败" in messages[0][1]
    assert not service.paused and not service._overloaded
    service._mt.errors = 3
    service.pump_once()
    assert len(messages) == 2


def test_downstream_is_drained_before_full_final_mt_submission():
    service = RealtimeCaptionService(Settings(), on_caption=lambda _event: None)
    service._asr = AsrEvents()
    order = []

    class Mt:
        full = True

        def get_event(self, timeout=0):
            order.append("drain")
            self.full = False
            raise queue.Empty

        def submit(self, event, *, target, timeout):
            assert timeout == 0
            order.append("submit")
            return not self.full

        def snapshot(self):
            return SimpleNamespace(overloaded=False)

    service._mt = Mt()
    service.pump_once()
    assert order[:2] == ["drain", "submit"]
    assert not service._pending_finals


def test_short_congestion_retries_final_in_order_without_unbounded_queue():
    service = RealtimeCaptionService(Settings(), on_caption=lambda _event: None)
    service._asr = AsrEvents(10)

    class Mt:
        ready = False
        submitted = []

        def get_event(self, timeout=0):
            raise queue.Empty

        def submit(self, event, *, target, timeout):
            if self.ready:
                self.submitted.append(event.segment_id)
            return self.ready

        def snapshot(self):
            return SimpleNamespace(overloaded=False)

    mt = Mt()
    service._mt = mt
    service.pump_once()
    assert len(service._pending_finals) == service._pending_capacity == 4
    assert service._asr.events.qsize() == 6
    mt.ready = True
    for _ in range(4):
        service.pump_once()
    assert mt.submitted == [f"segment-{index}" for index in range(10)]
    assert service._finals_aborted == 0


def test_sustained_congestion_pauses_and_accounts_pending_finals():
    statuses = []
    service = RealtimeCaptionService(
        Settings(),
        on_caption=lambda _event: None,
        on_status=lambda state, _message: statuses.append(state),
    )
    service._audio = AudioStub()
    service._asr = AsrEvents(2)

    class Mt:
        worker_alive = False
        aborted = False

        def get_event(self, timeout=0):
            raise queue.Empty

        def submit(self, event, *, target, timeout):
            return False

        def abort(self):
            self.aborted = True

        def snapshot(self):
            return SimpleNamespace(overloaded=False)

    mt = Mt()
    service._mt = mt
    service._pending_timeout = 0
    service.pump_once()
    service.pump_once()
    assert statuses[-1] == "overloaded"
    assert service.paused and not service._audio.enabled
    assert mt.aborted and service._finals_aborted == 2
    assert not service._pending_finals
    assert not service.accepts_delivery(transcript(1))


def test_total_stop_deadline_retains_native_worker_and_suppresses_late_ui():
    entered, release = threading.Event(), threading.Event()
    published = []

    class Translator:
        def translate(self, text, *, source, target):
            entered.set()
            assert release.wait(3)
            return "你好"

    registry = TranslationRouteRegistry()
    registry.register("en", "zh", "fake", Translator())
    settings = replace(Settings(), app=replace(Settings().app, history_enabled=False))
    service = RealtimeCaptionService(settings, on_caption=published.append)
    service._audio = AudioStub()
    engine = StreamingTranslationEngine(registry, settings.translation, trace=service.trace)
    service._mt = engine
    engine.start()
    engine.submit(transcript(0), target="zh")
    assert entered.wait(2)

    def run_shutdown():
        assert service._stop.wait(2)
        service._shutdown_workers()

    service._thread = threading.Thread(target=run_shutdown)
    service._thread.start()
    started = time.monotonic()
    try:
        with pytest.raises(TimeoutError):
            service.stop(timeout=0.05)
        # Scheduling tolerance, not a real-time performance assertion.
        assert time.monotonic() - started < 0.5
        assert engine.worker_alive
        assert service.snapshot().state == "stop_timeout"
        with pytest.raises(RuntimeError):
            service.release_resources()
        with pytest.raises(RuntimeError):
            service.start()
    finally:
        service._thread.join(2)
        release.set()
        engine.finish_stop(timeout=2)
    assert published == []
    assert engine.snapshot().stale_results_dropped == 1


def test_ui_ack_is_only_for_current_delivery_and_old_signal_is_rejected():
    service = RealtimeCaptionService(Settings(), on_caption=lambda _event: None)
    event = CaptionEvent("hello", "你好", "en", "zh", "final", 0, segment_id="current", revision=1)
    service._displayed_segment_id = "current"
    service._displayed_revision = 1
    assert service.accepts_delivery(event)
    service._stop.set()
    assert not service.accepts_delivery(event)


@pytest.mark.parametrize("stopping", [False, True])
def test_closed_mt_admission_race_does_not_escape_service_pump(stopping):
    service = RealtimeCaptionService(Settings(), on_caption=lambda _event: None)
    service._audio = AudioStub()
    service._asr = AsrEvents(2)

    class Mt:
        worker_alive = False

        def get_event(self, timeout=0):
            raise queue.Empty

        def submit(self, event, *, target, timeout):
            raise RuntimeError("worker admission closed just after poll")

        def abort(self):
            pass

        def snapshot(self):
            return SimpleNamespace(overloaded=False)

    service._mt = Mt()
    service._pending_finals.append((transcript(9), "zh", time.monotonic() + 1))
    if stopping:
        service._stop.set()
    service.pump_once()
    assert not service._pending_finals
    assert service._finals_aborted == 1
    assert stopping or service.snapshot().overloaded


@pytest.mark.parametrize("stopping", [False, True])
def test_closed_mt_accounts_current_final_once_without_requeue(stopping):
    service = RealtimeCaptionService(Settings(), on_caption=lambda _event: None)
    service._audio = AudioStub()
    service._asr = AsrEvents(1)

    class Mt:
        worker_alive = False

        def submit(self, event, *, target, timeout):
            raise RuntimeError("closed")

        def abort(self):
            pass

    service._mt = Mt()
    if stopping:
        service._stop.set()
    service._pump_asr()
    assert service._finals_aborted == 1
    assert not service._pending_finals


def test_start_resets_overload_and_display_after_previous_session_has_finished(monkeypatch):
    service = RealtimeCaptionService(Settings(), on_caption=lambda _event: None)
    service._audio = AudioStub()
    service._stop.set()
    service._overloaded = True
    service._resume_requested.set()
    service._displayed_segment_id = "old"
    service._displayed_revision = 1
    entered, release = threading.Event(), threading.Event()

    def fake_run():
        entered.set()
        assert release.wait(2)

    monkeypatch.setattr(service, "_run", fake_run)
    try:
        service.start(paused=True)
        assert entered.wait(2)
        assert not service._overloaded and not service._resume_requested.is_set()
        assert service._displayed_segment_id is None
        assert not service.accepts_delivery(
            CaptionEvent("old", "旧结果", "en", "zh", "final", 0, segment_id="old", revision=1)
        )
    finally:
        release.set()
        service.stop(timeout=2)


def test_loading_native_call_blocks_restart_even_without_inference_workers(monkeypatch):
    service = RealtimeCaptionService(Settings(), on_caption=lambda _event: None)
    service._audio = AudioStub()
    entered, release = threading.Event(), threading.Event()

    def fake_run():
        entered.set()
        assert release.wait(2)

    monkeypatch.setattr(service, "_run", fake_run)
    try:
        service.start()
        assert entered.wait(2)
        with pytest.raises(TimeoutError):
            service.stop(timeout=0.01)
        with pytest.raises(RuntimeError):
            service.start()
        with pytest.raises(RuntimeError):
            service.release_resources()
    finally:
        release.set()
        service.stop(timeout=2)


def test_stop_budget_does_not_wait_on_blocked_transcript_callback():
    entered, release = threading.Event(), threading.Event()

    def callback(event, target):
        entered.set()
        assert release.wait(2)

    service = RealtimeCaptionService(
        Settings(), on_caption=lambda _event: None, on_transcript=callback
    )
    service._audio = AudioStub()
    service._asr = AsrEvents(1)

    class Mt:
        worker_alive = False

        def submit(self, event, *, target, timeout):
            return True

        def abort(self):
            pass

    service._mt = Mt()
    service._thread = threading.Thread(target=service._pump_asr)
    service._thread.start()
    try:
        assert entered.wait(2)
        started = time.monotonic()
        with pytest.raises(TimeoutError):
            service.stop(timeout=0.02)
        assert time.monotonic() - started < 0.5
    finally:
        release.set()
        service._thread.join(2)


def test_old_llm_output_cannot_claim_empty_display_after_overload():
    published = []
    service = RealtimeCaptionService(Settings(), on_caption=published.append)
    output = queue.Queue()
    output.put(
        CaptionEvent(
            "old",
            "旧修正",
            "en",
            "zh",
            "revised",
            0,
            segment_id="old",
            revision=2,
            parent_revision=1,
        )
    )

    class Correction:
        def get_event(self, timeout=0):
            return output.get(timeout=timeout)

    service._correction = Correction()
    service._correction_mode = "live"
    service._pump_revisions()
    assert not published and service._displayed_segment_id is None
