from __future__ import annotations

import sys
from dataclasses import replace

from PySide6.QtCore import QEvent, QPoint, QRect, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QMouseEvent, QShowEvent
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from lingua_relay.asr.types import AsrEvent
from lingua_relay.config import OverlaySettings, Settings
from lingua_relay.events import CaptionEvent


class CaptionOverlay(QWidget):
    """Small always-on-top caption surface; model work never runs here."""

    geometry_changed = Signal(int, int, int, int)
    pause_requested = Signal()
    display_mode_requested = Signal()
    history_requested = Signal()
    record_requested = Signal()
    recording_pause_requested = Signal()
    workbench_requested = Signal()
    settings_requested = Signal()
    hide_requested = Signal()

    _LEFT = 1
    _TOP = 2
    _RIGHT = 4
    _BOTTOM = 8
    _RESIZE_MARGIN = 9

    def __init__(self, settings: OverlaySettings) -> None:
        super().__init__()
        self.settings = settings
        self._last_event: CaptionEvent | None = None
        self._active_segment_id: str | None = None
        self._press_global: QPoint | None = None
        self._press_geometry: QRect | None = None
        self._resize_edges = 0
        self._positioned = False
        self._retention_timer = QTimer(self)
        self._retention_timer.setSingleShot(True)
        self._retention_timer.timeout.connect(self.clear_caption)
        self._build_window()
        self._build_content()
        self.apply_settings(settings)

    def _build_window(self) -> None:
        self.setObjectName("captionOverlay")
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setWindowTitle("LinguaRelay")

    def _build_content(self) -> None:
        self.frame = QFrame(self)
        self.frame.setObjectName("captionFrame")
        self.frame.setMouseTracking(True)
        self.frame.installEventFilter(self)
        self.status = QLabel("LINGUARELAY · 正在准备")
        self.status.setToolTip("拖动窗口移动；拖动边缘或四角缩放")
        self.status.setFont(QFont("Segoe UI", 9, QFont.Weight.DemiBold))
        self.status.setStyleSheet("color: #77d6a5;")
        self.pause_button = self._tool_button("Ⅱ", "暂停 / 继续实时字幕")
        self.pause_button.clicked.connect(self.pause_requested.emit)
        self.record_button = self._tool_button("●", "开始录制当前音频源")
        self.record_button.clicked.connect(self.record_requested.emit)
        self.record_pause_button = self._tool_button("Ⅱ", "暂停录制")
        self.record_pause_button.clicked.connect(self.recording_pause_requested.emit)
        self.record_pause_button.hide()
        self.display_button = self._tool_button("双", "切换仅译文 / 双语显示")
        self.display_button.clicked.connect(self.display_mode_requested.emit)
        self.workbench_button = self._tool_button("辑", "打开录制与离线工作台")
        self.workbench_button.clicked.connect(self.workbench_requested.emit)
        self.history_button = self._tool_button("历", "打开字幕历史")
        self.history_button.clicked.connect(self.history_requested.emit)
        self.settings_button = self._tool_button("设", "打开用户设置")
        self.settings_button.clicked.connect(self.settings_requested.emit)
        self.hide_button = self._tool_button("×", "隐藏悬浮窗（Ctrl+Alt+L 恢复）")
        self.hide_button.clicked.connect(self.hide_requested.emit)
        self.control_buttons = (
            self.pause_button,
            self.record_button,
            self.record_pause_button,
            self.display_button,
            self.workbench_button,
            self.history_button,
            self.settings_button,
            self.hide_button,
        )
        header = QWidget()
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(3)
        header_layout.addWidget(self.status, 1)
        for button in self.control_buttons:
            header_layout.addWidget(button)
        self.source = QLabel("")
        self.source.setWordWrap(True)
        self.translation = QLabel("正在加载模型…")
        self.translation.setWordWrap(True)
        for label in (self.status, self.source, self.translation):
            label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

        content = QVBoxLayout(self.frame)
        content.setContentsMargins(22, 14, 22, 15)
        content.setSpacing(5)
        content.addWidget(header)
        content.addWidget(self.source)
        content.addWidget(self.translation)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.addWidget(self.frame)

    def apply_settings(self, settings: OverlaySettings) -> None:
        previous_geometry = self.geometry() if self._positioned else None
        self.settings = settings
        flags = (
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        if settings.click_through:
            flags |= Qt.WindowType.WindowTransparentForInput
        visible = self.isVisible()
        self.setWindowFlags(flags)
        self.setWindowOpacity(settings.opacity)
        self._apply_frame_style()
        self.setMinimumSize(360, 96)
        self.resize(settings.width, settings.height)
        self.source.setFont(QFont(settings.source_font_family, settings.source_font_size))
        self.translation.setFont(
            QFont(
                settings.translation_font_family,
                settings.translation_font_size,
                QFont.Weight.DemiBold,
            )
        )
        self.status.setVisible(settings.status_visible)
        self.display_button.setText("双" if settings.display_mode == "bilingual" else "译")
        for button in self.control_buttons:
            button.setVisible(not settings.click_through)
        self.record_pause_button.setVisible(
            not settings.click_through and self.record_button.property("recording") is True
        )
        self.source.setVisible(settings.display_mode == "bilingual")
        if self._last_event is not None:
            self.publish(self._last_event)
        elif settings.retention_seconds == 0:
            self._retention_timer.stop()
        if settings.x is not None and settings.y is not None:
            self.move(settings.x, settings.y)
            self._keep_on_screen()
            self._positioned = True
        elif previous_geometry is not None:
            self.setGeometry(previous_geometry)
            self._keep_on_screen()
        else:
            self.reposition()
        if visible:
            self.show()

    def set_display_mode(self, mode: str) -> None:
        if mode not in {"translated", "bilingual"}:
            raise ValueError("display mode must be translated or bilingual")
        self.apply_settings(replace(self.settings, display_mode=mode))
        if self._last_event is not None:
            self.publish(self._last_event)

    def set_click_through(self, enabled: bool) -> None:
        self.apply_settings(replace(self.settings, click_through=enabled))

    def set_paused(self, paused: bool) -> None:
        self.pause_button.setText("▶" if paused else "Ⅱ")
        self.pause_button.setToolTip("继续实时字幕" if paused else "暂停实时字幕")

    def set_recording_state(self, state: str) -> None:
        active = state in {"recording", "paused"}
        paused = state == "paused"
        self.record_button.setProperty("recording", active)
        self.record_button.setText("■" if active else "●")
        self.record_button.setToolTip("结束录制并开始后期处理" if active else "开始录制当前音频源")
        self.record_button.setStyleSheet(
            self._button_style("#ff6577" if active else "rgba(255,255,255,190)")
        )
        self.record_pause_button.setVisible(active and not self.settings.click_through)
        self.record_pause_button.setText("▶" if paused else "Ⅱ")
        self.record_pause_button.setToolTip("继续录制" if paused else "暂停录制")

    def set_status(self, state: str, message: str) -> None:
        colors = {
            "running": "#77d6a5",
            "ready": "#77d6a5",
            "paused": "#f2c66d",
            "stopped": "#b8c1d1",
            "stopping": "#f2c66d",
            "loading": "#f2c66d",
            "processing": "#70b7ff",
            "warning": "#f2c66d",
            "rate_limited": "#f2c66d",
            "circuit_open": "#f2c66d",
            "error": "#ff7d8b",
        }
        self.status.setStyleSheet(f"color: {colors.get(state, '#b8c1d1')};")
        self.status.setText(f"LINGUARELAY · {message}")
        if self._last_event is None:
            if state == "loading":
                self.translation.setText(message)
                self.translation.setStyleSheet(
                    self._text_style(self.settings.translation_color, 0.7)
                )
            elif state in {"ready", "running"}:
                self.translation.setText("模型已就绪，等待系统音频…")
                self.translation.setStyleSheet(
                    self._text_style(self.settings.translation_color, 0.76)
                )

    @staticmethod
    def _tool_button(text: str, tooltip: str) -> QToolButton:
        button = QToolButton()
        button.setText(text)
        button.setToolTip(tooltip)
        button.setFixedSize(26, 24)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.setStyleSheet(CaptionOverlay._button_style("rgba(255,255,255,190)"))
        return button

    @staticmethod
    def _button_style(color: str) -> str:
        return (
            f"QToolButton {{ color: {color}; background: rgba(255,255,255,14); "
            "border: 0; border-radius: 5px; font-weight: 600; }"
            "QToolButton:hover { background: rgba(255,255,255,35); color: white; }"
            "QToolButton:pressed { background: rgba(112,183,255,80); }"
        )

    def publish_transcript(self, event: AsrEvent, target_language: str) -> None:
        """Show recognition immediately while the newest translation is still running."""
        source = event.text.strip()
        if not source:
            return
        new_segment = event.segment_id != self._active_segment_id
        self._active_segment_id = event.segment_id
        self.source.setText(source)
        self.source.setVisible(self.settings.display_mode == "bilingual")
        self.source.setStyleSheet(self._text_style(self.settings.source_color, 0.7))
        if new_segment:
            self.translation.setText("正在翻译…")
            self.translation.setStyleSheet(self._text_style(self.settings.translation_color, 0.65))
        route = f"{event.language.upper()} → {target_language.upper()}"
        self.set_status("processing", route + " · 正在识别并翻译")
        self._arm_retention_timer()

    def publish(self, event: CaptionEvent) -> None:
        self._last_event = event
        self._active_segment_id = event.segment_id
        translated = event.translated_text.strip()
        source = event.source_text.strip()
        fallback = not translated
        self.source.setText(source)
        if translated:
            self.translation.setText(translated)
        elif self.settings.display_mode == "translated":
            self.translation.setText(source)
        else:
            self.translation.setText("")
        if event.state == "partial":
            self.source.setStyleSheet(self._text_style(self.settings.source_color, 0.62))
            self.translation.setStyleSheet(self._text_style(self.settings.translation_color, 0.72))
        else:
            self.source.setStyleSheet(self._text_style(self.settings.source_color, 0.82))
            self.translation.setStyleSheet(self._text_style(self.settings.translation_color))
        route = f"{event.source_language.upper()} → {event.target_language.upper()}"
        if event.state == "revised":
            scope = {
                "local": "本地修正",
                "cloud": "云端修正",
            }.get(event.processing_scope, "修正译文")
            suffix = f" · {scope} · v{event.revision}"
        else:
            suffix = " · 翻译失败，显示原文" if fallback else " · 本地快译"
        self.set_status("error" if fallback else "running", route + suffix)
        self.source.setVisible(self.settings.display_mode == "bilingual")
        self._arm_retention_timer()

    def clear_caption(self) -> None:
        """Clear expired text without hiding or moving the overlay."""
        self._retention_timer.stop()
        self._last_event = None
        self._active_segment_id = None
        self.source.clear()
        self.translation.clear()
        self.status.setText("LINGUARELAY · 等待系统音频")
        self.status.setStyleSheet("color: #77d6a5;")

    def _arm_retention_timer(self) -> None:
        seconds = self.settings.retention_seconds
        if seconds <= 0:
            self._retention_timer.stop()
            return
        self._retention_timer.start(max(100, round(seconds * 1000)))

    def _apply_frame_style(self) -> None:
        background = QColor(self.settings.background_color)
        background.setAlphaF(self.settings.background_opacity)
        self.frame.setStyleSheet(
            "#captionFrame {"
            f"background-color: {_rgba(background)};"
            "border: 1px solid rgba(255, 255, 255, 36);"
            "border-radius: 14px;"
            "} QLabel { background: transparent; }"
        )

    @staticmethod
    def _text_style(color: str, opacity: float = 1.0) -> str:
        resolved = QColor(color)
        resolved.setAlphaF(max(0.0, min(1.0, opacity)))
        return f"color: {_rgba(resolved)};"

    def reposition(self) -> None:
        screen = self.screen() or QApplication.primaryScreen()
        if screen is None:
            return
        geometry = screen.availableGeometry()
        x = geometry.x() + (geometry.width() - self.width()) // 2
        if self.settings.position == "top":
            y = geometry.y() + self.settings.bottom_margin
        else:
            y = geometry.y() + geometry.height() - self.height() - self.settings.bottom_margin
        self.move(x, y)
        self._keep_on_screen()
        self._positioned = True

    def reset_geometry(self) -> None:
        defaults = OverlaySettings()
        self.resize(defaults.width, defaults.height)
        self.settings = replace(
            self.settings,
            width=defaults.width,
            height=defaults.height,
            x=None,
            y=None,
        )
        self.reposition()
        self._commit_geometry()

    def resize_edges_at(self, point: QPoint) -> int:
        """Return the active resize edge mask for a local window position."""
        edges = 0
        if point.x() <= self._RESIZE_MARGIN:
            edges |= self._LEFT
        elif point.x() >= self.width() - self._RESIZE_MARGIN:
            edges |= self._RIGHT
        if point.y() <= self._RESIZE_MARGIN:
            edges |= self._TOP
        elif point.y() >= self.height() - self._RESIZE_MARGIN:
            edges |= self._BOTTOM
        return edges

    def eventFilter(self, watched: object, event: QEvent) -> bool:  # noqa: N802
        if watched is self.frame and isinstance(event, QMouseEvent):
            local = self.mapFromGlobal(event.globalPosition().toPoint())
            if event.type() == QEvent.Type.MouseButtonPress:
                return self._pointer_press(event, local)
            if event.type() == QEvent.Type.MouseMove:
                return self._pointer_move(event, local)
            if event.type() == QEvent.Type.MouseButtonRelease:
                return self._pointer_release(event)
        return super().eventFilter(watched, event)

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if not self._pointer_press(event, event.position().toPoint()):
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if not self._pointer_move(event, event.position().toPoint()):
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if not self._pointer_release(event):
            super().mouseReleaseEvent(event)

    def _pointer_press(self, event: QMouseEvent, local: QPoint) -> bool:
        if self.settings.click_through or event.button() != Qt.MouseButton.LeftButton:
            return False
        self._press_global = event.globalPosition().toPoint()
        self._press_geometry = self.geometry()
        self._resize_edges = self.resize_edges_at(local)
        if not self._resize_edges:
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
        event.accept()
        return True

    def _pointer_move(self, event: QMouseEvent, local: QPoint) -> bool:
        if self.settings.click_through:
            return False
        if self._press_global is None or self._press_geometry is None:
            self._set_resize_cursor(self.resize_edges_at(local))
            return False
        delta = event.globalPosition().toPoint() - self._press_global
        if self._resize_edges:
            self.setGeometry(self._resized_geometry(self._press_geometry, delta))
        else:
            self.move(self._press_geometry.topLeft() + delta)
        event.accept()
        return True

    def _pointer_release(self, event: QMouseEvent) -> bool:
        if event.button() != Qt.MouseButton.LeftButton or self._press_global is None:
            return False
        self._press_global = None
        self._press_geometry = None
        self._resize_edges = 0
        self.unsetCursor()
        self._keep_on_screen()
        self._commit_geometry()
        event.accept()
        return True

    def _resized_geometry(self, original: QRect, delta: QPoint) -> QRect:
        geometry = QRect(original)
        minimum_width = self.minimumWidth()
        minimum_height = self.minimumHeight()
        if self._resize_edges & self._LEFT:
            geometry.setLeft(min(original.left() + delta.x(), original.right() - minimum_width + 1))
        if self._resize_edges & self._RIGHT:
            geometry.setRight(
                max(original.right() + delta.x(), original.left() + minimum_width - 1)
            )
        if self._resize_edges & self._TOP:
            geometry.setTop(min(original.top() + delta.y(), original.bottom() - minimum_height + 1))
        if self._resize_edges & self._BOTTOM:
            geometry.setBottom(
                max(original.bottom() + delta.y(), original.top() + minimum_height - 1)
            )
        return geometry

    def _set_resize_cursor(self, edges: int) -> None:
        cursors = {
            self._LEFT: Qt.CursorShape.SizeHorCursor,
            self._RIGHT: Qt.CursorShape.SizeHorCursor,
            self._TOP: Qt.CursorShape.SizeVerCursor,
            self._BOTTOM: Qt.CursorShape.SizeVerCursor,
            self._LEFT | self._TOP: Qt.CursorShape.SizeFDiagCursor,
            self._RIGHT | self._BOTTOM: Qt.CursorShape.SizeFDiagCursor,
            self._RIGHT | self._TOP: Qt.CursorShape.SizeBDiagCursor,
            self._LEFT | self._BOTTOM: Qt.CursorShape.SizeBDiagCursor,
        }
        cursor = cursors.get(edges)
        if cursor is None:
            self.unsetCursor()
        else:
            self.setCursor(cursor)

    def _keep_on_screen(self) -> None:
        screen = QApplication.screenAt(self.geometry().center()) or self.screen()
        if screen is None:
            screen = QApplication.primaryScreen()
        if screen is None:
            return
        available = screen.availableGeometry()
        width = min(self.width(), available.width())
        height = min(self.height(), available.height())
        x = min(max(self.x(), available.left()), available.right() - width + 1)
        y = min(max(self.y(), available.top()), available.bottom() - height + 1)
        self.setGeometry(x, y, width, height)

    def _commit_geometry(self) -> None:
        geometry = self.geometry()
        self.settings = replace(
            self.settings,
            x=geometry.x(),
            y=geometry.y(),
            width=geometry.width(),
            height=geometry.height(),
        )
        self.geometry_changed.emit(geometry.x(), geometry.y(), geometry.width(), geometry.height())

    def showEvent(self, event: QShowEvent) -> None:  # noqa: N802
        if not self._positioned:
            self.reposition()
        super().showEvent(event)


def _rgba(color: QColor) -> str:
    return f"rgba({color.red()}, {color.green()}, {color.blue()}, {color.alpha()})"


def run_demo(settings: Settings) -> int:
    examples = (
        ("en", "zh", "The fast path never waits for an LLM.", "实时链路不会等待大模型。"),
        ("ja", "ko", "字幕表示を切り替えます。", "자막 표시를 전환합니다."),
        ("zh", "en", "音频只在本机内存中处理。", "Audio is processed in local memory."),
        ("ko", "ja", "번역이 실패해도 원문은 남습니다.", "翻訳に失敗しても原文は残ります。"),
    )
    app = QApplication.instance() or QApplication(sys.argv)
    overlay = CaptionOverlay(settings.overlay)
    overlay.show()
    index = 0

    def rotate_caption() -> None:
        nonlocal index
        source, target, text, translation = examples[index % len(examples)]
        overlay.publish(
            CaptionEvent(
                source_text=text,
                translated_text=translation,
                source_language=source,
                target_language=target,
                state="final",
                started_at_ms=0,
            )
        )
        index += 1

    rotate_caption()
    timer = QTimer(overlay)
    timer.timeout.connect(rotate_caption)
    timer.start(3_000)
    return app.exec()
