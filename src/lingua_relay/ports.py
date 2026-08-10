from __future__ import annotations

from collections.abc import Iterable
from typing import Protocol

from lingua_relay.events import CaptionEvent


class AudioSource(Protocol):
    def chunks(self) -> Iterable[bytes]: ...


class SpeechRecognizer(Protocol):
    def transcribe(self, pcm: bytes, *, language: str) -> str: ...


class Translator(Protocol):
    def translate(self, text: str, *, source: str, target: str) -> str: ...


class CaptionReviser(Protocol):
    def revise(self, event: CaptionEvent, context: tuple[CaptionEvent, ...]) -> CaptionEvent: ...


class CaptionSink(Protocol):
    def publish(self, event: CaptionEvent) -> None: ...
