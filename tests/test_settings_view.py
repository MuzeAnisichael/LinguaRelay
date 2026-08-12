from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QFont  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from lingua_relay.config import Settings  # noqa: E402
from lingua_relay.ui.settings_view import SettingsDialog  # noqa: E402


def test_settings_dialog_collects_caption_and_realtime_preferences() -> None:
    _app = QApplication.instance() or QApplication([])
    dialog = SettingsDialog(Settings())
    dialog.retention_seconds.setValue(4.5)
    dialog.translation_font.setCurrentFont(QFont("Arial"))
    dialog.translation_size.setValue(25)
    dialog.translation_color.set_color("#59D395")
    dialog.background_color.set_color("#20242C")
    dialog.status_visible.setChecked(False)
    dialog.partial_interval.setCurrentIndex(dialog.partial_interval.findData(640))
    dialog.punctuation_min.setValue(1.5)
    dialog.max_caption.setValue(7.0)

    result = dialog._collect()
    result.validate()

    assert result.overlay.retention_seconds == 4.5
    assert result.overlay.translation_font_size == 25
    assert result.overlay.translation_color == "#59D395"
    assert result.overlay.background_color == "#20242C"
    assert result.overlay.status_visible is False
    assert result.asr.partial_interval_ms == 640
    assert result.asr.max_caption_seconds == 7.0


def test_settings_dialog_keeps_language_route_distinct() -> None:
    app = QApplication.instance() or QApplication([])
    dialog = SettingsDialog(Settings())
    target = dialog.source_language.currentData()
    dialog.target_language.setCurrentIndex(dialog.target_language.findData(target))
    app.processEvents()

    assert dialog.source_language.currentData() != dialog.target_language.currentData()


def test_settings_dialog_configures_local_llm_without_putting_a_key_in_config() -> None:
    _app = QApplication.instance() or QApplication([])
    dialog = SettingsDialog(Settings())
    dialog._apply_llm_preset("local", "http://127.0.0.1:11434/v1")
    dialog.llm_model.setText("local-translator")
    dialog.llm_api_key_env.setText("LINGUA_RELAY_API_KEY")

    result = dialog._collect()
    result.validate()

    assert result.correction.mode == "asynchronous"
    assert result.correction.provider == "local"
    assert result.correction.endpoint == "http://127.0.0.1:11434/v1"
    assert result.correction.model == "local-translator"
