from __future__ import annotations

import os
import threading
import time
from types import SimpleNamespace

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QThread  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from lingua_relay.config import Settings  # noqa: E402
from lingua_relay.offline.processor import ProcessingOptions  # noqa: E402
from lingua_relay.offline.project import OfflineProjectStore  # noqa: E402
from lingua_relay.ui import offline_tasks  # noqa: E402
from lingua_relay.ui.offline_tasks import (  # noqa: E402
    OfflineTaskResult,
    OfflineTasksMixin,
    OfflineWorker,
)


@pytest.fixture
def app():
    return QApplication.instance() or QApplication([])


class _Service:
    def __init__(self, state="running", *, paused=False):
        self.state = state
        self.paused = paused or state == "paused"
        self.calls = []
        self.recording_state = "stopped"
        self.recording_project_id = None

    def snapshot(self):
        return SimpleNamespace(
            state=self.state,
            recording_state=self.recording_state,
            recording_project_id=self.recording_project_id,
        )

    def stop(self):
        self.calls.append("stop")

    def release_resources(self):
        self.calls.append("release")

    def start(self, *, paused=False):
        self.calls.append(("start", paused))

    def start_recording(self, session):
        self.calls.append(("record", session.project_id))

    def stop_recording(self):
        self.calls.append("stop_recording")


@pytest.mark.parametrize("failure", [None, InterruptedError("cancelled"), ValueError("bad")])
def test_worker_settles_after_restoring_original_paused_state(app, failure):
    service = _Service("loading", paused=True)

    def process(*_args, **_kwargs):
        service.calls.append("process")
        if failure:
            raise failure

    worker = OfflineWorker(
        SimpleNamespace(process=process), service, "project", ProcessingOptions()
    )
    worker.done.connect(lambda: service.calls.append("done"))
    worker.run()
    assert service.calls == ["stop", "release", "process", ("start", True), "done"]
    expected = (
        "completed"
        if failure is None
        else "cancelled"
        if isinstance(failure, InterruptedError)
        else "failed"
    )
    assert worker.result.status == expected
    assert worker.cancel() is False


def test_worker_does_not_undo_committed_success_for_late_cancellation(app):
    service = _Service()

    def process(*_args, cancel, **_kwargs):
        # Simulate cancellation that arrives only after the backend commit.
        cancel.set()

    worker = OfflineWorker(
        SimpleNamespace(process=process), service, "project", ProcessingOptions()
    )
    worker.run()
    assert worker.result.status == "completed"


def test_worker_shutdown_cancel_never_reenables_realtime(app):
    service = _Service()
    holder = []

    def process(*_args, **_kwargs):
        worker = holder[0]
        assert worker.cancel(restart_service=False)
        assert worker.cancel(restart_service=True)
        raise InterruptedError("cancelled")

    worker = OfflineWorker(
        SimpleNamespace(process=process), service, "project", ProcessingOptions()
    )
    holder.append(worker)
    worker.run()
    assert service.calls == ["stop", "release"]
    assert worker.result.status == "cancelled"


def test_worker_does_not_start_originally_stopped_service(app):
    service = _Service("stopped")
    worker = OfflineWorker(
        SimpleNamespace(process=lambda *_args, **_kwargs: None),
        service,
        "project",
        ProcessingOptions(),
    )
    worker.run()
    assert service.calls == ["stop", "release"]


def test_worker_cancel_before_start_leaves_service_alone(app):
    service = _Service()
    worker = OfflineWorker(
        SimpleNamespace(process=lambda *_args, **_kwargs: pytest.fail("must not process")),
        service,
        "project",
        ProcessingOptions(),
    )
    worker.cancel()
    worker.run()
    assert not service.calls
    assert worker.result.status == "cancelled"


def test_worker_restore_failure_cannot_emit_success(app):
    service = _Service()

    def fail(**_kwargs):
        raise RuntimeError("cannot restore")

    service.start = fail
    worker = OfflineWorker(
        SimpleNamespace(process=lambda *_args, **_kwargs: None),
        service,
        "project",
        ProcessingOptions(),
    )
    worker.run()
    assert worker.result.status == "failed"
    assert "恢复实时字幕失败" in worker.result.detail


@pytest.mark.parametrize("failure_step", ["snapshot", "stop"])
def test_worker_preparation_failure_settles_without_processing_or_restarting(app, failure_step):
    service = _Service()
    settled = []

    def fail():
        raise TimeoutError("service not stopped")

    setattr(service, failure_step, fail)
    worker = OfflineWorker(
        SimpleNamespace(process=lambda *_args, **_kwargs: pytest.fail("must not process")),
        service,
        "project",
        ProcessingOptions(),
    )
    worker.done.connect(lambda: settled.append(True))
    worker.run()
    assert settled == [True]
    assert worker.result.status == "failed"
    assert not service.calls


class _Controller(OfflineTasksMixin):
    def __init__(self, app, tmp_path):
        self.app = app
        self.settings = Settings()
        self.model_root = tmp_path / "models"
        self.project_store = OfflineProjectStore(tmp_path / "projects")
        self.service = _Service()
        self.messages = []
        self.tray = SimpleNamespace(showMessage=lambda *args: self.messages.append(args))
        self._init_offline_tasks()


