from __future__ import annotations

import math
import queue
import threading
import time
from collections import deque
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass, replace
from pathlib import Path

from lingua_relay.asr import FasterWhisperRecognizer, StreamingAsrEngine
from lingua_relay.asr.types import AsrEvent
from lingua_relay.audio.runtime import AudioCaptureRuntime
from lingua_relay.audio.types import AudioChunk
from lingua_relay.config import AudioSettings, Settings
from lingua_relay.correction import (
    AsynchronousRevisionEngine,
    OpenAICompatibleProvider,
    load_glossary,
)
from lingua_relay.events import CaptionEvent, ProcessingScope
from lingua_relay.history import JsonlHistory
from lingua_relay.mt import M2M100Translator, StreamingTranslationEngine
from lingua_relay.offline.recording import RecordingSession
from lingua_relay.telemetry import TraceCollector
from lingua_relay.translation import build_m2m100_registry


@dataclass(frozen=True, slots=True)
class ServiceSnapshot:
    state: str
    source_language: str
    target_language: str
    audio_device: str
    last_error: str | None
    correction_mode: str
    correction_state: str
    correction_scope: ProcessingScope | None
    correction_error: str | None
    recording_state: str
    recording_project_id: str | None
    overloaded: bool = False
    pending_finals: int = 0
    finals_aborted: int = 0


