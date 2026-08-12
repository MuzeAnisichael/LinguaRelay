"""Render deterministic product screenshots used by the repository README files."""

from __future__ import annotations

import argparse
import os
from dataclasses import replace
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "windows" if os.name == "nt" else "offscreen")

from PySide6.QtGui import QColor, QPalette  # noqa: E402
from PySide6.QtWidgets import QApplication, QTabWidget  # noqa: E402

from lingua_relay.config import Settings  # noqa: E402
from lingua_relay.events import CaptionEvent  # noqa: E402
from lingua_relay.ui.overlay import CaptionOverlay  # noqa: E402
from lingua_relay.ui.settings_view import SettingsDialog  # noqa: E402


def _dark_palette() -> QPalette:
    palette = QPalette()
    colors = {
        QPalette.ColorRole.Window: "#181B21",
        QPalette.ColorRole.WindowText: "#EEF2F6",
        QPalette.ColorRole.Base: "#101218",
        QPalette.ColorRole.AlternateBase: "#1E222A",
        QPalette.ColorRole.ToolTipBase: "#252A34",
        QPalette.ColorRole.ToolTipText: "#FFFFFF",
        QPalette.ColorRole.Text: "#EEF2F6",
        QPalette.ColorRole.Button: "#252A34",
        QPalette.ColorRole.ButtonText: "#EEF2F6",
        QPalette.ColorRole.BrightText: "#FF7D8B",
        QPalette.ColorRole.Link: "#70B7FF",
        QPalette.ColorRole.Highlight: "#3979B8",
        QPalette.ColorRole.HighlightedText: "#FFFFFF",
        QPalette.ColorRole.PlaceholderText: "#8C96A8",
    }
    for role, value in colors.items():
        palette.setColor(role, QColor(value))
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text, QColor("#747D8C"))
    palette.setColor(
        QPalette.ColorGroup.Disabled,
        QPalette.ColorRole.ButtonText,
        QColor("#747D8C"),
    )
    return palette


def _save_widget(widget, path: Path) -> None:
    widget.show()
    QApplication.processEvents()
    image = widget.grab()
    if image.isNull() or not image.save(str(path), "PNG"):
        raise RuntimeError(f"unable to save screenshot: {path}")
    widget.close()


def capture(output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    app = QApplication.instance() or QApplication([])
    app.setStyle("Fusion")
    app.setPalette(_dark_palette())

    defaults = Settings()
    overlay_settings = replace(
        defaults.overlay,
        width=1040,
        height=180,
        x=None,
        y=None,
        retention_seconds=0,
    )
    overlay = CaptionOverlay(overlay_settings)
    overlay.publish(
        CaptionEvent(
            source_text="The fast path stays responsive while the LLM improves completed captions.",
            translated_text="快速链路保持实时响应，大模型在后台优化完整字幕。",
            source_language="en",
            target_language="zh",
            state="final",
            started_at_ms=0,
        )
    )
    _save_widget(overlay, output_dir / "caption-overlay.png")

    settings = replace(
        defaults,
        correction=replace(
            defaults.correction,
            mode="asynchronous",
            provider="local",
            endpoint="http://127.0.0.1:11434/v1",
            model="qwen2.5:7b",
        ),
    )
    dialog = SettingsDialog(settings)
    dialog.resize(880, 680)
    tabs = dialog.findChild(QTabWidget)
    if tabs is None:
        raise RuntimeError("settings tab widget was not found")
    tabs.setCurrentIndex(3)
    _save_widget(dialog, output_dir / "llm-settings.png")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("docs/images"),
        help="directory for the generated PNG files",
    )
    args = parser.parse_args()
    capture(args.output_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
