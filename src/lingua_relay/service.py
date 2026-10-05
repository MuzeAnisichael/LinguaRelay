from __future__ import annotations

import queue
import threading
from collections.abc import Callable
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
    ) -> None:
        self.settings = settings
        self.on_caption = on_caption
        self.on_transcript = on_transcript or (lambda _event, _target: None)
        self.on_status = on_status or (lambda _state, _message: None)
        self.on_correction_status = on_correction_status or (lambda _state, _message: None)
        self.on_recording = on_recording or (lambda _state, _message, _project_id: None)
        self.model_root = Path(model_root)
        self.resource_dir = Path(resource_dir)
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
        self._audio = AudioCaptureRuntime(
            settings.audio,
            resource_dir=self.resource_dir,
            on_chunk=self._submit_audio,
            on_message=self._notify,
            on_recording=self.on_recording,
        )

    def start(self, *, paused: bool = False) -> None:
        if self._thread is not None and self._thread.is_alive():
            if paused:
                self.pause()
            else:
                self.resume()
            return
        self._stop.clear()
        self._audio.prepare()
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
            self._asr.flush()
        if self._state in {"ready", "running", "paused"}:
            self._set_state("paused", "已暂停")

    @property
    def paused(self) -> bool:
        return self._paused.is_set()

    def resume(self) -> None:
        self._paused.clear()
        if self._state in {"ready", "running", "paused"}:
            self._audio.set_realtime_enabled(True)
            self._set_state("running", self._audio_status_message())

    def set_route(self, source: str, target: str) -> None:
        if source == target:
            raise ValueError("source and target languages must differ")
        with self._lock:
            source_changed = source != self._source
            self._source = source
            self._target = target
        if source_changed and self._asr is not None:
            self._asr.flush()
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
        self._stop.set()
        if self._correction is not None:
            self._correction.set_enabled(False)
        self._audio.stop()
        thread = self._thread
        if thread is not None:
            thread.join(timeout)
            if thread.is_alive():
                raise TimeoutError("caption service did not stop in time")
        self._thread = None

    def release_resources(self) -> None:
        """Release model owners after the worker has stopped for model removal."""
        thread = self._thread
        if thread is not None and thread.is_alive():
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
            self._asr = StreamingAsrEngine(recognizer, self.settings.asr)
            self._mt = StreamingTranslationEngine(
                build_m2m100_registry(translator), translation_settings, history=history
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
                self._pump_asr()
                self._pump_captions()
                self._pump_revisions()
                self._stop.wait(0.01)
        except Exception as error:
            with self._lock:
                self._last_error = f"{type(error).__name__}: {error}"
            self._set_state("error", self._last_error)
        finally:
            self._shutdown_workers()
            if self._state != "error":
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
            asr.submit_chunk(chunk, language=source)

    def _pump_asr(self) -> None:
        assert self._asr is not None and self._mt is not None
        while True:
            try:
                event = self._asr.get_event(timeout=0)
            except queue.Empty:
                return
            with self._lock:
                target = self._target
                self._displayed_segment_id = event.segment_id
                self._displayed_revision = event.revision
            self.on_transcript(event, target)
            self._mt.submit(event, target=target)

    def _pump_captions(self) -> None:
        assert self._mt is not None
        while True:
            try:
                event = self._mt.get_event(timeout=0)
            except queue.Empty:
                return
            with self._lock:
                is_current_segment = self._displayed_segment_id in {None, event.segment_id}
                is_current_revision = event.revision >= self._displayed_revision
                if is_current_segment and is_current_revision:
                    self._displayed_segment_id = event.segment_id
                    self._displayed_revision = event.revision
            if is_current_segment and is_current_revision:
                self.on_caption(event)
            correction = self._correction
            with self._lock:
                mode = self._correction_mode
            if correction is not None and (
                mode == "live" or (mode == "asynchronous" and event.state == "final")
            ):
                correction.submit(event)

    def _pump_revisions(self) -> None:
        correction = self._correction
        if correction is None:
            return
        while True:
            try:
                event = correction.get_event(timeout=0)
            except queue.Empty:
                return
            with self._lock:
                is_current_segment = self._displayed_segment_id in {
                    None,
                    event.segment_id,
                }
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
            if is_current_segment and is_current_revision and mode != "off":
                self.on_caption(event)

    def _shutdown_workers(self) -> None:
        # A failed ASR/MT load must not terminate an independently started recording.
        self._audio.set_realtime_enabled(False)
        if self._asr is not None:
            self._asr.stop()
            if self._mt is not None:
                self._pump_asr()
        if self._mt is not None:
            self._mt.stop()
            self._pump_captions()
        if self._correction is not None:
            self._correction.stop()
            self._pump_revisions()

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
