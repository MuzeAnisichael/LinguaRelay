"""R-UI-01 / K-002: acknowledge widget updates and reject queued old deliveries."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from lingua_relay.config import Settings  # noqa: E402
from lingua_relay.events import CaptionEvent  # noqa: E402
from lingua_relay.service import RealtimeCaptionService  # noqa: E402
from lingua_relay.ui.app import DesktopController  # noqa: E402
from lingua_relay.ui.overlay import CaptionOverlay  # noqa: E402


def test_controller_acknowledges_actual_widget_update_but_not_late_queued_caption():
    app = QApplication.instance() or QApplication([])
    controller = DesktopController.__new__(DesktopController)
    controller.service = RealtimeCaptionService(Settings(), on_caption=lambda _event: None)
    controller.overlay = CaptionOverlay(Settings().overlay)
    event = CaptionEvent("hello", "你好", "en", "zh", "final", 0, segment_id="current", revision=1)
    controller.service._displayed_segment_id = "current"
    controller.service._displayed_revision = 1
    try:
        controller._publish_caption(event)
        assert controller.overlay.translation.text() == "你好"
        snapshot = controller.service.telemetry_snapshot()
        assert snapshot["outcomes"]["ui_updated"] == 1
        controller.service._stop.set()
        controller._publish_caption(
            CaptionEvent("old", "旧结果", "en", "zh", "final", 0, segment_id="current", revision=2)
        )
        assert controller.overlay.translation.text() == "你好"
        assert controller.service.telemetry_snapshot()["outcomes"]["ui_updated"] == 1
        app.processEvents()
    finally:
        controller.overlay.close()


def test_controller_rejects_late_running_status_after_overload():
    app = QApplication.instance() or QApplication([])
    controller = DesktopController.__new__(DesktopController)
    controller.service = RealtimeCaptionService(Settings(), on_caption=lambda _event: None)
    controller.overlay = CaptionOverlay(Settings().overlay)
    controller.service._state = "overloaded"
    try:
        controller._publish_status("overloaded", "字幕过载，录制继续")
        controller._publish_status("running", "旧运行状态")
        assert "字幕过载" in controller.overlay.status.text()
        assert controller.overlay.pause_button.text() == "▶"
        app.processEvents()
    finally:
        controller.overlay.close()
