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
