from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from lingua_relay.offline.project import Cue, OfflineProjectStore  # noqa: E402
from lingua_relay.ui.offline_workbench import OfflineWorkbench  # noqa: E402


def test_workbench_lists_projects_and_edits_cues(tmp_path) -> None:
    app = QApplication.instance() or QApplication([])
    store = OfflineProjectStore(tmp_path / "projects")
    project = store.create_project(
        title="Imported meeting",
        kind="video",
        source_language="ko",
        target_language="ja",
    )
    store.replace_cues(
        project.id,
        [Cue(None, project.id, 0, 0, 1000, "안녕하세요", "こんにちは")],
    )
    window = OfflineWorkbench(store)
    window.refresh(select_id=project.id)
    app.processEvents()

    assert window.projects.count() == 1
    assert window.cues.rowCount() == 1
    assert window.cues.item(0, 3).text() == "こんにちは"
    assert window.processing_options().asr_model == "large-v3-turbo"


def _window_with_projects(tmp_path):
    app = QApplication.instance() or QApplication([])
    store = OfflineProjectStore(tmp_path / "projects")
    first = store.create_project(
        title="First", kind="audio", source_language="en", target_language="zh"
    )
    second = store.create_project(
        title="Second", kind="audio", source_language="ja", target_language="ko"
    )
    window = OfflineWorkbench(store)
    window.refresh(select_id=first.id)
    app.processEvents()
    return window, first, second


def test_rejected_processing_request_does_not_leave_button_disabled(tmp_path):
    window, first, _second = _window_with_projects(tmp_path)
    requested = []
    window.process_requested.connect(lambda *args: requested.append(args))
    window._request_process()
    assert requested[0][0] == first.id
    assert window.process_button.isEnabled()
    assert not window.cancel_button.isEnabled()


def test_workbench_cancel_targets_active_task_and_waits_for_real_completion(tmp_path):
    window, first, second = _window_with_projects(tmp_path)
    cancelled = []
    window.cancel_requested.connect(cancelled.append)
    window.processing_started(first.id)
    assert not window.process_button.isEnabled()
    assert not window.model_combo.isEnabled()
    assert window.cancel_button.isEnabled()
    window.refresh(select_id=second.id)
    window.cancel_button.click()
    assert cancelled == [first.id]
    assert not window.cancel_button.isEnabled()
    assert not window.process_button.isEnabled()
    window.refresh(select_id=first.id)
    window.update_progress(first.id, 0.9, "should not overwrite cancellation")
    assert "正在取消" in window.progress_label.text()
    window.processing_finished(first.id, cancelled=True)
    assert window.process_button.isEnabled()
    assert window.model_combo.isEnabled()
    assert not window.cancel_button.isEnabled()
    assert "已取消" in window.progress_label.text()


def test_workbench_ignores_stale_completion_and_progress(tmp_path):
    window, first, second = _window_with_projects(tmp_path)
    window.processing_started(second.id)
    window.processing_finished(first.id)
    assert not window.process_button.isEnabled()
    assert window.cancel_button.isEnabled()
    window.refresh(select_id=second.id)
    window.update_progress(first.id, 1.0, "stale success")
    assert "stale success" not in window.progress_label.text()


def test_workbench_cannot_change_active_project_route_or_cues(tmp_path):
    window, first, _second = _window_with_projects(tmp_path)
    window.processing_started(first.id)
    window.source_language.setCurrentIndex(window.source_language.findData("ja"))
    assert window.store.get_project(first.id).source_language == "en"
    assert not window.cues.isEnabled()
    assert not window.source_language.isEnabled()
    assert not window.export_button.isEnabled()
