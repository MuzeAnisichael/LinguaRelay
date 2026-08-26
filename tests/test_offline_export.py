from __future__ import annotations

import json

from lingua_relay.offline.export import export_project
from lingua_relay.offline.project import Cue, OfflineProjectStore


def _project_with_cues(tmp_path):
    store = OfflineProjectStore(tmp_path / "projects")
    project = store.create_project(
        title="字幕",
        kind="audio",
        source_language="en",
        target_language="zh",
    )
    store.replace_cues(
        project.id,
        [
            Cue(None, project.id, 0, 1234, 3456, "Hello", "你好"),
            Cue(None, project.id, 1, 4000, 5678, "World", "世界"),
        ],
    )
    return store, project


def test_exports_webvtt_with_precise_timestamps(tmp_path) -> None:
    store, project = _project_with_cues(tmp_path)
    output = export_project(store, project.id, tmp_path / "captions.vtt")
    text = output.read_text(encoding="utf-8-sig")
    assert text.startswith("WEBVTT\n")
    assert "00:00:01.234 --> 00:00:03.456" in text
    assert "你好" in text


def test_exports_jsonl_with_word_payload(tmp_path) -> None:
    store, project = _project_with_cues(tmp_path)
    output = export_project(store, project.id, tmp_path / "captions.jsonl")
    first = json.loads(output.read_text(encoding="utf-8").splitlines()[0])
    assert first["start_ms"] == 1234
    assert first["translated_text"] == "你好"
