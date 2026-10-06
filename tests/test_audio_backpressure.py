"""K-001: bounded realtime handoff, recording conservation and shutdown ownership."""

from __future__ import annotations

import queue
import threading
import time
import wave
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from lingua_relay.audio.runtime import AudioCaptureRuntime
from lingua_relay.audio.types import AudioChunk, AudioLevel
from lingua_relay.config import AudioSettings
from lingua_relay.offline import recording as recording_module
from lingua_relay.offline.project import OfflineProjectStore
from lingua_relay.offline.recording import RecordingSession

SAMPLES_PER_CHUNK = 1600


class FakeCapture:
    def __init__(self) -> None:
        self.chunks: queue.Queue[AudioChunk | None] = queue.Queue()
        self.running = False

    def start(self) -> None:
        self.running = True

    def stop(self, timeout: float = 5.0) -> None:
        self.running = False
        self.chunks.put(None)  # Wake get_chunk without a timing-dependent polling sleep.

    def get_chunk(self, timeout: float) -> AudioChunk:
        chunk = self.chunks.get(timeout=timeout)
        if chunk is None:
            raise queue.Empty
        return chunk

    def snapshot(self) -> SimpleNamespace:
        return SimpleNamespace(state="running" if self.running else "stopped", last_error=None)


class ObservedRecording(RecordingSession):
    def __init__(self, store: OfflineProjectStore, project_id: str) -> None:
        super().__init__(store, project_id)
        self.sequences: list[int] = []
        self.writes = threading.Condition()

    def write(self, chunk: AudioChunk) -> None:
        super().write(chunk)
        with self.writes:
            self.sequences.append(chunk.sequence)
            self.writes.notify_all()

    def wait_for_chunks(self, count: int) -> bool:
        with self.writes:
            return self.writes.wait_for(lambda: len(self.sequences) >= count, timeout=2)


@pytest.fixture
def capture(monkeypatch) -> FakeCapture:
    capture = FakeCapture()
    monkeypatch.setattr(
        "lingua_relay.audio.runtime.create_audio_capture", lambda *_args, **_kwargs: capture
    )
    return capture


def recording(tmp_path: Path) -> ObservedRecording:
    store = OfflineProjectStore(tmp_path / "projects")
    project = store.create_project(
        title="Synthetic backpressure", kind="recording", source_language="en", target_language="zh"
    )
    return ObservedRecording(store, project.id)


def chunk(sequence: int) -> AudioChunk:
    return AudioChunk(
        np.full(SAMPLES_PER_CHUNK, sequence / 32, dtype=np.float32),
        sequence,
        time.monotonic_ns(),
        16_000,
        "synthetic",
        "Synthetic",
        AudioLevel(0.25, 0.25, -12, False),
    )


def runtime(on_chunk=lambda _chunk: None, *, on_overload=None) -> AudioCaptureRuntime:
    return AudioCaptureRuntime(
        AudioSettings(),
        resource_dir=Path("."),
        on_chunk=on_chunk,
        on_message=lambda _message: None,
        on_recording=lambda *_args: None,
        on_overload=on_overload,
    )


def assert_wave_samples(path: Path, sequences: list[int]) -> None:
    with wave.open(str(path), "rb") as stream:
        assert stream.getnchannels() == 1
        assert stream.getsampwidth() == 2
        assert stream.getframerate() == 16_000
        assert stream.getnframes() == len(sequences) * SAMPLES_PER_CHUNK
        actual = np.frombuffer(stream.readframes(stream.getnframes()), dtype="<i2")
    expected = np.concatenate(
        [np.full(SAMPLES_PER_CHUNK, sequence / 32, dtype=np.float32) for sequence in sequences]
    )
    np.testing.assert_array_equal(actual, (expected * 32767).astype("<i2"))


def assert_stop_is_bounded(audio: AudioCaptureRuntime) -> None:
    started = time.monotonic()
    with pytest.raises(TimeoutError):
        audio.stop(timeout=0.02)
    # Scheduler tolerance, not an actual-device latency/performance target.
    assert time.monotonic() - started < 0.5


def assert_pending_ownership(audio: AudioCaptureRuntime, capture: FakeCapture) -> None:
    assert audio._capture is capture
    assert audio._shutdown_pending
    with pytest.raises(RuntimeError, match="stop before releasing"):
        audio.release_resources()
    with pytest.raises(RuntimeError, match="停止尚未完成"):
        audio.prepare()


