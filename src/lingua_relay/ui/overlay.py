from __future__ import annotations

import sys

from lingua_relay.config import Settings


def run_demo(settings: Settings) -> int:
    from PySide6.QtCore import Qt, QTimer
    from PySide6.QtGui import QFont
    from PySide6.QtWidgets import QApplication, QFrame, QLabel, QVBoxLayout, QWidget

    class Overlay(QWidget):
        def __init__(self) -> None:
            super().__init__()
            flags = Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint
            flags |= Qt.WindowType.Tool
            if settings.overlay.click_through:
                flags |= Qt.WindowType.WindowTransparentForInput
            self.setWindowFlags(flags)
            self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
            self.setWindowOpacity(settings.overlay.opacity)

            frame = QFrame(self)
            frame.setObjectName("captionFrame")
            frame.setStyleSheet(
                "#captionFrame {"
                "background-color: rgba(16, 18, 24, 224);"
                "border: 1px solid rgba(255, 255, 255, 36);"
                "border-radius: 14px;"
                "}"
                "QLabel { color: white; background: transparent; }"
            )

            self.source = QLabel("LinguaRelay is ready")
            self.source.setFont(QFont("Segoe UI", 11))
            self.source.setStyleSheet("color: rgba(255, 255, 255, 155);")
            self.source.setWordWrap(True)

            self.translation = QLabel("实时字幕悬浮窗演示")
            self.translation.setFont(QFont("Microsoft YaHei UI", 17, QFont.Weight.DemiBold))
            self.translation.setWordWrap(True)

            status = QLabel("DEMO  ·  EN → 简体中文  ·  本地")
            status.setFont(QFont("Segoe UI", 9, QFont.Weight.DemiBold))
            status.setStyleSheet("color: #77d6a5;")

            content = QVBoxLayout(frame)
            content.setContentsMargins(22, 14, 22, 15)
            content.setSpacing(5)
            content.addWidget(status)
            content.addWidget(self.source)
            content.addWidget(self.translation)

            root = QVBoxLayout(self)
            root.setContentsMargins(0, 0, 0, 0)
            root.addWidget(frame)
            self.setFixedWidth(settings.overlay.width)

        def showEvent(self, event: object) -> None:  # noqa: N802
            screen = self.screen().availableGeometry()
            self.adjustSize()
            x = screen.x() + (screen.width() - self.width()) // 2
            y = screen.y() + screen.height() - self.height() - settings.overlay.bottom_margin
            self.move(x, y)
            super().showEvent(event)

    examples = (
        ("The fast path should never wait for an LLM.", "实时链路不应等待大模型。"),
        (
            "Completed captions can be revised with more context.",
            "完成的字幕可以结合更多上下文进行修正。",
        ),
        ("Audio remains on this computer by default.", "默认情况下，音频只在本机处理。"),
    )

    app = QApplication.instance() or QApplication(sys.argv)
    overlay = Overlay()
    overlay.show()

    index = 0

    def rotate_caption() -> None:
        nonlocal index
        source, translation = examples[index % len(examples)]
        overlay.source.setText(source)
        overlay.translation.setText(translation)
        overlay.adjustSize()
        index += 1

    rotate_caption()
    timer = QTimer(overlay)
    timer.timeout.connect(rotate_caption)
    timer.start(3_000)
    return app.exec()
