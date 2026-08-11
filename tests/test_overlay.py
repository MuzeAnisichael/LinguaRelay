from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint, QRect  # noqa: E402
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


def test_revised_caption_displays_local_or_cloud_scope() -> None:
    app = QApplication.instance() or QApplication([])
    overlay = CaptionOverlay(OverlaySettings())
    event = CaptionEvent(
        source_text="source",
        translated_text="revised",
        source_language="en",
        target_language="zh",
        state="revised",
        started_at_ms=0,
        revision=1,
        parent_revision=0,
        original_translation="fast",
        processing_scope="cloud",
    )

    overlay.publish(event)
    app.processEvents()

    assert "云端修正" in overlay.status.text()
    assert "v1" in overlay.status.text()


def test_caption_updates_preserve_user_geometry() -> None:
    app = QApplication.instance() or QApplication([])
    overlay = CaptionOverlay(OverlaySettings(width=640, height=180, x=20, y=30))
    before = overlay.geometry()

    overlay.publish(_event("一段很长的译文 " * 80))
    app.processEvents()

    assert overlay.geometry() == before


def test_overlay_detects_corners_and_enforces_minimum_resize() -> None:
    app = QApplication.instance() or QApplication([])
    overlay = CaptionOverlay(OverlaySettings(width=640, height=180, x=20, y=30))
    app.processEvents()

    assert overlay.resize_edges_at(QPoint(0, 0)) == overlay._LEFT | overlay._TOP
    assert overlay.resize_edges_at(QPoint(overlay.width() - 1, 90)) == overlay._RIGHT

    overlay._resize_edges = overlay._LEFT | overlay._TOP
    resized = overlay._resized_geometry(QRect(20, 30, 640, 180), QPoint(900, 900))
    assert resized.width() == overlay.minimumWidth()
    assert resized.height() == overlay.minimumHeight()