@pytest.mark.parametrize("state", ["loading", "error", "stopped"])
def test_recording_does_not_wait_for_model_readiness(app, tmp_path, state):
    controller = _Controller(app, tmp_path)
    controller.service.state = state
    controller.toggle_recording()
    assert len(controller.project_store.list_projects()) == 1
    assert controller.service.calls[0][0] == "record"


def test_stop_recording_uses_workbench_options(app, tmp_path):
    controller = _Controller(app, tmp_path)
    controller.service.recording_state = "recording"
    controller.service.recording_project_id = "recorded-project"
    desired = ProcessingOptions(asr_model="large-v3", quality="accurate", use_llm=True)
    controller._offline_workbench = SimpleNamespace(processing_options=lambda: desired)
    controller.show_workbench = lambda **_kwargs: None
    started = []
    controller._start_offline_processing = lambda *args: started.append(args)
    controller.toggle_recording()
    assert controller.service.calls == ["stop_recording"]
    assert started == [("recorded-project", desired)]


def test_recording_is_blocked_during_offline_task(app, tmp_path):
    controller = _Controller(app, tmp_path)
    controller._offline_worker = object()
    warnings = []
    controller._warn_offline_busy = lambda: warnings.append(True)
    controller.toggle_recording()
    assert warnings == [True]
    assert not controller.project_store.list_projects()
    assert not controller.service.calls


def test_stale_task_callbacks_do_not_complete_new_task(app, tmp_path):
    controller = _Controller(app, tmp_path)
    old = SimpleNamespace(project_id="old", result=OfflineTaskResult("old", "completed"))
    current = SimpleNamespace(project_id="new")
    controller._offline_worker = current
    current_thread = object()
    controller._offline_thread = current_thread
    controller._offline_progress(old, "old", 1.0, "stale")
    controller._offline_thread_finished(old, object())
    assert controller._offline_worker is current
    assert controller._offline_thread is current_thread
    assert not controller.messages


def test_cancelled_qt_worker_finishes_before_unlock_and_never_notifies_success(
    app, tmp_path, monkeypatch
):
    controller = _Controller(app, tmp_path)
    project = controller.project_store.create_project(
        title="Test", kind="audio", source_language="en", target_language="zh"
    )
    entered = threading.Event()
    released = threading.Event()
    callbacks = []

    class Processor:
        def process(self, *_args, cancel, on_progress):
            entered.set()
            on_progress(0.3, "working")
            assert released.wait(3)
            if cancel.is_set():
                raise InterruptedError("cancelled")

    controller._offline_workbench = SimpleNamespace(
        processing_started=lambda *_args: None,
        processing_cancelling=lambda *_args: callbacks.append(
            ("cancelling", QThread.currentThread())
        ),
        update_progress=lambda *_args: callbacks.append(("progress", QThread.currentThread())),
        processing_finished=lambda *_args, **_kwargs: callbacks.append(
            ("finished", QThread.currentThread())
        ),
    )
    monkeypatch.setattr(offline_tasks, "ensure_advanced_models", lambda *_args: True)
    monkeypatch.setattr(offline_tasks, "OfflineProcessor", lambda *_args: Processor())
    controller._start_offline_processing(project.id, ProcessingOptions())
    try:
        assert entered.wait(2)
        controller._cancel_offline_processing(project.id)
        assert controller._offline_is_busy()
        assert not any(name == "finished" for name, _thread in callbacks)
        released.set()
        deadline = time.monotonic() + 3
        while controller._offline_is_busy() and time.monotonic() < deadline:
            app.processEvents()
            time.sleep(0.001)
        assert not controller._offline_is_busy()
        assert any(name == "finished" for name, _thread in callbacks)
        assert all(callback_thread == app.thread() for _name, callback_thread in callbacks)
        assert not controller.messages
    finally:
        released.set()
        if controller._offline_thread is not None:
            controller._shutdown_offline_tasks()
        # Process queued deleteLater calls while the QApplication is alive.
        app.processEvents()


def test_shutdown_worker_quits_without_gui_event_dispatch(app, tmp_path, monkeypatch):
    controller = _Controller(app, tmp_path)
    entered = threading.Event()

    class Processor:
        def process(self, *_args, cancel, **_kwargs):
            entered.set()
            assert cancel.wait(3)
            raise InterruptedError("cancelled for shutdown")

    monkeypatch.setattr(offline_tasks, "ensure_advanced_models", lambda *_args: True)
    monkeypatch.setattr(offline_tasks, "OfflineProcessor", lambda *_args: Processor())
    controller._start_offline_processing("test-project", ProcessingOptions())
    assert entered.wait(2)
    thread = controller._offline_thread
    controller._shutdown_offline_tasks()
    assert not thread.isRunning()
    assert controller.service.calls == ["stop", "release"]
    app.processEvents()
    assert not controller.messages
    assert controller._offline_worker is None
