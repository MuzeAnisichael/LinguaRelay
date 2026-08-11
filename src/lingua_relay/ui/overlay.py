from __future__ import annotations

import sys
from dataclasses import replace

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QFont, QShowEvent
from PySide6.QtWidgets import QApplication, QFrame, QLabel, QVBoxLayout, QWidget

from lingua_relay.config import OverlaySettings, Settings
from lingua_relay.events import CaptionEvent


class CaptionOverlay(QWidget):
    """Small always-on-top caption surface; model work never runs here."""

    def __init__(self, settings: OverlaySettings) -> None:
        super().__init__()
        self.settings = settings
        self._last_event: CaptionEvent | None = None
        self._build_window()
        self._build_content()
        self.apply_settings(settings)

    def _build_window(self) -> None:
        self.setObjectName("captionOverlay")
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setWindowTitle("LinguaRelay")

    def _build_content(self) -> None:
        frame = QFrame(self)
        frame.setObjectName("captionFrame")
        frame.setStyleSheet(
            "#captionFrame {"
            "background-color: rgba(16, 18, 24, 224);"
            "border: 1px solid rgba(255, 255, 255, 36);"
            "border-radius: 14px;"
            "} QLabel { color: white; background: transparent; }"
        )
        self.status = QLabel("LINGUARELAY · 正在准备")
        self.status.setFont(QFont("Segoe UI", 9, QFont.Weight.DemiBold))
        self.status.setStyleSheet("color: #77d6a5;")
        self.source = QLabel("")
        self.source.setWordWrap(True)
        self.translation = QLabel("正在加载模型…")
        self.translation.setWordWrap(True)

        content = QVBoxLayout(frame)
        content.setContentsMargins(22, 14, 22, 15)
        content.setSpacing(5)
        content.addWidget(self.status)
        content.addWidget(self.source)
        content.addWidget(self.translation)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.addWidget(frame)

    def apply_settings(self, settings: OverlaySettings) -> None:
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
        self.setFixedWidth(settings.width)
        self.source.setFont(QFont("Segoe UI", settings.source_font_size))
        self.translation.setFont(
            QFont("Microsoft YaHei UI", settings.translation_font_size, QFont.Weight.DemiBold)
        )
        self.source.setVisible(settings.display_mode == "bilingual")
        self.adjustSize()
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

    def set_status(self, state: str, message: str) -> None:
        colors = {"running": "#77d6a5", "loading": "#f2c66d", "error": "#ff7d8b"}
        self.status.setStyleSheet(f"color: {colors.get(state, '#b8c1d1')};")
        self.status.setText(f"LINGUARELAY · {message}")

    def publish(self, event: CaptionEvent) -> None:
        self._last_event = event
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
            self.source.setStyleSheet("color: rgba(255, 255, 255, 125);")
            self.translation.setStyleSheet("color: rgba(255, 255, 255, 175);")
        else:
            self.source.setStyleSheet("color: rgba(255, 255, 255, 165);")
            self.translation.setStyleSheet("color: white;")
        route = f"{event.source_language.upper()} → {event.target_language.upper()}"
        suffix = " · 翻译失败，显示原文" if fallback else ""
        self.set_status("error" if fallback else "running", route + suffix)
        self.source.setVisible(self.settings.display_mode == "bilingual")
        self.adjustSize()
        self.reposition()

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

    def showEvent(self, event: QShowEvent) -> None:  # noqa: N802
        self.adjustSize()
        self.reposition()
        super().showEvent(event)


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
