from __future__ import annotations

import threading
from pathlib import Path

from lingua_relay.asr.types import AsrEvent
from lingua_relay.config import TranslationSettings
from lingua_relay.history import JsonlHistory
from lingua_relay.mt.streaming import StreamingTranslationEngine
from lingua_relay.mt.types import TranslationResult
from lingua_relay.translation import TranslationRouteRegistry


class FakeTranslator:
    def translate(self, text: str, *, source: str, target: str) -> TranslationResult:
        return TranslationResult(f"{target}:{text}", source, target, 4.5)


class BrokenTranslator:
    def translate(self, text: str, *, source: str, target: str) -> TranslationResult:
        raise RuntimeError("offline")


def _asr_event(*, state: str = "final", revision: int = 1, text: str = "hello") -> AsrEvent:
    return AsrEvent(
        text=text,
        stable_text=text,
        unstable_text="",
        newly_stable_text="hello",
        language="en",
        state=state,  # type: ignore[arg-type]
        segment_id="segment-1",
        revision=revision,
        started_at_ms=10,
        ended_at_ms=20,
        emitted_at_ns=1,
        timings_ms={"asr": 7.0},
    )


def _registry(translator: object) -> TranslationRouteRegistry:
    registry = TranslationRouteRegistry()
    registry.register("en", "zh", "fake", translator)  # type: ignore[arg-type]
    return registry


def test_final_translation_is_emitted_and_written_to_history(tmp_path: Path) -> None:
    history = JsonlHistory(tmp_path / "history.jsonl")
    engine = StreamingTranslationEngine(
        _registry(FakeTranslator()), TranslationSettings(), history=history
    )
    engine.start()
    engine.submit(_asr_event(), target="zh")

    caption = engine.get_event(timeout=2)
    engine.stop()

    assert caption.translated_text == "zh:hello"
    assert caption.timings_ms["translation"] == 4.5
    assert tuple(history.read_all())[0]["translated_text"] == "zh:hello"


def test_translation_failure_keeps_source_for_overlay_fallback() -> None:
    engine = StreamingTranslationEngine(_registry(BrokenTranslator()), TranslationSettings())
    engine.start()
    engine.submit(_asr_event(), target="zh")

    caption = engine.get_event(timeout=2)
    engine.stop()

    assert caption.source_text == "hello"
    assert caption.translated_text == ""
    assert caption.error == "RuntimeError: offline"
    assert engine.snapshot().translation_errors == 1


class BlockingTranslator:
    def __init__(self) -> None:
        self.started = threading.Event()
        self.release = threading.Event()
        self.calls = 0

    def translate(self, text: str, *, source: str, target: str) -> TranslationResult:
        self.calls += 1
        if self.calls == 1:
            self.started.set()
            assert self.release.wait(2)
        return TranslationResult(f"{target}:{text}", source, target, 1.0)


def test_completed_partial_translation_is_shown_while_newer_text_waits() -> None:
    translator = BlockingTranslator()
    engine = StreamingTranslationEngine(_registry(translator), TranslationSettings())
    engine.start()
    engine.submit(_asr_event(state="partial", revision=1, text="first"), target="zh")
    assert translator.started.wait(2)
    engine.submit(_asr_event(state="partial", revision=2, text="second"), target="zh")
    translator.release.set()

    first = engine.get_event(timeout=2)
    engine.stop()

    assert first.revision == 1
    assert first.translated_text == "zh:first"
