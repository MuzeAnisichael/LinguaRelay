from __future__ import annotations

import queue
import threading
from collections.abc import Callable
from dataclasses import dataclass, replace
from pathlib import Path

from lingua_relay.asr import FasterWhisperRecognizer, StreamingAsrEngine
from lingua_relay.audio import WasapiLoopbackCapture
from lingua_relay.config import Settings
from lingua_relay.events import CaptionEvent
from lingua_relay.history import JsonlHistory
from lingua_relay.mt import M2M100Translator, StreamingTranslationEngine
from lingua_relay.translation import build_m2m100_registry


@dataclass(frozen=True, slots=True)
class ServiceSnapshot:
    state: str
    source_language: str
    target_language: str
    audio_device: str
    last_error: str | None


class RealtimeCaptionService:
    """Own the M1 -> M2 -> M3 pipeline outside the Qt thread."""

    def __init__(
        self,
        settings: Settings,
        *,
        on_caption: Callable[[CaptionEvent], None],
        on_status: Callable[[str, str], None] | None = None,
        model_root: str | Path = "models",
    ) -> None:
        self.settings = settings
        self.on_caption = on_caption
        self.on_status = on_status or (lambda _state, _message: None)
        self.model_root = Path(model_root)
        self._source = settings.app.source_language
        self._target = settings.app.target_language
        self._device = settings.audio.device
        self._state = "stopped"
        self._last_error: str | None = None
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._paused = threading.Event()
        self._thread: threading.Thread | None = None
        self._capture: WasapiLoopbackCapture | None = None
        self._asr: StreamingAsrEngine | None = None
        self._mt: StreamingTranslationEngine | None = None

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            self.resume()
            return
        self._stop.clear()
        self._paused.clear()
        self._thread = threading.Thread(target=self._run, name="lingua-relay-service", daemon=True)
        self._thread.start()

    def pause(self) -> None:
        self._paused.set()
        capture = self._capture
        if capture is not None:
            capture.stop()
        if self._asr is not None:
            self._asr.flush()
        self._set_state("paused", "已暂停")

    def resume(self) -> None:
        self._paused.clear()
        capture = self._capture
        if capture is not None:
            capture.start()
        self._set_state("running", "正在监听系统音频")

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

    def set_audio_device(self, device: str) -> None:
        with self._lock:
            self._device = device
            old_capture = self._capture
            if old_capture is not None:
                old_capture.stop()
            self._capture = WasapiLoopbackCapture(replace(self.settings.audio, device=device))
            if not self._paused.is_set():
                self._capture.start()
        self._notify("音频设备已切换")

    def stop(self, timeout: float = 40.0) -> None:
        self._stop.set()
        if self._capture is not None:
            self._capture.stop()
        thread = self._thread
        if thread is not None:
            thread.join(timeout)
            if thread.is_alive():
                raise TimeoutError("caption service did not stop in time")
        self._thread = None

    def snapshot(self) -> ServiceSnapshot:
        with self._lock:
            return ServiceSnapshot(
                self._state,
                self._source,
                self._target,
                self._device,
                self._last_error,
            )

    def _run(self) -> None:
        try:
            self._set_state("loading", "正在加载并预热语音与翻译模型…")
            recognizer = FasterWhisperRecognizer(self.settings.asr, download_root=self.model_root)
            recognizer.load()
            translation_settings = self.settings.translation
            translator = M2M100Translator(translation_settings)
            translator.load()
            history = (
                JsonlHistory(self.settings.app.history_path)
                if self.settings.app.history_enabled
                else None
            )
            self._asr = StreamingAsrEngine(recognizer, self.settings.asr)
            self._mt = StreamingTranslationEngine(
                build_m2m100_registry(translator), translation_settings, history=history
            )
            self._capture = WasapiLoopbackCapture(replace(self.settings.audio, device=self._device))
            self._asr.start()
            self._mt.start()
            if self._paused.is_set():
                self._set_state("paused", "已暂停")
            else:
                self._capture.start()
                self._set_state("running", "正在监听系统音频")
            while not self._stop.is_set():
                if not self._paused.is_set():
                    self._pump_audio()
                else:
                    self._stop.wait(0.05)
                self._pump_asr()
                self._pump_captions()
        except Exception as error:
            with self._lock:
                self._last_error = f"{type(error).__name__}: {error}"
            self._set_state("error", self._last_error)
        finally:
            self._shutdown_workers()
            if self._state != "error":
                self._set_state("stopped", "已停止")

    def _pump_audio(self) -> None:
        assert self._capture is not None and self._asr is not None
        try:
            chunk = self._capture.get_chunk(timeout=0.05)
        except queue.Empty:
            return
        with self._lock:
            source = self._source
        self._asr.submit_chunk(chunk, language=source)

    def _pump_asr(self) -> None:
        assert self._asr is not None and self._mt is not None
        while True:
            try:
                event = self._asr.get_event(timeout=0)
            except queue.Empty:
                return
            with self._lock:
                target = self._target
            self._mt.submit(event, target=target)

    def _pump_captions(self) -> None:
        assert self._mt is not None
        while True:
            try:
                self.on_caption(self._mt.get_event(timeout=0))
            except queue.Empty:
                return

    def _shutdown_workers(self) -> None:
        if self._capture is not None:
            self._capture.stop()
        if self._asr is not None:
            self._asr.stop()
            if self._mt is not None:
                self._pump_asr()
        if self._mt is not None:
            self._mt.stop()
            self._pump_captions()

    def _set_state(self, state: str, message: str) -> None:
        with self._lock:
            self._state = state
        self.on_status(state, message)

    def _notify(self, message: str) -> None:
        with self._lock:
            state = self._state
        self.on_status(state, message)