class RealtimeCaptionService:
    """Own the M1 -> M4 pipeline outside the Qt thread."""

    def __init__(
        self,
        settings: Settings,
        *,
        on_caption: Callable[[CaptionEvent], None],
        on_transcript: Callable[[AsrEvent, str], None] | None = None,
        on_status: Callable[[str, str], None] | None = None,
        on_correction_status: Callable[[str, str], None] | None = None,
        on_recording: Callable[[str, str, str | None], None] | None = None,
        model_root: str | Path = "models",
        resource_dir: str | Path = ".",
        trace: TraceCollector | None = None,
    ) -> None:
        self.settings = settings
        self.on_caption = on_caption
        self.on_transcript = on_transcript or (lambda _event, _target: None)
        self.on_status = on_status or (lambda _state, _message: None)
        self.on_correction_status = on_correction_status or (lambda _state, _message: None)
        self.on_recording = on_recording or (lambda _state, _message, _project_id: None)
        self.model_root = Path(model_root)
        self.resource_dir = Path(resource_dir)
        self.trace = trace if trace is not None else TraceCollector()
        self._source = settings.app.source_language
        self._target = settings.app.target_language
        self._device = _audio_selector(settings.audio)
        self._state = "stopped"
        self._last_error: str | None = None
        self._correction_mode = settings.correction.mode
        self._correction_state = "off" if settings.correction.mode == "off" else "loading"
        self._correction_error: str | None = None
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._paused = threading.Event()
        self._thread: threading.Thread | None = None
        self._asr: StreamingAsrEngine | None = None
        self._mt: StreamingTranslationEngine | None = None
        self._correction: AsynchronousRevisionEngine | None = None
        self._displayed_segment_id: str | None = None
        self._displayed_revision = 0
        self._overloaded = False
        self._resume_requested = threading.Event()
        self._stop_deadline: float | None = None
        self._shutdown_error: str | None = None
        self._pending_finals: deque[tuple[AsrEvent, str, float]] = deque()
        self._pending_lock = threading.RLock()
        self._pending_capacity = settings.translation.queue_capacity
        self._pending_timeout = 1.0
        self._finals_aborted = 0
        self._retired_counts: dict[str, int] = {}
        self._history_errors_reported = 0
        self._audio = AudioCaptureRuntime(
            settings.audio,
            resource_dir=self.resource_dir,
            on_chunk=self._submit_audio,
            on_message=self._notify,
            on_recording=self.on_recording,
            on_overload=self._handle_overload,
        )

    def start(self, *, paused: bool = False) -> None:
        service_alive = self._thread is not None and self._thread.is_alive()
        if (self._stop.is_set() and service_alive) or (
            (self._stop.is_set() or not service_alive) and self._workers_alive()
        ):
            raise RuntimeError("旧推理尚未结束，暂不能重新启动；请稍后重试")
        if self._thread is not None and self._thread.is_alive():
            if paused:
                self.pause()
            else:
                self.resume()
            return
        self._audio.prepare()
        self._retire_engines()
        self._asr = self._mt = self._correction = None
        self._stop.clear()
        self._stop_deadline = None
        self._shutdown_error = None
        self._overloaded = False
        self._resume_requested.clear()
        self._cancel_pending()
        self._displayed_segment_id = None
        self._displayed_revision = 0
        if paused:
            self._paused.set()
        else:
            self._paused.clear()
        self._thread = threading.Thread(target=self._run, name="lingua-relay-service", daemon=True)
        self._thread.start()

    def pause(self) -> None:
        self._paused.set()
        self._audio.set_realtime_enabled(False)
        if self._asr is not None:
            try:
                self._asr.flush(timeout=0)
            except (TimeoutError, RuntimeError):
                self._handle_overload("完整句队列繁忙，实时字幕已暂停；录制继续")
        if self._state in {"ready", "running", "paused"}:
            self._set_state("paused", "已暂停")

    @property
    def paused(self) -> bool:
        return self._paused.is_set()

    def resume(self) -> None:
        if self._overloaded:
            self._resume_requested.set()
            self._notify("准备恢复字幕；需等待旧推理结束，录制不受影响")
            return
        try:
            if self._state in {"ready", "running", "paused"}:
                self._audio.set_realtime_enabled(True)
        except RuntimeError:
            self._notify("旧字幕提交尚未结束，请稍后重试；录制继续")
            return
        self._paused.clear()
        if self._state in {"ready", "running", "paused"}:
            self._set_state("running", self._audio_status_message())

    def set_route(self, source: str, target: str) -> None:
        if source == target:
            raise ValueError("source and target languages must differ")
        with self._lock:
            source_changed = source != self._source
            self._source = source
            self._target = target
        if source_changed and self._asr is not None:
            try:
                self._asr.flush(timeout=0)
            except (TimeoutError, RuntimeError):
                self._handle_overload("切换语言时完整句队列繁忙，字幕已暂停；录制继续")
        self._notify("语言已切换，仍使用手动源语言")

    def set_correction_mode(self, mode: str) -> None:
        if mode not in {"off", "asynchronous", "live"}:
            raise ValueError("correction mode must be off, asynchronous, or live")
        if mode != "off" and self.settings.correction.provider == "none":
            raise ValueError("configure a correction provider before enabling correction")
        with self._lock:
            self._correction_mode = mode
        if self._correction is not None:
            self._correction.set_enabled(mode != "off")
        if mode == "off":
            self._set_correction_state("off", "修正已关闭；仅显示本地快译")
        else:
            label = "仅完整句异步修正" if mode == "asynchronous" else "实时异步修正"
            scope = "本地处理" if self._correction_scope() == "local" else "云端传输"
            self._set_correction_state("ready", f"{scope} · {label}")

    def set_audio_device(self, device: str) -> None:
        self.set_audio_source(replace(self.settings.audio, source="system", device=device))

    def set_audio_source(self, audio: AudioSettings) -> None:
        candidate = replace(self.settings, audio=audio)
        candidate.validate()
        self._audio.set_source(audio)
        with self._lock:
            self.settings = candidate
            self._device = _audio_selector(audio)
        self._notify(self._audio_status_message(prefix="音频源已切换："))

    def stop(self, timeout: float = 40.0) -> None:
        if not math.isfinite(timeout) or timeout < 0:
            raise ValueError("timeout must be finite and non-negative")
        deadline = time.monotonic() + timeout
        previous_shutdown_error = self._shutdown_error
        self._stop_deadline = deadline
        self._stop.set()
        if self._correction is not None:
            self._correction.set_enabled(False)
        self._set_state("stopping", "正在停止；录制与字幕正在收尾…")
        audio_error: TimeoutError | None = None
        try:
            self._audio.stop(timeout=max(0, deadline - time.monotonic()))
        except TimeoutError as error:
            audio_error = error
        thread = self._thread
        if thread is not None:
            thread.join(max(0, deadline - time.monotonic()))
            if thread.is_alive():
                for worker in (self._asr, self._mt):
                    if worker is not None:
                        worker.abort()
                self._set_state("stop_timeout", "停止超时，旧调用仍在收尾；暂不能释放模型")
                raise TimeoutError("caption service did not stop in time")
        if audio_error is not None or self._workers_alive():
            self._set_state("stop_timeout", "停止超时，旧调用仍在收尾；暂不能释放模型")
            raise TimeoutError("pipeline workers are still stopping") from audio_error
        if self._shutdown_error is not None:
            if previous_shutdown_error != self._shutdown_error:
                raise RuntimeError(self._shutdown_error)
            # A subsequent explicit retry has now confirmed audio and models stopped.
            self._last_error = self._shutdown_error
            self._shutdown_error = None
            self.trace.increment("shutdown_error_recoveries")
            self._set_state("stopped", "已停止；先前收尾错误已保留在诊断中")
        self._thread = None
        if self._state != "error":
            self._set_state("stopped", "已停止")

    def release_resources(self) -> None:
        """Release model owners after the worker has stopped for model removal."""
        thread = self._thread
        if (thread is not None and thread.is_alive()) or self._workers_alive():
            raise RuntimeError("caption service must stop before releasing model resources")
        self._audio.release_resources()
        self._asr = None
        self._mt = None
        self._correction = None

    def snapshot(self) -> ServiceSnapshot:
        recording_state, recording_project_id = self._audio.recording_snapshot()
        with self._lock:
            return ServiceSnapshot(
                self._state,
                self._source,
                self._target,
                self._device,
                self._last_error,
                self._correction_mode,
                self._correction_state,
                self._correction_scope(),
                self._correction_error,
                recording_state,
                recording_project_id,
                self._overloaded,
                len(self._pending_finals),
                self._finals_aborted,
            )

    def start_recording(self, session: RecordingSession) -> None:
        self._audio.start_recording(session)

    def pause_recording(self) -> None:
        self._audio.pause_recording()

    def resume_recording(self) -> None:
        self._audio.resume_recording()

    def stop_recording(self) -> Path:
        return self._audio.stop_recording()

    def _run(self) -> None:
        try:
            self._set_state("loading", "正在加载语音识别模型…")
            recognizer = FasterWhisperRecognizer(self.settings.asr, download_root=self.model_root)
            recognizer.load()
            if self._stop.is_set():
                return
            self._set_state("loading", "语音识别已就绪，正在加载翻译模型…")
            translation_settings = self.settings.translation
            translator = M2M100Translator(translation_settings)
            translator.load()
            if self._stop.is_set():
                return
            self._set_state("ready", "模型加载完成，正在启动音频捕获…")
            history = (
                JsonlHistory(self.settings.app.history_path)
                if self.settings.app.history_enabled
                else None
            )
            self._asr = StreamingAsrEngine(recognizer, self.settings.asr, trace=self.trace)
            self._mt = StreamingTranslationEngine(
                build_m2m100_registry(translator),
                translation_settings,
                history=history,
                trace=self.trace,
            )
            self._prepare_correction(history)
            self._asr.start()
            self._mt.start()
            if self._correction is not None:
                self._correction.start()
            if self._paused.is_set():
                self._set_state("paused", "已暂停")
            else:
                self._audio.set_realtime_enabled(True)
                self._set_state("running", self._audio_status_message())
            while not self._stop.is_set():
                self.pump_once()
                if self._resume_requested.is_set():
                    self._try_resume_overload()
                self._stop.wait(0.01)
        except Exception as error:
            with self._lock:
                self._last_error = f"{type(error).__name__}: {error}"
            self._set_state("error", self._last_error)
        finally:
            self._shutdown_workers()
            if self._workers_alive():
                self._set_state("stop_timeout", "旧推理尚未结束；模型资源暂未释放")
            elif self._state != "error":
                self._set_state("stopped", "已停止")

    def _prepare_correction(self, history: JsonlHistory | None) -> None:
        correction_settings = self.settings.correction
        if correction_settings.provider == "none":
            self._set_correction_state("off", "修正未配置；仅显示本地快译")
            return
        try:
            glossary = load_glossary(correction_settings.glossary_path)
        except (OSError, ValueError) as error:
            glossary = ()
            self._set_correction_state("warning", f"术语表无效，已忽略：{error}")
        provider = OpenAICompatibleProvider(correction_settings)
        self._correction = AsynchronousRevisionEngine(
            provider,
            correction_settings,
            history=history,
            glossary=glossary,
            on_status=self._handle_correction_status,
        )
        self._correction.set_enabled(self._correction_mode != "off")
        if self._correction_mode == "off":
            self._set_correction_state("off", "修正已关闭；仅显示本地快译")

    def _submit_audio(self, chunk: AudioChunk) -> None:
        """Audio runs independently; only ready, unpaused models consume chunks."""
        with self._lock:
            asr = self._asr
            source = self._source
        if (
            asr is not None
            and not self._paused.is_set()
            and not self._stop.is_set()
            and self._audio.accepts_realtime_chunk(chunk)
        ):
            try:
                asr.submit_chunk(chunk, language=source, timeout=0)
            except (TimeoutError, RuntimeError):
                self._handle_overload("语音识别完整句队列过载，字幕已暂停；录制继续")

    def telemetry_snapshot(self) -> dict:
        result = self.trace.snapshot()
        counts = dict(self._retired_counts)
        for name, worker in (("asr", self._asr), ("mt", self._mt)):
            if worker is not None:
                snapshot = worker.snapshot()
                for field in (
                    "final_requests_added",
                    "final_submit_rejections",
                    "final_requests_aborted",
                    "final_outputs_rejected",
                    "final_events_aborted",
                    "stale_results_dropped",
                    "history_errors",
                ):
                    key = f"{name}_{field}"
                    counts[key] = counts.get(key, 0) + getattr(snapshot, field, 0)
        result["pipeline"] = {
            "engine_counts": counts,
            "pending_finals": len(self._pending_finals),
            "service_finals_aborted": self._finals_aborted,
            "overloaded": self._overloaded,
        }
        return result

    def acknowledge_ui(self, event: CaptionEvent | AsrEvent) -> None:
        """The widgets were updated, not proof that pixels have been painted."""
        stage = "transcript_ui_updated" if isinstance(event, AsrEvent) else "ui_updated"
        self.trace.record(event.segment_id, event.revision, stage)

    def accepts_delivery(self, event: CaptionEvent | AsrEvent) -> bool:
        revision = getattr(event, "parent_revision", None)
        if revision is None:
            revision = event.revision
        with self._lock:
            return (
                not self._stop.is_set()
                and not self._overloaded
                and self._displayed_segment_id == event.segment_id
                and revision >= self._displayed_revision
            )

    def pump_once(self) -> None:
        """Drain downstream first; never wait on MT admission while owning its consumer."""
        for worker in (self._asr, self._mt):
            if worker is not None and worker.snapshot().overloaded:
                self._handle_overload("字幕输出或完整句队列持续过载，已暂停；录制继续")
        if self._mt is not None:
            self._pump_captions()
            errors = getattr(self._mt.snapshot(), "history_errors", 0)
            if errors > self._history_errors_reported:
                self._history_errors_reported = errors
                self._notify("历史记录保存失败，请检查磁盘空间和目录权限；实时翻译继续")
        self._pump_revisions()
        if not self._overloaded and self._asr is not None and self._mt is not None:
            self._pump_pending()
            self._pump_asr()
        for worker in (self._asr, self._mt):
            if worker is not None and worker.snapshot().overloaded:
                self._handle_overload("字幕输出或完整句队列持续过载，已暂停；录制继续")

    def _pump_pending(self) -> None:
        assert self._mt is not None
        with self._pending_lock:
            for _ in range(self._pending_capacity):
                if not self._pending_finals:
                    break
                event, target, deadline = self._pending_finals[0]
                accepted = self._submit_translation(event, target)
                if accepted:
                    self._pending_finals.popleft()
                elif accepted is None or not self._pending_finals or self._overloaded:
                    break
                elif time.monotonic() >= deadline:
                    self._handle_overload("完整句等待翻译超时，字幕已暂停；录制继续")
                    break
                else:
                    break

    def _submit_translation(self, event: AsrEvent, target: str) -> bool | None:
        """False is retryable congestion; None is permanent cancellation."""
        assert self._mt is not None
        try:
            return self._mt.submit(event, target=target, timeout=0)
        except (TimeoutError, RuntimeError):
            self.trace.record(event.segment_id, event.revision, "cancelled")
            if self._stop.is_set():
                self._cancel_pending()
                if self._asr is not None:
                    self._asr.abort()
            else:
                self._handle_overload("翻译引擎已停止接收，字幕已暂停；录制继续")
            return None

    def _pump_asr(self) -> None:
        assert self._asr is not None and self._mt is not None
        for _ in range(8):
            if self._overloaded or len(self._pending_finals) >= self._pending_capacity:
                return
            try:
                event = self._asr.get_event(timeout=0)
            except queue.Empty:
                return
            with self._lock:
                target = self._target
                self._displayed_segment_id = event.segment_id
                self._displayed_revision = event.revision
            if not self._stop.is_set():
                self.on_transcript(event, target)
            # A pending final must not be overtaken by a newer final.
            with self._pending_lock:
                if self._overloaded:
                    self._finals_aborted += int(event.state == "final")
                    self.trace.record(event.segment_id, event.revision, "cancelled")
                    return
                accepted = (
                    False if self._pending_finals else self._submit_translation(event, target)
                )
                if accepted is None:
                    self._finals_aborted += int(event.state == "final")
                    return
                if not accepted and event.state == "final":
                    self._pending_finals.append(
                        (event, target, time.monotonic() + self._pending_timeout)
                    )
                elif not accepted:
                    self.trace.increment("mt_partial_admission_rejections")

    def _pump_captions(self) -> None:
        assert self._mt is not None
        for _ in range(8):
            try:
                event = self._mt.get_event(timeout=0)
            except queue.Empty:
                return
            if self._overloaded or self._stop.is_set():
                self.trace.increment("caption_delivery_suppressed")
                continue
            with self._lock:
                is_current_segment = self._displayed_segment_id in {None, event.segment_id}
                is_current_revision = event.revision >= self._displayed_revision
                if is_current_segment and is_current_revision:
                    self._displayed_segment_id = event.segment_id
                    self._displayed_revision = event.revision
            if (
                is_current_segment
                and is_current_revision
                and not self._stop.is_set()
                and not self._overloaded
            ):
                self.trace.record(event.segment_id, event.revision, "service_adopted")
                self.on_caption(event)
            else:
                self.trace.increment("caption_delivery_suppressed")
            correction = self._correction
            with self._lock:
                mode = self._correction_mode
            if (
                correction is not None
                and not self._stop.is_set()
                and not self._overloaded
                and (mode == "live" or (mode == "asynchronous" and event.state == "final"))
            ):
                correction.submit(event)

    def _pump_revisions(self) -> None:
        correction = self._correction
        if correction is None:
            return
        for _ in range(8):
            try:
                event = correction.get_event(timeout=0)
            except queue.Empty:
                return
            if self._overloaded or self._stop.is_set():
                self.trace.increment("revision_delivery_suppressed")
                continue
            with self._lock:
                is_current_segment = self._displayed_segment_id == event.segment_id
                mode = self._correction_mode
                # LLM revision N+1 still refers to ASR/MT revision N. Compare its
                # parent, so a delayed revision cannot overwrite newer source text.
                source_revision = (
                    event.parent_revision if event.parent_revision is not None else event.revision
                )
                is_current_revision = source_revision >= self._displayed_revision
                if is_current_segment and is_current_revision and mode != "off":
                    self._displayed_segment_id = event.segment_id
                    self._displayed_revision = source_revision
            if (
                is_current_segment
                and is_current_revision
                and mode != "off"
                and not self._stop.is_set()
                and not self._overloaded
            ):
                self.trace.record(event.segment_id, event.revision, "service_adopted")
                self.on_caption(event)

    def _shutdown_workers(self) -> None:
        # A failed ASR/MT load must not terminate an independently started recording.
        deadline = self._stop_deadline or (time.monotonic() + 40.0)
        errors: list[str] = []
        try:
            self._audio.set_realtime_enabled(False)
        except Exception as error:
            errors.append(f"audio: {type(error).__name__}")
        if self._asr is not None:
            try:
                # Even a full final queue must not prevent downstream drain/join.
                with suppress(TimeoutError):
                    self._asr.request_stop()
                while time.monotonic() < deadline:
                    if self._mt is not None:
                        self.pump_once()
                    snapshot = self._asr.snapshot()
                    if (
                        not self._asr.worker_alive
                        and snapshot.event_queue_depth == 0
                        and not self._pending_finals
                    ):
                        break
                    time.sleep(0.002)
            except Exception as error:
                errors.append(f"asr: {type(error).__name__}")
                self._asr.abort()
        if self._mt is not None:
            try:
                self._mt.request_stop()
                while time.monotonic() < deadline:
                    self._pump_captions()
                    if not self._mt.worker_alive and self._mt.snapshot().event_queue_depth == 0:
                        break
                    time.sleep(0.002)
            except Exception as error:
                errors.append(f"mt: {type(error).__name__}")
                self._mt.abort()
        for worker in (self._asr, self._mt):
            if worker is not None:
                if worker.worker_alive:
                    worker.abort()
                # Owners stay attached until native calls really return.
                with suppress(TimeoutError):
                    worker.finish_stop(timeout=max(0, deadline - time.monotonic()))
        self._cancel_pending()
        if self._correction is not None:
            try:
                self._correction.stop(timeout=max(0, deadline - time.monotonic()))
            except TimeoutError:
                pass  # worker_alive keeps timeout visible and prevents release.
            except Exception as error:
                errors.append(f"correction: {type(error).__name__}")
        if errors:
            self._shutdown_error = "收尾失败：" + ", ".join(errors)
            self._last_error = self._shutdown_error
            self._set_state("error", self._shutdown_error)

    def _workers_alive(self) -> bool:
        return any(
            worker is not None and worker.worker_alive for worker in (self._asr, self._mt)
        ) or (
            self._correction is not None
            and getattr(self._correction, "_thread", None) is not None
            and self._correction._thread.is_alive()
        )

    def _cancel_pending(self) -> None:
        with self._pending_lock:
            self._finals_aborted += len(self._pending_finals)
            while self._pending_finals:
                event, _target, _deadline = self._pending_finals.popleft()
                self.trace.record(event.segment_id, event.revision, "cancelled")

    def _handle_overload(self, message: str) -> None:
        with self._lock:
            if self._overloaded or self._stop.is_set():
                return
            self._overloaded = True
            self._paused.set()
            self._displayed_segment_id = None
            self._displayed_revision = 0
        try:
            self._audio.set_realtime_enabled(False)
        except Exception as error:
            self._last_error = f"audio pause: {type(error).__name__}"
            self.trace.increment("overload_audio_errors")
            message += f"；音频暂停异常（{type(error).__name__}），请停止后重试"
        self._cancel_pending()
        for worker in (self._asr, self._mt):
            if worker is not None:
                worker.abort()
        if self._correction is not None:
            self._correction.set_enabled(False)
        self.trace.increment("overload_pauses")
        self._set_state("overloaded", message)

    def _try_resume_overload(self) -> None:
        if (
            any(worker is not None and worker.worker_alive for worker in (self._asr, self._mt))
            or self._audio.snapshot().realtime_inflight
        ):
            return
        assert self._asr is not None and self._mt is not None
        old_asr, old_mt = self._asr, self._mt
        self._displayed_segment_id = None
        self._displayed_revision = 0
        self._retire_engines()
        self._asr = StreamingAsrEngine(old_asr.recognizer, old_asr.settings, trace=self.trace)
        self._mt = StreamingTranslationEngine(
            old_mt.registry, old_mt.settings, history=old_mt.history, trace=self.trace
        )
        self._asr.start()
        self._mt.start()
        if self._correction is not None:
            self._correction.set_enabled(self._correction_mode != "off")
        self._overloaded = False
        self._resume_requested.clear()
        self._paused.clear()
        self._audio.set_realtime_enabled(True)
        self._set_state("running", self._audio_status_message(prefix="字幕已恢复 · "))

    def _retire_engines(self) -> None:
        for name, worker in (("asr", self._asr), ("mt", self._mt)):
            if worker is None:
                continue
            snapshot = worker.snapshot()
            for field in (
                "final_requests_added",
                "final_submit_rejections",
                "final_requests_aborted",
                "final_outputs_rejected",
                "final_events_aborted",
                "stale_results_dropped",
                "history_errors",
            ):
                key = f"{name}_{field}"
                self._retired_counts[key] = self._retired_counts.get(key, 0) + getattr(
                    snapshot, field, 0
                )
        self._history_errors_reported = 0

    def _set_state(self, state: str, message: str) -> None:
        with self._lock:
            self._state = state
        self.on_status(state, message)

    def _notify(self, message: str) -> None:
        with self._lock:
            state = self._state
        self.on_status(state, message)

    def _handle_correction_status(self, state: str, message: str) -> None:
        with self._lock:
            if self._correction_mode == "off" and state == "ready":
                return
            self._correction_state = state
            self._correction_error = message if state == "error" else None
        self.on_correction_status(state, message)

    def _set_correction_state(self, state: str, message: str) -> None:
        with self._lock:
            self._correction_state = state
            self._correction_error = message if state == "error" else None
        self.on_correction_status(state, message)

    def _correction_scope(self) -> ProcessingScope | None:
        if self.settings.correction.provider == "local":
            return "local"
        if self.settings.correction.provider == "openai_compatible":
            return "cloud"
        return None

    def _audio_status_message(self, *, prefix: str = "") -> str:
        audio = self.settings.audio
        if audio.source == "microphone":
            label = "正在监听麦克风"
        elif audio.source == "process":
            name = audio.process_name.strip() or f"PID {audio.process_id}"
            label = f"正在监听进程 {name}"
        else:
            label = "正在监听系统音频"
        return prefix + label


def _audio_selector(audio: AudioSettings) -> str:
    if audio.source == "microphone":
        return audio.microphone_device
    if audio.source == "process":
        return f"process:{audio.process_id}" if audio.process_id else audio.process_name
    return audio.device
