import queue
import time

import pytest

from lingua_relay.asr.types import AsrEvent
from lingua_relay.config import CorrectionSettings, Settings
from lingua_relay.events import CaptionEvent
from lingua_relay.service import RealtimeCaptionService


def test_service_switches_configured_correction_modes_without_starting_models() -> None:
    statuses: list[tuple[str, str]] = []
    service = RealtimeCaptionService(
        Settings(correction=CorrectionSettings(provider="local", model="mock")),
        on_caption=lambda _event: None,
        on_correction_status=lambda state, message: statuses.append((state, message)),
    )

    service.set_correction_mode("asynchronous")
    assert service.snapshot().correction_mode == "asynchronous"
    assert service.snapshot().correction_scope == "local"
    assert "本地处理" in statuses[-1][1]

    service.set_correction_mode("off")
    assert service.snapshot().correction_mode == "off"


def test_service_rejects_enabling_unconfigured_provider() -> None:
    service = RealtimeCaptionService(Settings(), on_caption=lambda _event: None)

    with pytest.raises(ValueError, match="provider"):
        service.set_correction_mode("live")


def test_service_does_not_replace_new_caption_with_older_revision() -> None:
    published: list[CaptionEvent] = []
    service = RealtimeCaptionService(
        Settings(
            correction=CorrectionSettings(mode="asynchronous", provider="local", model="mock")
        ),
        on_caption=published.append,
    )
    old_revision = CaptionEvent(
        "old source",
        "old revised",
        "en",
        "zh",
        "revised",
        0,
        segment_id="old",
        revision=1,
    )

    class CorrectionQueue:
        def __init__(self) -> None:
            self.returned = False

        def get_event(self, timeout: float = 0) -> CaptionEvent:
            if self.returned:
                raise queue.Empty
            self.returned = True
            return old_revision

    service._correction = CorrectionQueue()  # type: ignore[assignment]
    service._displayed_segment_id = "new"

    service._pump_revisions()

    assert published == []


def test_service_publishes_transcript_before_submitting_translation() -> None:
    transcripts: list[tuple[AsrEvent, str]] = []
    service = RealtimeCaptionService(
        Settings(),
        on_caption=lambda _event: None,
        on_transcript=lambda event, target: transcripts.append((event, target)),
    )
    event = AsrEvent(
        "hello",
        "hello",
        "",
        "hello",
        "en",
        "partial",
        "segment",
        1,
        0,
        320,
        time.monotonic_ns(),
    )

    class AsrQueue:
        def __init__(self) -> None:
            self.returned = False

        def get_event(self, timeout: float = 0) -> AsrEvent:
            if self.returned:
                raise queue.Empty
            self.returned = True
            return event

    class TranslationQueue:
        def __init__(self) -> None:
            self.submitted: list[tuple[AsrEvent, str]] = []

        def submit(self, submitted: AsrEvent, *, target: str) -> None:
            assert transcripts == [(event, "zh")]
            self.submitted.append((submitted, target))

    service._asr = AsrQueue()  # type: ignore[assignment]
    translation = TranslationQueue()
    service._mt = translation  # type: ignore[assignment]

    service._pump_asr()

    assert translation.submitted == [(event, "zh")]


def test_older_translation_does_not_overwrite_a_newer_transcript() -> None:
    published: list[CaptionEvent] = []
    service = RealtimeCaptionService(Settings(), on_caption=published.append)
    old_caption = CaptionEvent(
        "old source",
        "old translation",
        "en",
        "zh",
        "final",
        0,
        segment_id="old",
    )

    class TranslationEvents:
        def __init__(self) -> None:
            self.returned = False

        def get_event(self, timeout: float = 0) -> CaptionEvent:
            if self.returned:
                raise queue.Empty
            self.returned = True
            return old_caption

    service._mt = TranslationEvents()  # type: ignore[assignment]
    service._displayed_segment_id = "new"

    service._pump_captions()

    assert published == []
