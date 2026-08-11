from __future__ import annotations

import ctypes
import sys
import threading
from contextlib import suppress
from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import QObject, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import (
    QAction,
    QActionGroup,
    QColor,
    QDesktopServices,
    QIcon,
    QPainter,
    QPixmap,
)
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QMenu,
    QMessageBox,
    QSystemTrayIcon,
    QTextEdit,
)

from lingua_relay import __version__
from lingua_relay.audio import WasapiDeviceManager
from lingua_relay.config import Settings
from lingua_relay.history import JsonlHistory
from lingua_relay.languages import SUPPORTED_LANGUAGES
from lingua_relay.paths import AppPaths
from lingua_relay.runtime_state import RuntimeJournal
from lingua_relay.service import RealtimeCaptionService
from lingua_relay.settings_io import (
    persist_audio_device,
    persist_display_mode,
    persist_route,
    persist_setting,
)
from lingua_relay.ui.model_setup import ensure_model_pack
from lingua_relay.ui.overlay import CaptionOverlay
from lingua_relay.updates import UpdateInfo, check_for_update


class _Bridge(QObject):
    caption = Signal(object)
    status = Signal(str, str)
    correction_status = Signal(str, str)
    update = Signal(object, bool)
    update_error = Signal(str)


class _GlobalHotkey(QObject):
    """Small Windows key-state monitor used for the configured show/hide shortcut."""

    activated = Signal()

    def __init__(self, shortcut: str) -> None:
        super().__init__()
        self.shortcut = shortcut
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if sys.platform != "win32" or self._thread is not None:
            return
        self._thread = threading.Thread(target=self._poll, name="lingua-relay-hotkey", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(1)

    def _poll(self) -> None:
        parts = {part.strip().upper() for part in self.shortcut.split("+")}
        key_name = next((part for part in parts if len(part) == 1 and part.isalnum()), "L")
        key_code = ord(key_name)
        user32 = ctypes.windll.user32
        was_down = False
        while not self._stop.wait(0.04):
            ctrl = not {"CTRL", "CONTROL"}.isdisjoint(parts)
            alt = "ALT" in parts
            modifiers_down = (not ctrl or user32.GetAsyncKeyState(0x11) & 0x8000) and (
                not alt or user32.GetAsyncKeyState(0x12) & 0x8000
            )
            down = bool(modifiers_down and user32.GetAsyncKeyState(key_code) & 0x8000)
            if down and not was_down:
                self.activated.emit()
            was_down = down


class DesktopController:
    def __init__(
        self,
        app: QApplication,
        config_path: Path | None,
        *,
        model_root: Path | None = None,
        recovered: bool = False,
    ) -> None:
        self.app = app
        self.paths = AppPaths.discover()
        self.paths.data_dir.mkdir(parents=True, exist_ok=True)
        development_models = Path.cwd() / "models"
        self.model_root = model_root or (
            development_models if development_models.is_dir() else self.paths.model_dir
        )
        self.recovered = recovered
        self.latest_release_url: str | None = None
        self.config_path = config_path or self.paths.config_path
        self.template_path = self.paths.resource_dir / "config.example.toml"
        self.settings = self._load_settings()
        self.bridge = _Bridge()
        self.overlay = CaptionOverlay(self.settings.overlay)
        self.bridge.caption.connect(self.overlay.publish)
        self.bridge.status.connect(self.overlay.set_status)
        self.bridge.correction_status.connect(self.overlay.set_status)
        self.bridge.update.connect(self._on_update)
        self.bridge.update_error.connect(self._on_update_error)
        self.service = RealtimeCaptionService(
            self.settings,
            on_caption=self.bridge.caption.emit,
            on_status=self.bridge.status.emit,
            on_correction_status=self.bridge.correction_status.emit,
            model_root=self.model_root,
        )
        self.icon = _make_icon()
        self.tray = QSystemTrayIcon(self.icon, self.app)
        self.tray.setToolTip("LinguaRelay")
        self.menu = QMenu()
        self._build_menu()
        self.tray.setContextMenu(self.menu)
        self.tray.activated.connect(self._tray_activated)
        self.hotkey = _GlobalHotkey(self.settings.overlay.toggle_shortcut)
        self.hotkey.activated.connect(self.toggle_overlay)
        self.app.aboutToQuit.connect(self.shutdown)

    def run(self) -> None:
        self.app.setQuitOnLastWindowClosed(False)
        self.tray.show()
        self.overlay.show()
        self.hotkey.start()
        QTimer.singleShot(0, self.service.start)
        QTimer.singleShot(1500, self._after_start)

    def _load_settings(self) -> Settings:
        if self.config_path.exists():
            settings = Settings.load(self.config_path)
        else:
            settings = Settings.load(None)
        translation_path = settings.translation.model_path
        cwd_model = Path.cwd() / translation_path
        packaged_model = self.model_root / translation_path.name
        model_path = cwd_model if (cwd_model / "model.bin").is_file() else packaged_model
        return replace(
            settings,
            app=replace(settings.app, history_path=self.paths.history_path),
            translation=replace(settings.translation, model_path=model_path),
            correction=replace(
                settings.correction,
                glossary_path=(
                    self.config_path.parent / settings.correction.glossary_path
                    if not settings.correction.glossary_path.is_absolute()
                    else settings.correction.glossary_path
                ),
            ),
        )

    def _build_menu(self) -> None:
        self.pause_action = QAction("暂停", self.menu)
        self.pause_action.triggered.connect(self.toggle_pause)
        self.menu.addAction(self.pause_action)
        self.show_action = QAction("隐藏悬浮窗", self.menu)
        self.show_action.triggered.connect(self.toggle_overlay)
        self.menu.addAction(self.show_action)
        self.menu.addSeparator()

        self.source_menu = self.menu.addMenu("源语言（手动）")
        self.target_menu = self.menu.addMenu("目标语言")
        self._populate_languages(self.source_menu, source=True)
        self._populate_languages(self.target_menu, source=False)

        display_menu = self.menu.addMenu("字幕显示")
        display_group = QActionGroup(display_menu)
        for mode, label in (("translated", "仅显示译文"), ("bilingual", "双语同时显示")):
            action = display_menu.addAction(label)
            action.setCheckable(True)
            action.setChecked(self.settings.overlay.display_mode == mode)
            action.triggered.connect(
                lambda _checked=False, value=mode: self.set_display_mode(value)
            )
            display_group.addAction(action)
        self.click_action = display_menu.addAction("点击穿透")
        self.click_action.setCheckable(True)
        self.click_action.setChecked(self.settings.overlay.click_through)
        self.click_action.triggered.connect(self.set_click_through)

        correction_menu = self.menu.addMenu("大模型修正")
        correction_group = QActionGroup(correction_menu)
        self.correction_actions: dict[str, QAction] = {}
        for mode, label in (
            ("off", "关闭（仅本地快译）"),
            ("asynchronous", "完整句异步修正"),
            ("live", "实时异步修正（含临时字幕）"),
        ):
            action = correction_menu.addAction(label)
            action.setCheckable(True)
            action.setChecked(self.settings.correction.mode == mode)
            action.triggered.connect(
                lambda _checked=False, value=mode: self.set_correction_mode(value)
            )
            correction_group.addAction(action)
            self.correction_actions[mode] = action
        scope = {
            "none": "未配置 provider",
            "local": "本地处理（不上传字幕）",
            "openai_compatible": "云端传输（字幕将发送至配置的 API）",
        }[self.settings.correction.provider]
        scope_action = correction_menu.addAction(scope)
        scope_action.setEnabled(False)

        self.device_menu = self.menu.addMenu("音频设备")
        self.device_menu.aboutToShow.connect(self._refresh_devices)
        history_menu = self.menu.addMenu("历史记录")
        history_menu.addAction("查看最近记录", self.show_history)
        history_menu.addAction("导出…", self.export_history)
        self.status_action = QAction("状态：正在准备", self.menu)
        self.status_action.setEnabled(False)
        self.menu.addAction(self.status_action)
        self.bridge.status.connect(self._update_status_action)
        self.correction_status_action = QAction("修正：正在准备", self.menu)
        self.correction_status_action.setEnabled(False)
        self.menu.addAction(self.correction_status_action)
        self.bridge.correction_status.connect(self._update_correction_status)
        self.menu.addAction("检查更新", lambda: self.check_updates(manual=True))
        self.release_action = self.menu.addAction("打开发布页面", self.open_release_page)
        self.release_action.setEnabled(False)
        self.menu.addSeparator()
        self.menu.addAction("退出", self.app.quit)

    def _populate_languages(self, menu: QMenu, *, source: bool) -> None:
        group = QActionGroup(menu)
        for code, language in SUPPORTED_LANGUAGES.items():
            action = menu.addAction(f"{language.native_name} ({code})")
            action.setCheckable(True)
            current = (
                self.settings.app.source_language if source else self.settings.app.target_language
            )
            action.setChecked(code == current)
            action.triggered.connect(
                lambda _checked=False, value=code, is_source=source: self.set_language(
                    value, source=is_source
                )
            )
            group.addAction(action)

    def set_language(self, code: str, *, source: bool) -> None:
        current_source = self.settings.app.source_language
        current_target = self.settings.app.target_language
        if source:
            new_source = code
            new_target = current_target if code != current_target else _other_language(code)
        else:
            new_target = code
            new_source = current_source if code != current_source else _other_language(code)
        self.settings = replace(
            self.settings,
            app=replace(self.settings.app, source_language=new_source, target_language=new_target),
        )
        persist_route(new_source, new_target, self.config_path, self.template_path)
        self.service.set_route(new_source, new_target)
        self.source_menu.clear()
        self.target_menu.clear()
        self._populate_languages(self.source_menu, source=True)
        self._populate_languages(self.target_menu, source=False)

    def set_display_mode(self, mode: str) -> None:
        self.settings = replace(
            self.settings, overlay=replace(self.settings.overlay, display_mode=mode)
        )
        self.overlay.set_display_mode(mode)
        persist_display_mode(mode, self.config_path, self.template_path)

    def set_click_through(self, enabled: bool) -> None:
        self.settings = replace(
            self.settings, overlay=replace(self.settings.overlay, click_through=enabled)
        )
        self.overlay.set_click_through(enabled)
        persist_setting("overlay", "click_through", enabled, self.config_path, self.template_path)

    def set_correction_mode(self, mode: str) -> None:
        try:
            self.service.set_correction_mode(mode)
        except ValueError as error:
            self.correction_actions[self.settings.correction.mode].setChecked(True)
            QMessageBox.warning(None, "无法启用修正", str(error))
            return
        self.settings = replace(
            self.settings, correction=replace(self.settings.correction, mode=mode)
        )
        persist_setting("correction", "mode", mode, self.config_path, self.template_path)

    def toggle_pause(self) -> None:
        state = self.service.snapshot().state
        if state in {"error", "stopped"}:
            self.service.start()
            self.pause_action.setText("暂停")
        elif state == "paused":
            self.service.resume()
            self.pause_action.setText("暂停")
        else:
            self.service.pause()
            self.pause_action.setText("继续")

    def toggle_overlay(self) -> None:
        if self.overlay.isVisible():
            self.overlay.hide()
            self.show_action.setText("显示悬浮窗")
        else:
            self.overlay.show()
            self.overlay.raise_()
            self.show_action.setText("隐藏悬浮窗")

    def _refresh_devices(self) -> None:
        self.device_menu.clear()
        try:
            devices = WasapiDeviceManager().list_devices()
        except Exception as error:
            action = self.device_menu.addAction(f"无法读取设备：{error}")
            action.setEnabled(False)
            return
        default = self.device_menu.addAction("跟随系统默认设备")
        default.setCheckable(True)
        default.setChecked(self.settings.audio.device == "default")
        default.triggered.connect(lambda: self.set_device("default"))
        for device in devices:
            action = self.device_menu.addAction(device.name)
            action.setCheckable(True)
            action.setChecked(self.settings.audio.device == device.device_id)
            action.triggered.connect(
                lambda _checked=False, value=device.device_id: self.set_device(value)
            )

    def set_device(self, device: str) -> None:
        self.settings = replace(self.settings, audio=replace(self.settings.audio, device=device))
        persist_audio_device(device, self.config_path, self.template_path)
        self.service.set_audio_device(device)

    def show_history(self) -> None:
        rows = tuple(JsonlHistory(self.paths.history_path).read_all())[-100:]
        text = (
            "\n\n".join(
                f"[{row.get('source_language')}→{row.get('target_language')}] "
                f"{row.get('source_text')}\n{row.get('translated_text') or row.get('source_text')}"
                for row in rows
            )
            or "暂无记录"
        )
        viewer = QTextEdit()
        viewer.setReadOnly(True)
        viewer.setPlainText(text)
        viewer.setWindowTitle("LinguaRelay 历史记录")
        viewer.resize(760, 520)
        viewer.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        viewer.show()
        self._history_viewer = viewer

    def export_history(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            None,
            "导出字幕历史",
            str(self.paths.data_dir / "captions.csv"),
            "CSV (*.csv);;JSON Lines (*.jsonl);;SubRip (*.srt)",
        )
        if not path:
            return
        try:
            JsonlHistory(self.paths.history_path).export(path)
        except Exception as error:
            QMessageBox.critical(None, "导出失败", str(error))

    def _update_status_action(self, state: str, message: str) -> None:
        self.status_action.setText(f"状态：{message}")
        self.tray.setToolTip(f"LinguaRelay · {message}")
        if state == "error":
            self.pause_action.setText("重试启动")
            self.tray.showMessage("LinguaRelay", message, QSystemTrayIcon.MessageIcon.Critical)

    def _update_correction_status(self, state: str, message: str) -> None:
        self.correction_status_action.setText(f"修正：{message}")
        if state == "error":
            self.tray.showMessage(
                "LinguaRelay 修正",
                message,
                QSystemTrayIcon.MessageIcon.Warning,
            )

    def _tray_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            self.toggle_overlay()

    def _after_start(self) -> None:
        if self.recovered:
            self.tray.showMessage(
                "LinguaRelay 已恢复",
                "检测到上次未正常退出；模型临时文件已清理，字幕历史仍保留。",
                QSystemTrayIcon.MessageIcon.Warning,
            )
        self.check_updates(manual=False)

    def check_updates(self, *, manual: bool) -> None:
        def worker() -> None:
            try:
                self.bridge.update.emit(check_for_update(__version__), manual)
            except Exception as error:
                if manual:
                    self.bridge.update_error.emit(str(error))

        threading.Thread(target=worker, name="lingua-relay-update", daemon=True).start()

    def _on_update(self, info: UpdateInfo, manual: bool) -> None:
        self.latest_release_url = info.release_url
        self.release_action.setEnabled(True)
        if info.available:
            self.tray.showMessage(
                "LinguaRelay 有新版本",
                f"v{info.latest_version} 已发布。请从 GitHub 下载并运行新安装包。",
                QSystemTrayIcon.MessageIcon.Information,
            )
        elif manual:
            self.tray.showMessage(
                "LinguaRelay 更新",
                f"当前已是最新版 v{__version__}。",
                QSystemTrayIcon.MessageIcon.Information,
            )

    def _on_update_error(self, message: str) -> None:
        QMessageBox.warning(None, "检查更新失败", message)

    def open_release_page(self) -> None:
        if self.latest_release_url:
            QDesktopServices.openUrl(QUrl(self.latest_release_url))

    def shutdown(self) -> None:
        self.hotkey.stop()
        with suppress(TimeoutError):
            self.service.stop()


def run_app(config_path: Path | None = None) -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName("LinguaRelay")
    app.setApplicationDisplayName("LinguaRelay")
    app.setWindowIcon(_make_icon())
    paths = AppPaths.discover()
    journal = RuntimeJournal(paths.data_dir, version=__version__)
    recovery = journal.begin()
    journal.install_exception_hooks()
    development_models = Path.cwd() / "models"
    model_root = development_models if development_models.is_dir() else paths.model_dir
    manifest_path = paths.resource_dir / "packaging" / "model-manifest.json"
    try:
        if not ensure_model_pack(model_root, manifest_path, paths.data_dir / "downloads"):
            return 0
        controller = DesktopController(
            app,
            config_path,
            model_root=model_root,
            recovered=recovery.previous_run_crashed,
        )
        controller.run()
        return app.exec()
    finally:
        journal.close_cleanly()


def _make_icon() -> QIcon:
    pixmap = QPixmap(64, 64)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setBrush(QColor("#59d395"))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.drawRoundedRect(4, 4, 56, 56, 15, 15)
    painter.setPen(QColor("#101218"))
    font = painter.font()
    font.setBold(True)
    font.setPixelSize(28)
    painter.setFont(font)
    painter.drawText(pixmap.rect(), Qt.AlignmentFlag.AlignCenter, "译")
    painter.end()
    return QIcon(pixmap)


def _other_language(code: str) -> str:
    return next(candidate for candidate in SUPPORTED_LANGUAGES if candidate != code)
