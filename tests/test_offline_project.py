from __future__ import annotations

from lingua_relay.offline.project import Cue, OfflineProjectStore


def test_project_store_persists_project_and_editable_cues(tmp_path) -> None:
    store = OfflineProjectStore(tmp_path / "projects")
    project = store.create_project(
        title="Meeting",
        kind="audio",
        source_path=tmp_path / "meeting.mp3",
        source_language="en",
        target_language="zh",
    )
    store.update_project(project.id, status="processing", progress=0.5, duration_ms=2500)
    store.replace_cues(
        project.id,
        [Cue(None, project.id, 0, 100, 1200, "Hello", "你好", 0.95)],
    )

    reopened = OfflineProjectStore(tmp_path / "projects")
    loaded = reopened.get_project(project.id)
    cue = reopened.list_cues(project.id)[0]
    assert loaded.status == "processing"
    assert loaded.progress == 0.5
    assert cue.translated_text == "你好"

    reopened.update_cue(
        cue.id or 0,
        start_ms=200,
        end_ms=1300,
        source_text="Hello world",
        translated_text="你好，世界",
    )
    assert reopened.list_cues(project.id)[0].start_ms == 200


def test_project_id_cannot_escape_root(tmp_path) -> None:
    store = OfflineProjectStore(tmp_path / "projects")
    try:
        store.project_dir("../outside")
    except ValueError as error:
        assert "invalid project id" in str(error)
    else:
        raise AssertionError("unsafe id was accepted")
