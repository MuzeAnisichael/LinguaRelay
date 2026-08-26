from __future__ import annotations

import json
import wave

import numpy as np
import pytest

from lingua_relay.audio.types import AudioChunk, AudioLevel
from lingua_relay.offline.project import OfflineProjectStore
from lingua_relay.offline.recording import RecordingSession, recover_recording


def _chunk(sequence: int) -> AudioChunk:
    return AudioChunk(
        samples=np.full(1600, 0.25, dtype=np.float32),
        sequence=sequence,
        captured_at_ns=sequence,
        sample_rate=16_000,
        device_id="test",
        device_name="Test",
        level=AudioLevel(rms=0.25, peak=0.25, dbfs=-12, silent=False),
    )


def test_recording_pause_removes_gap_and_merges_fragments(tmp_path) -> None:
    store = OfflineProjectStore(tmp_path / "projects")
    project = store.create_project(
        title="Recording",
        kind="recording",
        source_language="ja",
        target_language="ko",
    )
    session = RecordingSession(store, project.id)
    session.start()
    session.write(_chunk(1))
    session.pause()
    session.write(_chunk(2))
    session.resume()
    session.write(_chunk(3))
    output = session.stop()

    with wave.open(str(output), "rb") as stream:
        assert stream.getnframes() == 3200
        assert stream.getframerate() == 16_000
    loaded = store.get_project(project.id)
    assert loaded.duration_ms == 200
    assert loaded.status == "ready"
    assert output == loaded.audio_path


def test_paused_recording_is_recovered_after_restart(tmp_path) -> None:
    store = OfflineProjectStore(tmp_path / "projects")
    project = store.create_project(
        title="Interrupted",
        kind="recording",
        source_language="zh",
        target_language="en",
    )
    session = RecordingSession(store, project.id)
    session.start()
    session.write(_chunk(1))
    session.pause()

    recovered = recover_recording(OfflineProjectStore(store.root), project.id)
    with wave.open(str(recovered), "rb") as stream:
        assert stream.getnframes() == 1600
    assert store.get_project(project.id).status == "ready"


def test_recovery_rejects_fragment_paths_outside_project(tmp_path) -> None:
    store = OfflineProjectStore(tmp_path / "projects")
    project = store.create_project(
        title="Untrusted manifest",
        kind="recording",
        source_language="en",
        target_language="zh",
    )
    directory = store.project_dir(project.id)
    manifest_path = directory / "recording.json"
    manifest_path.write_text(
        json.dumps({"fragments": ["../outside.wav"], "sample_rate": 16_000}),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="无效的片段路径"):
        recover_recording(store, project.id)
