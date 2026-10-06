from __future__ import annotations

import queue
import threading
import time
from collections import deque
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass, replace
from pathlib import Path

from lingua_relay.audio.capture import WasapiLoopbackCapture, create_audio_capture
from lingua_relay.audio.types import AudioChunk
from lingua_relay.config import AudioSettings
from lingua_relay.offline.recording import RecordingSession


@dataclass(frozen=True, slots=True)
class AudioRuntimeSnapshot:
    """Handoff counts describe audio blocks, not completed ASR segments."""

    handoff_depth: int
    handoff_capacity: int
    handoff_accepted: int
    handoff_completed: int
    handoff_failed: int
    handoff_rejected: int
    handoff_cancelled: int
    realtime_enabled: bool
    realtime_inflight: bool
    overloaded: bool


class AudioCaptureRuntime:
    """Record captured audio independently of a bounded realtime submission worker."""

    def __init__(
        self,
        settings: AudioSettings,
        *,
        resource_dir: Path,
        on_chunk: Callable[[AudioChunk], None],
        on_message: Callable[[str], None],
        on_recording: Callable[[str, str, str | None], None],
        on_overload: Callable[[str], None] | None = None,
        realtime_queue_capacity: int = 4,
    ) -> None:
        if realtime_queue_capacity < 1:
            raise ValueError("realtime_queue_capacity must be positive")
        self.settings = settings
        self.resource_dir = resource_dir
        self.on_chunk = on_chunk
        self.on_message = on_message
        self.on_recording = on_recording
        self.on_overload = on_overload
        self._lock = threading.RLock()
        # Disk operations must not own the state lock: realtime pause and shutdown
        # still need to invalidate a generation while a recording write is blocked.
        self._recording_lock = threading.RLock()
        self._handoff_ready = threading.Condition(self._lock)
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._realtime_thread: threading.Thread | None = None
        self._handoff: deque[tuple[int, AudioChunk]] = deque()
        self._handoff_capacity = realtime_queue_capacity
        self._handoff_accepted = 0
        self._handoff_completed = 0
        self._handoff_failed = 0
        self._handoff_rejected = 0
        self._handoff_cancelled = 0
        self._inflight: tuple[int, AudioChunk] | None = None
        self._overloaded = False
        self._capture_stop_pending = False
        self._shutdown_pending = False
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

    def snapshot(self) -> AudioRuntimeSnapshot:
        with self._lock:
            return AudioRuntimeSnapshot(
                handoff_depth=len(self._handoff),
                handoff_capacity=self._handoff_capacity,
                handoff_accepted=self._handoff_accepted,
                handoff_completed=self._handoff_completed,
                handoff_failed=self._handoff_failed,
                handoff_rejected=self._handoff_rejected,
                handoff_cancelled=self._handoff_cancelled,
                realtime_enabled=self._realtime_enabled,
                realtime_inflight=self._inflight is not None,
                overloaded=self._overloaded,
            )

    def recording_snapshot(self) -> tuple[str, str | None]:
        with self._lock:
            recorder = self._recorder
            return (recorder.state, recorder.project_id) if recorder else ("stopped", None)

    def prepare(self) -> None:
        with self._lock:
            self._require_stopped_workers()
            self._closed = False
            self._stop.clear()

    def accepts_realtime_chunk(self, chunk: AudioChunk) -> bool:
        with self._lock:
            return (
                not self._closed
                and not self._stop.is_set()
                and self._realtime_enabled
                and self._inflight is not None
                and self._inflight[0] == self._realtime_generation
                and self._inflight[1] is chunk
                and chunk.captured_at_ns >= self._realtime_after_ns
            )

    def set_realtime_enabled(self, enabled: bool) -> None:
        with self._lock:
            if (self._closed or self._stop.is_set()) and enabled:
                return
            if enabled:
                self._require_stopped_workers()
            if enabled != self._realtime_enabled:
                if enabled and self._inflight is not None:
                    raise RuntimeError("上一轮实时音频提交尚未结束，请稍后再恢复字幕")
                self._realtime_generation += 1
                self._cancel_handoff()
                if enabled:
                    self._realtime_after_ns = time.monotonic_ns()
                    self._overloaded = False
            self._realtime_enabled = enabled
            self._update_capture()

    def set_source(self, settings: AudioSettings) -> None:
        with self._recording_lock, self._lock:
            self._require_stopped_workers()
            if self._recording_active():
                raise RuntimeError("请先结束当前录制，再切换音频源")
            replacement = create_audio_capture(settings, resource_dir=self.resource_dir)
            if self._capture is not None:
                self._capture.stop()
            self._capturing = False
            self._generation += 1
            self._realtime_generation += 1
            self._cancel_handoff()
            self.settings = settings
            self._capture = replacement
            self._last_capture_error = None
            self._update_capture()

    def start_recording(self, session: RecordingSession) -> None:
        with self._recording_lock:
            with self._lock:
                self._require_stopped_workers()
                if self._recording_active():
                    raise RuntimeError("已有录制正在进行")
                self._closed = False
                self._stop.clear()
            session.start()
            try:
                with self._lock:
                    if self._closed or self._stop.is_set():
                        raise RuntimeError("音频运行时正在停止，不能开始录制")
                    self._recorder = session
                    self._recording_generation += 1
                    self._recording_after_ns = time.monotonic_ns()
                    self._update_capture()
            except Exception as error:
                session.abort(str(error))
                with self._lock:
                    self._recorder = None
                raise
        self.on_recording("recording", "正在录制", session.project_id)

    def pause_recording(self) -> None:
        with self._recording_lock:
            with self._lock:
                recorder = self._require_recorder()
            recorder.pause()
            with self._lock:
                self._recording_generation += 1
                self._update_capture()
        self.on_recording("paused", "录制已暂停", recorder.project_id)

    def resume_recording(self) -> None:
        with self._recording_lock:
            with self._lock:
                recorder = self._require_recorder()
            recorder.resume()
            with self._lock:
                self._recording_generation += 1
                self._recording_after_ns = time.monotonic_ns()
                self._update_capture()
        self.on_recording("recording", "正在录制", recorder.project_id)

    def stop_recording(self) -> Path:
        failure: Exception | None = None
        output: Path | None = None
        with self._recording_lock:
            with self._lock:
                recorder = self._require_recorder()
            try:
                output = recorder.stop()
            except Exception as error:
                failure = error
                with suppress(Exception):
                    recorder.abort(str(error))
            finally:
                with self._lock:
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
        """Use one deadline; retain ownership of every worker that has not exited."""
        deadline = time.monotonic() + max(0.0, timeout)
        self._shutdown_pending = True
        self._stop.set()
        if not self._lock.acquire(timeout=max(0.0, deadline - time.monotonic())):
            raise TimeoutError("audio runtime state change did not stop in time")
        try:
            self._closed = True
            self._realtime_enabled = False
            self._realtime_generation += 1
            self._recording_generation += 1
            self._capturing = False
            self._generation += 1
            self._cancel_handoff()
            capture = self._capture
            workers = (self._thread, self._realtime_thread)
        finally:
            self._lock.release()
        errors: list[str] = []
        if capture is not None:
            try:
                capture.stop(timeout=max(0.0, deadline - time.monotonic()))
                self._capture_stop_pending = False
            except Exception as error:
                self._capture_stop_pending = True
                errors.append(f"audio capture: {error}")
        for thread in workers:
            if thread is None:
                continue
            if thread is not threading.current_thread():
                thread.join(max(0.0, deadline - time.monotonic()))
            if thread.is_alive():
                errors.append(f"{thread.name} did not stop in time")
        if errors:
            raise TimeoutError("; ".join(errors))
        with self._lock:
            self._thread = None
            self._realtime_thread = None
            self._shutdown_pending = False

    def release_resources(self) -> None:
        with self._lock:
            if self._shutdown_pending or self._capture_stop_pending or self._workers_alive():
                raise RuntimeError("audio runtime must stop before releasing capture resources")
            self._capture = None

    def _workers_alive(self) -> bool:
        return any(
            thread is not None and thread.is_alive()
            for thread in (self._thread, self._realtime_thread)
        )

    def _require_stopped_workers(self) -> None:
        if (
            self._shutdown_pending
            or self._capture_stop_pending
            or (self._stop.is_set() and self._workers_alive())
        ):
            raise RuntimeError("上一次音频停止尚未完成，请等待旧线程结束后重试")

    def _cancel_handoff(self) -> None:
        self._handoff_cancelled += len(self._handoff)
        self._handoff.clear()
        self._handoff_ready.notify_all()

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
        if self._closed or self._stop.is_set():
            return
        if not self._needs_audio():
            if self._capture is not None and self._capturing:
                self._capturing = False
                self._generation += 1
                self._capture_stop_pending = True
            if self._capture is not None and self._capture_stop_pending:
                # Only request/poll here. Never spend a default five-second join
                # under the state lock or outside service's total stop deadline.
                try:
                    self._capture.stop(timeout=0)
                except TimeoutError:
                    return
                self._capture_stop_pending = False
            return
        if self._capture is None:
            self._capture = create_audio_capture(self.settings, resource_dir=self.resource_dir)
        self._capture.start()
        if not self._capturing:
            self._generation += 1
            self._capturing = True
        if self._thread is None or not self._thread.is_alive():
            self._thread = threading.Thread(
                target=self._run, name="lingua-relay-audio-router", daemon=True
            )
            self._thread.start()
        if self._realtime_thread is None or not self._realtime_thread.is_alive():
            self._realtime_thread = threading.Thread(
                target=self._run_realtime, name="lingua-relay-audio-realtime", daemon=True
            )
            self._realtime_thread.start()

    def _run(self) -> None:
        try:
            self._route_audio()
        finally:
            # Closing/merging a WAV may itself wait on disk I/O. Keep it on the
            # owned router so stop's join deadline also covers recording cleanup.
            with self._recording_lock:
                with self._lock:
                    recorder = self._recorder
                if recorder is not None and recorder.state in {"recording", "paused"}:
                    try:
                        recorder.stop()
                    except Exception as error:
                        with suppress(Exception):
                            recorder.abort(str(error))
                with self._lock:
                    self._recorder = None

    def _route_audio(self) -> None:
        while not self._stop.is_set():
            with self._lock:
                capture = self._capture
                needs_audio = self._needs_audio()
                generation = self._generation
                recording_generation = self._recording_generation
                recording_owner = self._recorder
                realtime_generation = self._realtime_generation
            if capture is None or not needs_audio:
                if capture is not None:
                    try:
                        with self._lock:
                            self._update_capture()
                    except Exception as error:
                        self._report_error(f"音频暂停失败：{type(error).__name__}")
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
            overload_message: str | None = None
            with self._recording_lock:
                # A source switch/pause may finish while get_chunk is waiting.
                with self._lock:
                    if (
                        self._stop.is_set()
                        or capture is not self._capture
                        or generation != self._generation
                    ):
                        continue
                    recorder = self._recorder
                    recording_chunk = None
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
                        recording_chunk = _recording_chunk_after(chunk, self._recording_after_ns)
                if recorder is not None and recording_chunk is not None:
                    try:
                        recorder.write(recording_chunk)
                    except Exception as error:
                        detail = f"{type(error).__name__}: {error}"
                        with suppress(Exception):
                            recorder.abort(detail)
                        failed_recording = (detail, recorder.project_id)
                        with self._lock:
                            self._recorder = None
                            self._update_capture()
            with self._lock:
                if (
                    not self._stop.is_set()
                    and self._realtime_enabled
                    and realtime_generation == self._realtime_generation
                    and chunk.captured_at_ns >= self._realtime_after_ns
                ):
                    if len(self._handoff) < self._handoff_capacity:
                        self._handoff.append((realtime_generation, chunk))
                        self._handoff_accepted += 1
                        self._handoff_ready.notify()
                    else:
                        self._handoff_rejected += 1
                        self._overloaded = True
                        self._realtime_enabled = False
                        self._realtime_generation += 1
                        self._cancel_handoff()
                        overload_message = (
                            "实时字幕处理过载，已暂停；录制不受此暂停影响。"
                            "请等待当前处理结束后手动恢复字幕。"
                        )
                        self._update_capture()
            if failed_recording is not None:
                self.on_recording("failed", *failed_recording)
            if overload_message is not None:
                # Callbacks are notifications only; they must not synchronously
                # join this router or perform model/disk work.
                self.on_message(overload_message)
                if self.on_overload is not None:
                    self.on_overload(overload_message)

    def _run_realtime(self) -> None:
        while not self._stop.is_set():
            with self._handoff_ready:
                self._handoff_ready.wait_for(
                    lambda: self._stop.is_set() or bool(self._handoff), timeout=0.05
                )
                if self._stop.is_set():
                    return
                if not self._handoff:
                    continue
                generation, chunk = self._handoff.popleft()
                if not self._realtime_enabled or generation != self._realtime_generation:
                    self._handoff_cancelled += 1
                    continue
                self._inflight = (generation, chunk)
            failed = False
            try:
                self.on_chunk(chunk)
            except Exception as error:
                failed = True
                self.on_message(f"字幕音频提交失败：{type(error).__name__}: {error}")
            finally:
                with self._handoff_ready:
                    if failed:
                        self._handoff_failed += 1
                    else:
                        self._handoff_completed += 1
                    self._inflight = None
                    self._handoff_ready.notify_all()

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
