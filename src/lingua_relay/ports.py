from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

from lingua_relay.events import CaptionEvent

if TYPE_CHECKING:
    import numpy as np

    from lingua_relay.asr.types import AsrResult
    from lingua_relay.audio.types import AudioChunk
    from lingua_relay.mt.types import TranslationResult


class AudioSource(Protocol):
    def start(self) -> None: ...

    def stop(self, timeout: float = 5.0) -> None: ...

    def get_chunk(self, timeout: float | None = None) -> AudioChunk: ...


class SpeechRecognizer(Protocol):
    def transcribe(
        self, samples: np.ndarray, *, language: str, vad_filter: bool | None = None
    ) -> AsrResult: ...


class Translator(Protocol):
    def translate(self, text: str, *, source: str, target: str) -> TranslationResult: ...


class CaptionReviser(Protocol):
    def revise(self, event: CaptionEvent, context: tuple[CaptionEvent, ...]) -> CaptionEvent: ...


class CaptionSink(Protocol):
    def publish(self, event: CaptionEvent) -> None: ...
