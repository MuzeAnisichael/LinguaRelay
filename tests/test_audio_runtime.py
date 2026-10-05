from __future__ import annotations

import queue
import threading
import time
import wave
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from lingua_relay.audio.runtime import AudioCaptureRuntime, _recording_chunk_after
from lingua_relay.audio.types import AudioChunk, AudioLevel
from lingua_relay.config import AudioSettings, Settings
from lingua_relay.offline.project import OfflineProjectStore
from lingua_relay.offline.recording import RecordingSession
from lingua_relay.service import RealtimeCaptionService


class FakeCapture:
    def __init__(self) -> None:
        self.chunks: queue.Queue[AudioChunk] = queue.Queue()
        self.running = False
        self.starts = 0
        self.stops = 0

    def start(self) -> None:
        if not self.running:
            self.starts += 1
            self.running = True

    def stop(self) -> None:
        self.running = False
        self.stops += 1

    def get_chunk(self, timeout: float) -> AudioChunk:
        return self.chunks.get(timeout=timeout)

    def snapshot(self) -> SimpleNamespace:
        return SimpleNamespace(state="running" if self.running else "stopped", last_error=None)


class ObservedRecording(RecordingSession):
    def __init__(self, store: OfflineProjectStore, project_id: str) -> None:
        super().__init__(store, project_id)
        self.written = threading.Event()

    def write(self, chunk: AudioChunk) -> None:
        super().write(chunk)
        self.written.set()


def _recording(tmp_path: Path) -> ObservedRecording:
    store = OfflineProjectStore(tmp_path / "projects")
    project = store.create_project(
        title="Synthetic recording", kind="recording", source_language="en", target_language="zh"
    )
    return ObservedRecording(store, project.id)


def _chunk(sequence: int) -> AudioChunk:
    return AudioChunk(
        np.full(1600, 0.25, dtype=np.float32),
        sequence,
        time.monotonic_ns(),
        16_000,
        "synthetic",
        "Synthetic",
        AudioLevel(0.25, 0.25, -12, False),
    )


@pytest.fixture
def capture(monkeypatch) -> FakeCapture:
    result = FakeCapture()
    monkeypatch.setattr(
        "lingua_relay.audio.runtime.create_audio_capture", lambda *_args, **_kwargs: result
    )
    return result


def _runtime(on_chunk=lambda _chunk: None) -> AudioCaptureRuntime:
    return AudioCaptureRuntime(
        AudioSettings(),
        resource_dir=Path("."),
        on_chunk=on_chunk,
        on_message=lambda _message: None,
        on_recording=lambda *_args: None,
    )


def test_service_can_record_without_loading_any_models(tmp_path, capture) -> None:
    service = RealtimeCaptionService(Settings(), on_caption=lambda _event: None)
    recorder = _recording(tmp_path)
    try:
        service.start_recording(recorder)
        capture.chunks.put(_chunk(1))
        assert recorder.written.wait(2)
        assert service.snapshot().state == "stopped"
        assert service.snapshot().recording_state == "recording"
        output = service.stop_recording()
        with wave.open(str(output), "rb") as stream:
            assert stream.getnframes() == 1600
        assert not capture.running
    finally:
        service.stop()


def test_recording_survives_blocking_and_failed_model_load(tmp_path, capture, monkeypatch) -> None:
    loading = threading.Event()
    release_load = threading.Event()
    failed = threading.Event()

    class FailingRecognizer:
        def __init__(self, *_args, **_kwargs) -> None:
            pass

        def load(self) -> None:
            loading.set()
            assert release_load.wait(2)
            raise RuntimeError("synthetic missing model")

    monkeypatch.setattr("lingua_relay.service.FasterWhisperRecognizer", FailingRecognizer)
    service = RealtimeCaptionService(
        Settings(),
        on_caption=lambda _event: None,
        on_status=lambda state, _message: failed.set() if state == "error" else None,
    )
    recorder = _recording(tmp_path)
    try:
        service.start(paused=True)
        assert loading.wait(2)
        service.start_recording(recorder)
        capture.chunks.put(_chunk(1))
        assert recorder.written.wait(2)
        assert service.snapshot().state == "loading"
        recorder.written.clear()
        release_load.set()
        assert failed.wait(2)
        capture.chunks.put(_chunk(2))
        assert recorder.written.wait(2)
        assert service.snapshot().recording_state == "recording"
        output = service.stop_recording()
        with wave.open(str(output), "rb") as stream:
            assert stream.getnframes() == 3200
    finally:
        release_load.set()
        service.stop()