def test_full_realtime_handoff_preserves_recording_samples(tmp_path, capture) -> None:
    entered, release, overloaded = threading.Event(), threading.Event(), threading.Event()
    submitted = []
    messages = []

    def blocked_submission(value: AudioChunk) -> None:
        submitted.append(value.sequence)
        entered.set()
        assert release.wait(5)

    def report_overload(message: str) -> None:
        messages.append(message)
        overloaded.set()

    audio = runtime(blocked_submission, on_overload=report_overload)
    recorder = recording(tmp_path)
    try:
        audio.set_realtime_enabled(True)
        audio.start_recording(recorder)
        capture.chunks.put(chunk(1))
        assert entered.wait(2)
        for sequence in range(2, 7):
            capture.chunks.put(chunk(sequence))
        assert overloaded.wait(2)
        assert recorder.wait_for_chunks(6)
        snapshot = audio.snapshot()
        assert snapshot.handoff_capacity == 4
        assert snapshot.handoff_accepted == 5
        assert snapshot.handoff_rejected == 1
        assert snapshot.handoff_cancelled == 4
        assert snapshot.handoff_completed == snapshot.handoff_failed == snapshot.handoff_depth == 0
        assert snapshot.realtime_inflight and snapshot.overloaded
        assert not snapshot.realtime_enabled
        assert capture.running and recorder.state == "recording"
        assert len(messages) == 1 and "过载" in messages[0]
        # Recording continues beyond overload while the same realtime call is still blocked.
        for sequence in range(7, 10):
            capture.chunks.put(chunk(sequence))
        assert recorder.wait_for_chunks(9)
        assert not release.is_set() and submitted == [1]
        assert recorder.sequences == list(range(1, 10))
        output = audio.stop_recording()
        assert_wave_samples(output, list(range(1, 10)))
        release.set()
        audio.stop(timeout=2)
        final = audio.snapshot()
        assert final.handoff_completed == 1 and final.handoff_failed == 0
        assert final.handoff_accepted == final.handoff_completed + final.handoff_cancelled
        assert not final.realtime_inflight
    finally:
        release.set()
        audio.stop(timeout=2)


@pytest.mark.parametrize("blocked_stage", ["submission", "write"])
def test_stop_timeout_keeps_blocked_audio_owner_and_allows_retry(
    tmp_path, capture, blocked_stage
) -> None:
    entered, release = threading.Event(), threading.Event()

    def blocked_submission(_chunk: AudioChunk) -> None:
        entered.set()
        assert release.wait(5)

    audio = runtime(blocked_submission if blocked_stage == "submission" else lambda _chunk: None)
    recorder = recording(tmp_path)
    if blocked_stage == "write":
        original_write = recorder.write

        def blocked_write(value: AudioChunk) -> None:
            entered.set()
            assert release.wait(5)
            original_write(value)

        recorder.write = blocked_write
    try:
        if blocked_stage == "submission":
            audio.set_realtime_enabled(True)
        audio.start_recording(recorder)
        capture.chunks.put(chunk(1))
        assert entered.wait(2)
        owner = audio._realtime_thread if blocked_stage == "submission" else audio._thread
        assert owner is not None and owner.is_alive()
        assert_stop_is_bounded(audio)
        assert owner.is_alive()
        assert (audio._realtime_thread if blocked_stage == "submission" else audio._thread) is owner
        assert_pending_ownership(audio, capture)
        release.set()
        audio.stop(timeout=2)
        assert not owner.is_alive()
        assert audio._thread is audio._realtime_thread is None
        assert not audio._shutdown_pending
        assert recorder.state == "stopped"
        assert_wave_samples(recorder.directory / "recording.wav", [1])
        audio.release_resources()
        assert audio._capture is None
        audio.prepare()  # A confirmed stop, unlike a timed-out one, permits a fresh session.
    finally:
        release.set()
        audio.stop(timeout=2)


def test_recording_merge_uses_stop_deadline_and_keeps_router_owner(
    tmp_path, capture, monkeypatch
) -> None:
    entered, release = threading.Event(), threading.Event()
    original_merge = recording_module._merge_wave_fragments

    def blocked_merge(fragments, output, sample_rate) -> None:
        entered.set()
        assert release.wait(5)
        original_merge(fragments, output, sample_rate)

    monkeypatch.setattr(recording_module, "_merge_wave_fragments", blocked_merge)
    audio = runtime()
    recorder = recording(tmp_path)
    try:
        audio.start_recording(recorder)
        capture.chunks.put(chunk(1))
        assert recorder.wait_for_chunks(1)
        owner = audio._thread
        assert owner is not None
        # Request cleanup first, then synchronize on real merge entry rather than sleep.
        with pytest.raises(TimeoutError):
            audio.stop(timeout=0)
        assert entered.wait(2)
        assert owner.is_alive() and audio._thread is owner
        assert_stop_is_bounded(audio)
        assert owner.is_alive() and audio._thread is owner
        assert_pending_ownership(audio, capture)
        release.set()
        audio.stop(timeout=2)
        assert not owner.is_alive() and audio._thread is None
        assert recorder.state == "stopped"
        assert_wave_samples(recorder.directory / "recording.wav", [1])
        audio.release_resources()
        assert audio._capture is None
    finally:
        release.set()
        audio.stop(timeout=2)
