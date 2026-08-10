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

            self.status = QLabel("DEMO  ·  四语互译  ·  本地")
            self.status.setFont(QFont("Segoe UI", 9, QFont.Weight.DemiBold))
            self.status.setStyleSheet("color: #77d6a5;")

            content = QVBoxLayout(frame)
            content.setContentsMargins(22, 14, 22, 15)
            content.setSpacing(5)
            content.addWidget(self.status)
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
        ("EN → ZH", "The fast path should never wait for an LLM.", "实时链路不应等待大模型。"),
        (
            "JA → KO",
            "完了した字幕は、より多くの文脈を使って修正できます。",
            "완성된 자막은 더 많은 문맥으로 수정할 수 있습니다.",
        ),
        (
            "ZH → EN",
            "默认情况下，音频只在本机内存中处理。",
            "By default, audio is processed only in local memory.",
        ),
        (
            "KO → JA",
            "자동 언어 감지는 아직 사용하지 않습니다.",
            "言語の自動検出はまだ使用しません。",
        ),
        (
            "EN → KO",
            "Completed captions can be revised with more context.",
            "완성된 자막은 더 많은 문맥으로 수정할 수 있습니다.",
        ),
    )

    app = QApplication.instance() or QApplication(sys.argv)
    overlay = Overlay()
    overlay.show()

    index = 0

    def rotate_caption() -> None:
        nonlocal index
        route, source, translation = examples[index % len(examples)]
        overlay.status.setText(f"DEMO  ·  {route}  ·  本地")
        overlay.source.setText(source)
        overlay.translation.setText(translation)
        overlay.adjustSize()
        index += 1

    rotate_caption()
    timer = QTimer(overlay)
    timer.timeout.connect(rotate_caption)
    timer.start(3_000)
    return app.exec()