def test_pausing_captions_does_not_pause_recording(tmp_path, capture) -> None:
    submitted = threading.Event()
    runtime = _runtime(lambda _chunk: submitted.set())
    recorder = _recording(tmp_path)
    try:
        runtime.set_realtime_enabled(True)
        runtime.start_recording(recorder)
        capture.chunks.put(_chunk(1))
        assert submitted.wait(2)
        submitted.clear()
        recorder.written.clear()
        runtime.set_realtime_enabled(False)
        assert capture.running
        capture.chunks.put(_chunk(2))
        assert recorder.written.wait(2)
        assert not submitted.is_set()
        runtime.pause_recording()
        assert not capture.running
        runtime.resume_recording()
        assert capture.running
    finally:
        runtime.stop()


def test_source_switch_is_rejected_while_recording_is_paused(tmp_path, capture) -> None:
    runtime = _runtime()
    recorder = _recording(tmp_path)
    try:
        runtime.start_recording(recorder)
        runtime.pause_recording()
        with pytest.raises(RuntimeError, match="结束当前录制"):
            runtime.set_source(replace(AudioSettings(), source="microphone"))
    finally:
        runtime.stop()


def test_caption_submission_error_does_not_kill_audio_recording(tmp_path, capture) -> None:
    submitted = threading.Event()

    def fail_submission(_chunk) -> None:
        submitted.set()
        raise RuntimeError("synthetic ASR failure")

    runtime = _runtime(fail_submission)
    recorder = _recording(tmp_path)
    try:
        runtime.set_realtime_enabled(True)
        runtime.start_recording(recorder)
        capture.chunks.put(_chunk(1))
        assert submitted.wait(2)
        submitted.clear()
        capture.chunks.put(_chunk(2))
        assert submitted.wait(2)
        output = runtime.stop_recording()
        with wave.open(str(output), "rb") as stream:
            assert stream.getnframes() == 3200
    finally:
        runtime.stop()


def test_late_model_ready_callback_cannot_restart_stopped_audio(capture) -> None:
    runtime = _runtime()
    runtime.set_realtime_enabled(True)
    runtime.stop()
    runtime.set_realtime_enabled(True)
    assert not capture.running
    assert runtime._thread is None


def test_old_chunk_is_discarded_after_capture_pause_and_resume(tmp_path, capture) -> None:
    received = threading.Event()
    release_old_chunk = threading.Event()
    original_get = capture.get_chunk
    first = True

    def get_chunk(timeout: float) -> AudioChunk:
        nonlocal first
        chunk = original_get(timeout)
        if first:
            first = False
            received.set()
            assert release_old_chunk.wait(2)
        return chunk

    capture.get_chunk = get_chunk
    runtime = _runtime()
    recorder = _recording(tmp_path)
    try:
        runtime.start_recording(recorder)
        capture.chunks.put(_chunk(1))
        assert received.wait(2)
        runtime.pause_recording()
        runtime.resume_recording()
        release_old_chunk.set()
        capture.chunks.put(_chunk(2))
        assert recorder.written.wait(2)
        output = runtime.stop_recording()
        with wave.open(str(output), "rb") as stream:
            assert stream.getnframes() == 1600
    finally:
        release_old_chunk.set()
        runtime.stop()


def test_capture_start_failure_does_not_leave_an_active_recording(tmp_path, capture) -> None:
    def fail_start() -> None:
        raise RuntimeError("synthetic capture unavailable")

    capture.start = fail_start
    runtime = _runtime()
    recorder = _recording(tmp_path)
    try:
        with pytest.raises(RuntimeError, match="capture unavailable"):
            runtime.start_recording(recorder)
        assert runtime.recording_snapshot() == ("stopped", None)
        assert recorder.store.get_project(recorder.project_id).status == "failed"
    finally:
        runtime.stop()


@pytest.mark.parametrize("realtime", [False, True])
def test_old_chunk_is_discarded_across_recording_pause_even_with_live_captions(
    tmp_path, capture, realtime
) -> None:
    received = threading.Event()
    release_old_chunk = threading.Event()
    original_get = capture.get_chunk
    first = True

    def get_chunk(timeout: float) -> AudioChunk:
        nonlocal first
        chunk = original_get(timeout)
        if first:
            first = False
            received.set()
            assert release_old_chunk.wait(2)
        return chunk

    capture.get_chunk = get_chunk
    runtime = _runtime()
    recorder = _recording(tmp_path)
    try:
        if realtime:
            runtime.set_realtime_enabled(True)
        runtime.start_recording(recorder)
        capture.chunks.put(_chunk(1))
        assert received.wait(2)
        runtime.pause_recording()
        runtime.resume_recording()
        release_old_chunk.set()
        capture.chunks.put(_chunk(2))
        assert recorder.written.wait(2)
        output = runtime.stop_recording()
        with wave.open(str(output), "rb") as stream:
            assert stream.getnframes() == 1600
    finally:
        release_old_chunk.set()
        runtime.stop()


