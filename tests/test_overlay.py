from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint, QRect  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from lingua_relay.asr.types import AsrEvent  # noqa: E402
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


def test_ready_status_replaces_loading_placeholder() -> None:
    app = QApplication.instance() or QApplication([])
    overlay = CaptionOverlay(OverlaySettings())

    overlay.set_status("running", "正在监听系统音频")
    app.processEvents()

    assert "模型已就绪" in overlay.translation.text()


def test_transcript_is_visible_before_translation_finishes() -> None:
    app = QApplication.instance() or QApplication([])
    overlay = CaptionOverlay(OverlaySettings(display_mode="bilingual"))
    event = AsrEvent(
        text="recognized immediately",
        stable_text="recognized",
        unstable_text="immediately",
        newly_stable_text="recognized",
        language="en",
        state="partial",
        segment_id="segment-live",
        revision=1,
        started_at_ms=0,
        ended_at_ms=320,
        emitted_at_ns=1,
    )

    overlay.publish_transcript(event, "zh")
    app.processEvents()

    assert overlay.source.text() == "recognized immediately"
    assert overlay.translation.text() == "正在翻译…"
    assert "正在识别并翻译" in overlay.status.text()


def test_caption_is_cleared_after_user_retention_time() -> None:
    app = QApplication.instance() or QApplication([])
    overlay = CaptionOverlay(OverlaySettings(retention_seconds=0.1))
    overlay.publish(_event("短暂显示"))

    QTest.qWait(150)
    app.processEvents()

    assert overlay.source.text() == ""
    assert overlay.translation.text() == ""
    assert "等待系统音频" in overlay.status.text()


def test_overlay_applies_user_fonts_colors_and_status_visibility() -> None:
    app = QApplication.instance() or QApplication([])
    overlay = CaptionOverlay(
        OverlaySettings(
            source_font_family="Arial",
            source_font_size=15,
            source_color="#112233",
            translation_font_family="Arial",
            translation_font_size=24,
            translation_color="#59D395",
            background_color="#20242C",
            background_opacity=0.7,
            status_visible=False,
        )
    )
    overlay.publish(_event("自定义颜色"))
    app.processEvents()

    assert overlay.source.font().pointSize() == 15
    assert overlay.translation.font().pointSize() == 24
    assert "89, 211, 149" in overlay.translation.styleSheet()
    assert "32, 36, 44" in overlay.frame.styleSheet()
    assert overlay.status.isHidden()


def test_overlay_exposes_compact_controls_and_hides_them_in_click_through_mode() -> None:
    app = QApplication.instance() or QApplication([])
    overlay = CaptionOverlay(OverlaySettings())
    requested: list[str] = []
    overlay.pause_requested.connect(lambda: requested.append("pause"))
    overlay.display_mode_requested.connect(lambda: requested.append("display"))
    overlay.history_requested.connect(lambda: requested.append("history"))
    overlay.record_requested.connect(lambda: requested.append("record"))
    overlay.workbench_requested.connect(lambda: requested.append("workbench"))
    overlay.settings_requested.connect(lambda: requested.append("settings"))

    overlay.pause_button.click()
    overlay.display_button.click()
    overlay.record_button.click()
    overlay.workbench_button.click()
    overlay.history_button.click()
    overlay.settings_button.click()
    app.processEvents()

    assert requested == ["pause", "display", "record", "workbench", "history", "settings"]
    overlay.set_click_through(True)
    assert all(button.isHidden() for button in overlay.control_buttons)


def test_overlay_recording_controls_show_pause_and_stop_state() -> None:
    app = QApplication.instance() or QApplication([])
    overlay = CaptionOverlay(OverlaySettings())
    overlay.set_recording_state("recording")
    app.processEvents()
    assert overlay.record_button.text() == "■"
    assert not overlay.record_pause_button.isHidden()

    overlay.set_recording_state("paused")
    assert overlay.record_pause_button.text() == "▶"
    overlay.set_recording_state("stopped")
    assert overlay.record_button.text() == "●"
    assert overlay.record_pause_button.isHidden()
