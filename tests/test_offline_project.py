from __future__ import annotations

import threading

import pytest

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


def test_complete_processing_commits_cues_and_status_together(tmp_path) -> None:
    store = OfflineProjectStore(tmp_path / "projects")
    project = store.create_project(
        title="Atomic result", kind="audio", source_language="en", target_language="zh"
    )
    audio = tmp_path / "audio.wav"
    completed = store.complete_processing(
        project.id,
        [Cue(None, project.id, 0, 0, 1000, "Hello", "你好")],
        audio_path=audio,
        duration_ms=1000,
        error="One optional correction failed",
    )
    assert completed.status == "completed"
    assert completed.progress == 1
    assert completed.audio_path == audio
    assert completed.duration_ms == 1000
    assert completed.error == "One optional correction failed"
    assert store.list_cues(project.id)[0].translated_text == "你好"


@pytest.mark.parametrize("cancel_during_insert", [False, True])
def test_cancelled_commit_preserves_previous_cues_and_project(
    tmp_path, monkeypatch, cancel_during_insert
) -> None:
    store = OfflineProjectStore(tmp_path / "projects")
    project = store.create_project(
        title="Previous result", kind="audio", source_language="en", target_language="zh"
    )
    store.replace_cues(project.id, [Cue(None, project.id, 0, 0, 1000, "Old", "原有字幕")])
    original_cues = store.list_cues(project.id)
    original_project = store.get_project(project.id)
    cancelled = threading.Event()
    connect = store._connect

    def traced_connect():
        connection = connect()
        connection.set_trace_callback(
            lambda sql: cancelled.set() if "INSERT INTO cues" in sql else None
        )
        return connection

    if cancel_during_insert:
        monkeypatch.setattr(store, "_connect", traced_connect)
    else:
        cancelled.set()
    with pytest.raises(InterruptedError):
        store.complete_processing(
            project.id,
            [Cue(None, project.id, 0, 0, 2000, "New", "不应发布")],
            audio_path=tmp_path / "new.wav",
            duration_ms=2000,
            cancel=cancelled,
        )
    assert store.list_cues(project.id) == original_cues
    assert store.get_project(project.id) == original_project
