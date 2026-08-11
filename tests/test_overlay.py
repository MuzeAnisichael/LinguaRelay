from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from lingua_relay.config import OverlaySettings  # noqa: E402
from lingua_relay.events import CaptionEvent  # noqa: E402
from lingua_relay.ui.overlay import CaptionOverlay  # noqa: E402


def _event(translated: str) -> CaptionEvent:
    return CaptionEvent(
        source_text="source survives",
        translated_text=translated,
        source_language="en",
        target_language="zh",
        state="final",
        started_at_ms=0,
    )


def test_translated_only_and_bilingual_modes() -> None:
    app = QApplication.instance() or QApplication([])
    overlay = CaptionOverlay(OverlaySettings(display_mode="translated"))
    overlay.publish(_event("译文"))
    app.processEvents()
    assert overlay.source.isHidden()
    assert overlay.translation.text() == "译文"

    overlay.set_display_mode("bilingual")
    overlay.publish(_event("译文"))
    app.processEvents()
    assert not overlay.source.isHidden()
    assert overlay.source.text() == "source survives"


def test_translated_only_falls_back_to_source_on_failure() -> None:
    app = QApplication.instance() or QApplication([])
    overlay = CaptionOverlay(OverlaySettings(display_mode="translated"))
    overlay.publish(_event(""))
    app.processEvents()
    assert overlay.translation.text() == "source survives"

    overlay.set_display_mode("bilingual")
    app.processEvents()
    assert overlay.source.text() == "source survives"
    assert overlay.translation.text() == ""
