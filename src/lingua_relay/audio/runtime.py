from __future__ import annotations

import queue
import threading
import time
from collections.abc import Callable
from contextlib import suppress
from dataclasses import replace
from pathlib import Path

from lingua_relay.audio.capture import WasapiLoopbackCapture, create_audio_capture
from lingua_relay.audio.types import AudioChunk
from lingua_relay.config import AudioSettings
from lingua_relay.offline.recording import RecordingSession


class AudioCaptureRuntime:
    """Share one capture stream between captions and model-independent recording."""

    def __init__(
        self,
        settings: AudioSettings,
        *,
        resource_dir: Path,
        on_chunk: Callable[[AudioChunk], None],
        on_message: Callable[[str], None],
        on_recording: Callable[[str, str, str | None], None],
    ) -> None:
        self.settings = settings
        self.resource_dir = resource_dir
        self.on_chunk = on_chunk
        self.on_message = on_message
        self.on_recording = on_recording
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._capture: WasapiLoopbackCapture | None = None
        self._recorder: RecordingSession | None = None
        self._realtime_enabled = False
        self._closed = False
        self._capturing = False
        self._generation = 0
        self._recording_generation = 0
        self._realtime_generation = 0
        self._recording_after_ns = 0
        self._realtime_after_ns = 0
        self._last_capture_error: str | None = None

    def recording_snapshot(self) -> tuple[str, str | None]:
        with self._lock:
            recorder = self._recorder
            return (recorder.state, recorder.project_id) if recorder else ("stopped", None)

    def prepare(self) -> None:
        with self._lock:
            self._closed = False

    def accepts_realtime_chunk(self, chunk: AudioChunk) -> bool:
        with self._lock:
            return (
                not self._closed
                and self._realtime_enabled
                and chunk.captured_at_ns >= self._realtime_after_ns
            )

    def set_realtime_enabled(self, enabled: bool) -> None:
        with self._lock:
            if self._closed and enabled:
                return
            if enabled != self._realtime_enabled:
                self._realtime_generation += 1
                if enabled:
                    self._realtime_after_ns = time.monotonic_ns()
            self._realtime_enabled = enabled
            self._update_capture()

    def set_source(self, settings: AudioSettings) -> None:
        with self._lock:
            if self._recording_active():
                raise RuntimeError("请先结束当前录制，再切换音频源")
            replacement = create_audio_capture(settings, resource_dir=self.resource_dir)
            if self._capture is not None:
                self._capture.stop()
            self._capturing = False
            self._generation += 1
            self.settings = settings
            self._capture = replacement
            self._last_capture_error = None
            self._update_capture()

    def start_recording(self, session: RecordingSession) -> None:
        with self._lock:
            if self._recording_active():
                raise RuntimeError("已有录制正在进行")
            self._closed = False
            session.start()
            self._recorder = session
            self._recording_generation += 1
            self._recording_after_ns = time.monotonic_ns()
            try:
                self._update_capture()
            except Exception as error:
                session.abort(str(error))
                self._recorder = None
                raise
        self.on_recording("recording", "正在录制", session.project_id)

    def pause_recording(self) -> None:
        with self._lock:
            recorder = self._require_recorder()
            recorder.pause()
            self._recording_generation += 1
            self._update_capture()
        self.on_recording("paused", "录制已暂停", recorder.project_id)

    def resume_recording(self) -> None:
        with self._lock:
            recorder = self._require_recorder()
            recorder.resume()
            self._recording_generation += 1
            self._recording_after_ns = time.monotonic_ns()
            self._update_capture()
        self.on_recording("recording", "正在录制", recorder.project_id)

    def stop_recording(self) -> Path:
        failure: Exception | None = None
        output: Path | None = None
        with self._lock:
            recorder = self._require_recorder()
            try:
                output = recorder.stop()
            except Exception as error:
                failure = error
                with suppress(Exception):
                    recorder.abort(str(error))
            finally:
                self._recorder = None
                self._recording_generation += 1
                try:
                    self._update_capture()
                except Exception as error:
                    failure = failure or error
        if failure is not None:
            self.on_recording("failed", str(failure), recorder.project_id)
            raise failure
        self.on_recording("stopped", "录制完成，准备后期处理", recorder.project_id)
        assert output is not None
        return output

    def stop(self, timeout: float = 5.0) -> None:
        """Join the audio consumer before closing a recorder's active WAV file."""
        with self._lock:
            self._closed = True
            self._realtime_enabled = False
            self._realtime_generation += 1
            self._recording_generation += 1
            self._capturing = False
            self._generation += 1
            self._stop.set()
            capture = self._capture
            thread = self._thread
        if capture is not None:
            capture.stop()
        if thread is not None:
            thread.join(timeout)
            if thread.is_alive():
                raise TimeoutError("audio routing worker did not stop in time")
        with self._lock:
            self._thread = None
            self._realtime_enabled = False
            recorder = self._recorder
            if recorder is not None and recorder.state in {"recording", "paused"}:
                try:
                    recorder.stop()
                except Exception as error:
                    recorder.abort(str(error))
            self._recorder = None

    def release_resources(self) -> None:
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                raise RuntimeError("audio runtime must stop before releasing capture resources")
            self._capture = None

    def _require_recorder(self) -> RecordingSession:
        recorder = self._recorder
        if recorder is None or recorder.state not in {"recording", "paused"}:
            raise RuntimeError("当前没有录制任务")
        return recorder

    def _recording_active(self) -> bool:
        return self._recorder is not None and self._recorder.state in {"recording", "paused"}

    def _needs_audio(self) -> bool:
        return self._realtime_enabled or (
            self._recorder is not None and self._recorder.state == "recording"
        )

    def _update_capture(self) -> None:
        # Called under _lock; the worker never owns this lock while calling service/UI code.
        if self._closed:
            return
        if not self._needs_audio():
            if self._capture is not None and self._capturing:
                self._capture.stop()
                self._capturing = False
                self._generation += 1
            return
        if self._capture is None:
            self._capture = create_audio_capture(self.settings, resource_dir=self.resource_dir)
        self._capture.start()
        if not self._capturing:
            self._generation += 1
            self._capturing = True
        if self._thread is None or not self._thread.is_alive():
            self._stop.clear()
            self._thread = threading.Thread(
                target=self._run, name="lingua-relay-audio-router", daemon=True
            )
            self._thread.start()

    def _run(self) -> None:
        while not self._stop.is_set():
            with self._lock:
                capture = self._capture
                needs_audio = self._needs_audio()
                generation = self._generation
                recording_generation = self._recording_generation
                recording_owner = self._recorder
                realtime_generation = self._realtime_generation
            if capture is None or not needs_audio:
                self._stop.wait(0.05)
                continue
            try:
                chunk = capture.get_chunk(timeout=0.05)
            except queue.Empty:
                self._report_capture_state(capture)
                continue
            except Exception as error:
                self._report_error(f"音频读取失败：{type(error).__name__}: {error}")
                self._stop.wait(0.1)
                continue
            self._report_capture_state(capture)
            failed_recording: tuple[str, str] | None = None
            with self._lock:
                # A source switch/pause may finish while get_chunk is waiting.
                if (
                    self._stop.is_set()
                    or capture is not self._capture
                    or generation != self._generation
                ):
                    continue
                recorder = self._recorder
                if (
                    recorder is not None
                    and recorder.state == "recording"
                    and (
                        recording_generation == self._recording_generation
                        or chunk.captured_at_ns > self._recording_after_ns
                        or (
                            recording_owner is not recorder
                            and chunk.captured_at_ns >= self._recording_after_ns
                        )
                    )
                ):
                    try:
                        recording_chunk = _recording_chunk_after(chunk, self._recording_after_ns)
                        if recording_chunk is not None:
                            recorder.write(recording_chunk)
                    except Exception as error:
                        detail = f"{type(error).__name__}: {error}"
                        with suppress(Exception):
                            recorder.abort(detail)
                        failed_recording = (detail, recorder.project_id)
                        self._recorder = None
                        self._update_capture()
                realtime_enabled = (
                    self._realtime_enabled
                    and realtime_generation == self._realtime_generation
                    and chunk.captured_at_ns >= self._realtime_after_ns
                )
            if failed_recording is not None:
                self.on_recording("failed", *failed_recording)
            if realtime_enabled and not self._stop.is_set():
                try:
                    self.on_chunk(chunk)
                except Exception as error:
                    self._report_error(f"字幕音频提交失败：{type(error).__name__}: {error}")

    def _report_error(self, detail: str) -> None:
        if detail != self._last_capture_error:
            self._last_capture_error = detail
            self.on_message(detail)

    def _report_capture_state(self, capture: WasapiLoopbackCapture) -> None:
        snapshot = capture.snapshot()
        if snapshot.last_error and snapshot.state in {"reconnecting", "failed"}:
            self._report_error(f"音频重连中：{snapshot.last_error}")
        elif snapshot.state == "running" and self._last_capture_error is not None:
            self._last_capture_error = None
            self.on_message("音频已恢复")


def _recording_chunk_after(chunk: AudioChunk, started_at_ns: int) -> AudioChunk | None:
    """Keep only samples captured after record/resume, including queued partial blocks."""
    delta_ns = max(0, started_at_ns - chunk.captured_at_ns)
    first_sample = (delta_ns * chunk.sample_rate + 999_999_999) // 1_000_000_000
    if first_sample >= len(chunk.samples):
        return None
    if not first_sample:
        return chunk
    return replace(
        chunk,
        samples=chunk.samples[first_sample:],
        captured_at_ns=chunk.captured_at_ns + first_sample * 1_000_000_000 // chunk.sample_rate,
    )