def test_recording_timestamp_boundary_discards_or_trims_buffered_audio() -> None:
    chunk = replace(_chunk(1), captured_at_ns=1_000_000_000)
    assert _recording_chunk_after(chunk, 1_100_000_000) is None
    assert _recording_chunk_after(chunk, 999_000_000) is chunk
    trimmed = _recording_chunk_after(chunk, 1_050_000_000)
    assert trimmed is not None
    assert len(trimmed.samples) == 800
    assert trimmed.captured_at_ns == 1_050_000_000
    assert len(chunk.samples) == 1600


def test_empty_recording_stop_emits_failure_and_clears_active_ui_state(tmp_path, capture) -> None:
    statuses = []
    runtime = _runtime()
    runtime.on_recording = lambda *args: statuses.append(args)
    recorder = _recording(tmp_path)
    try:
        runtime.start_recording(recorder)
        with pytest.raises(RuntimeError, match="没有捕获到音频"):
            runtime.stop_recording()
        assert runtime.recording_snapshot() == ("stopped", None)
        assert statuses[-1][0] == "failed"
        assert statuses[-1][2] == recorder.project_id
        assert not capture.running
    finally:
        runtime.stop()


def test_recording_write_failure_is_isolated_and_a_new_recording_can_start(
    tmp_path, capture
) -> None:
    failed = threading.Event()
    runtime = _runtime()
    runtime.on_recording = lambda state, *_args: failed.set() if state == "failed" else None
    broken = _recording(tmp_path)

    def fail_write(_chunk: AudioChunk) -> None:
        raise OSError("synthetic disk full")

    broken.write = fail_write
    try:
        runtime.start_recording(broken)
        capture.chunks.put(_chunk(1))
        assert failed.wait(2)
        assert runtime.recording_snapshot() == ("stopped", None)
        assert broken.store.get_project(broken.project_id).status == "failed"
        recovered = _recording(tmp_path)
        runtime.start_recording(recovered)
        capture.chunks.put(_chunk(2))
        assert recovered.written.wait(2)
        output = runtime.stop_recording()
        with wave.open(str(output), "rb") as stream:
            assert stream.getnframes() == 1600
    finally:
        runtime.stop()


def test_realtime_resumption_does_not_submit_pre_pause_audio(
    tmp_path, capture, monkeypatch
) -> None:
    # Windows clocks can give identical readings across rapid UI transitions.
    # The state generation, not timestamp inequality alone, must reject old audio.
    monkeypatch.setattr("lingua_relay.audio.runtime.time.monotonic_ns", lambda: 1_000_000_000)
    received = threading.Event()
    release_old_chunk = threading.Event()
    submitted = threading.Event()
    original_get = capture.get_chunk
    first = True
    published = []

    def get_chunk(timeout: float) -> AudioChunk:
        nonlocal first
        chunk = original_get(timeout)
        if first:
            first = False
            received.set()
            assert release_old_chunk.wait(2)
        return chunk

    def publish(chunk: AudioChunk) -> None:
        published.append(chunk.sequence)
        submitted.set()

    capture.get_chunk = get_chunk
    runtime = _runtime(publish)
    recorder = _recording(tmp_path)
    try:
        runtime.set_realtime_enabled(True)
        runtime.start_recording(recorder)
        capture.chunks.put(_chunk(1))
        assert received.wait(2)
        runtime.set_realtime_enabled(False)
        runtime.set_realtime_enabled(True)
        release_old_chunk.set()
        capture.chunks.put(_chunk(2))
        assert submitted.wait(2)
        assert published == [2]
    finally:
        release_old_chunk.set()
        runtime.stop()


def test_stop_closes_recording_only_after_audio_consumer_has_finished(tmp_path, capture) -> None:
    runtime = _runtime()
    recorder = _recording(tmp_path)
    entered = threading.Event()
    release_write = threading.Event()
    closed = threading.Event()
    original_write = recorder.write
    original_stop = recorder.stop

    def blocked_write(chunk: AudioChunk) -> None:
        entered.set()
        assert release_write.wait(2)
        original_write(chunk)

    def observed_stop() -> Path:
        assert release_write.is_set()
        output = original_stop()
        closed.set()
        return output

    recorder.write = blocked_write
    recorder.stop = observed_stop
    stopper = threading.Thread(target=runtime.stop)
    try:
        runtime.start_recording(recorder)
        capture.chunks.put(_chunk(1))
        assert entered.wait(2)
        stopper.start()
        assert not closed.is_set()
        release_write.set()
        stopper.join(2)
        assert not stopper.is_alive()
        assert closed.is_set()
    finally:
        release_write.set()
        runtime.stop()
