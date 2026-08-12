from __future__ import annotations

import ctypes
import gc
import os
import sys
import threading
from contextlib import suppress
from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import QObject, QProcess, QTimer, QUrl, Signal
from PySide6.QtGui import (
    QAction,
    QActionGroup,
    QDesktopServices,
    QIcon,
)
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QMenu,
    QMessageBox,
    QSystemTrayIcon,
)

from lingua_relay import __version__
from lingua_relay.audio import WasapiDeviceManager
from lingua_relay.config import Settings, migrate_legacy_realtime_defaults
from lingua_relay.history import JsonlHistory
from lingua_relay.languages import SUPPORTED_LANGUAGES
from lingua_relay.model_pack import load_model_catalog, uninstall_model_pack
from lingua_relay.paths import AppPaths
from lingua_relay.runtime_state import RuntimeJournal
from lingua_relay.service import RealtimeCaptionService
from lingua_relay.settings_io import (
    persist_audio_device,
    persist_display_mode,
    persist_overlay_geometry,
    persist_route,
    persist_setting,
    persist_settings,
)
from lingua_relay.ui.history_view import HistoryWindow
from lingua_relay.ui.model_setup import ensure_model_installation
from lingua_relay.ui.overlay import CaptionOverlay
from lingua_relay.ui.settings_view import SettingsDialog
from lingua_relay.updates import UpdateInfo, check_for_update


class _Bridge(QObject):
    caption = Signal(object)
    transcript = Signal(object, str)
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
        self._models_ready_notified = False
        self.config_path = config_path or self.paths.config_path
        self.template_path = self.paths.resource_dir / "config.example.toml"
        self.settings = self._load_settings()
        self.bridge = _Bridge()
        self.overlay = CaptionOverlay(self.settings.overlay)
        self.overlay.geometry_changed.connect(self._persist_overlay_geometry)
        self.overlay.pause_requested.connect(self.toggle_pause)
        self.overlay.display_mode_requested.connect(self.toggle_display_mode)
        self.overlay.history_requested.connect(self.show_history)
        self.overlay.settings_requested.connect(self.show_settings)
        self.overlay.hide_requested.connect(self.toggle_overlay)
        self.bridge.caption.connect(self.overlay.publish)
        self.bridge.transcript.connect(self.overlay.publish_transcript)
        self.bridge.status.connect(self.overlay.set_status)
        self.bridge.update.connect(self._on_update)
        self.bridge.update_error.connect(self._on_update_error)
        self.service = RealtimeCaptionService(
            self.settings,
            on_caption=self.bridge.caption.emit,
            on_transcript=self.bridge.transcript.emit,
            on_status=self.bridge.status.emit,
            on_correction_status=self.bridge.correction_status.emit,
            model_root=self.model_root,
        )
        self.icon = _make_icon(self.paths.resource_dir)
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
        settings, migrated = migrate_legacy_realtime_defaults(settings)
        if migrated:
            persist_settings(
                "asr",
                {
                    "adaptive_partial_enabled": settings.asr.adaptive_partial_enabled,
                    "punctuation_boundary_min_seconds": (
                        settings.asr.punctuation_boundary_min_seconds
                    ),
                    "preferred_segment_seconds": settings.asr.preferred_segment_seconds,
                    "max_caption_seconds": settings.asr.max_caption_seconds,
                    "max_window_seconds": settings.asr.max_window_seconds,
                    "max_segment_seconds": settings.asr.max_segment_seconds,
                },
                self.config_path,
                self.template_path,
            )
        translation_path = settings.translation.model_path
        packaged_model = self.model_root / translation_path.name
        return replace(
            settings,
            app=replace(settings.app, history_path=self.paths.history_path),
            translation=replace(settings.translation, model_path=packaged_model),
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
        self.display_actions: dict[str, QAction] = {}
        for mode, label in (("translated", "仅显示译文"), ("bilingual", "双语同时显示")):
            action = display_menu.addAction(label)
            action.setCheckable(True)
            action.setChecked(self.settings.overlay.display_mode == mode)
            action.triggered.connect(
                lambda _checked=False, value=mode: self.set_display_mode(value)
            )
            display_group.addAction(action)
            self.display_actions[mode] = action
        self.click_action = display_menu.addAction("点击穿透")
        self.click_action.setCheckable(True)
        self.click_action.setChecked(self.settings.overlay.click_through)
        self.click_action.triggered.connect(self.set_click_through)
        display_menu.addAction("重置悬浮窗位置和大小", self.overlay.reset_geometry)
        self.menu.addAction("用户设置…", self.show_settings)

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
        self.correction_scope_action = correction_menu.addAction(scope)
        self.correction_scope_action.setEnabled(False)

        self.device_menu = self.menu.addMenu("音频设备")
        self.device_menu.aboutToShow.connect(self._refresh_devices)
        history_menu = self.menu.addMenu("历史记录")
        history_menu.addAction("查看最近记录", self.show_history)
        history_menu.addAction("导出…", self.export_history)
        storage_menu = self.menu.addMenu("模型与卸载")
        storage_menu.addAction("删除本地模型并退出…", self.remove_local_models)
        storage_menu.addAction("卸载 LinguaRelay…", self.uninstall_application)
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
        self.menu.addAction("关于 LinguaRelay", self.show_about)
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

    def toggle_display_mode(self) -> None:
        target = "translated" if self.settings.overlay.display_mode == "bilingual" else "bilingual"
        self.set_display_mode(target)

    def set_click_through(self, enabled: bool) -> None:
        self.settings = replace(
            self.settings, overlay=replace(self.settings.overlay, click_through=enabled)
        )
        self.overlay.set_click_through(enabled)
        persist_setting("overlay", "click_through", enabled, self.config_path, self.template_path)

    def show_settings(self) -> None:
        dialog = SettingsDialog(self.settings)
        dialog.setWindowIcon(self.icon)
        dialog.remove_models_requested.connect(
            lambda: QTimer.singleShot(0, self.remove_local_models)
        )
        dialog.uninstall_requested.connect(lambda: QTimer.singleShot(0, self.uninstall_application))
        if dialog.exec() != SettingsDialog.DialogCode.Accepted:
            return
        previous = self.settings
        updated = dialog.result_settings()
        self.settings = updated

        persist_route(
            updated.app.source_language,
            updated.app.target_language,
            self.config_path,
            self.template_path,
        )
        persist_setting(
            "app",
            "history_enabled",
            updated.app.history_enabled,
            self.config_path,
            self.template_path,
        )
        persist_settings(
            "overlay",
            {
                "opacity": updated.overlay.opacity,
                "click_through": updated.overlay.click_through,
                "display_mode": updated.overlay.display_mode,
                "source_font_size": updated.overlay.source_font_size,
                "translation_font_size": updated.overlay.translation_font_size,
                "source_font_family": updated.overlay.source_font_family,
                "translation_font_family": updated.overlay.translation_font_family,
                "source_color": updated.overlay.source_color,
                "translation_color": updated.overlay.translation_color,
                "background_color": updated.overlay.background_color,
                "background_opacity": updated.overlay.background_opacity,
                "status_visible": updated.overlay.status_visible,
                "retention_seconds": updated.overlay.retention_seconds,
            },
            self.config_path,
            self.template_path,
        )
        persist_settings(
            "asr",
            {
                "partial_interval_ms": updated.asr.partial_interval_ms,
                "adaptive_partial_enabled": updated.asr.adaptive_partial_enabled,
                "punctuation_boundary_enabled": updated.asr.punctuation_boundary_enabled,
                "punctuation_boundary_min_seconds": (updated.asr.punctuation_boundary_min_seconds),
                "preferred_segment_seconds": updated.asr.preferred_segment_seconds,
                "max_caption_seconds": updated.asr.max_caption_seconds,
                "max_window_seconds": updated.asr.max_window_seconds,
                "max_segment_seconds": updated.asr.max_segment_seconds,
                "suppress_credit_hallucinations": (updated.asr.suppress_credit_hallucinations),
                "context_hint": updated.asr.context_hint,
            },
            self.config_path,
            self.template_path,
        )
        persist_settings(
            "correction",
            {
                "mode": updated.correction.mode,
                "provider": updated.correction.provider,
                "endpoint": updated.correction.endpoint,
                "api_key_env": updated.correction.api_key_env,
                "model": updated.correction.model,
                "context_segments": updated.correction.context_segments,
                "timeout_seconds": updated.correction.timeout_seconds,
                "requests_per_minute": updated.correction.requests_per_minute,
                "max_tokens": updated.correction.max_tokens,
                "temperature": updated.correction.temperature,
            },
            self.config_path,
            self.template_path,
        )

        self.overlay.apply_settings(updated.overlay)
        self.click_action.setChecked(updated.overlay.click_through)
        self.display_actions[updated.overlay.display_mode].setChecked(True)
        if (
            previous.app.source_language,
            previous.app.target_language,
        ) != (
            updated.app.source_language,
            updated.app.target_language,
        ):
            self.service.set_route(
                updated.app.source_language,
                updated.app.target_language,
            )
            self.source_menu.clear()
            self.target_menu.clear()
            self._populate_languages(self.source_menu, source=True)
            self._populate_languages(self.target_menu, source=False)

        restart_reasons = []
        if previous.asr != updated.asr:
            restart_reasons.append("实时识别参数")
        if previous.app.history_enabled != updated.app.history_enabled:
            restart_reasons.append("历史记录开关")
        previous_provider = replace(previous.correction, mode=updated.correction.mode)
        correction_runtime_changed = previous_provider != updated.correction
        if correction_runtime_changed:
            restart_reasons.append("大模型服务")
            self.correction_scope_action.setText("大模型新配置将在重启后生效")
        elif previous.correction.mode != updated.correction.mode:
            try:
                self.service.set_correction_mode(updated.correction.mode)
            except ValueError:
                restart_reasons.append("大模型修正方式")
            else:
                self.correction_actions[updated.correction.mode].setChecked(True)
        if restart_reasons:
            QMessageBox.information(
                None,
                "设置已保存",
                "字幕外观与语言已立即应用。"
                + "、".join(restart_reasons)
                + "将在下次启动 LinguaRelay 时生效。",
            )

    def _persist_overlay_geometry(self, x: int, y: int, width: int, height: int) -> None:
        self.settings = replace(
            self.settings,
            overlay=replace(
                self.settings.overlay,
                x=x,
                y=y,
                width=width,
                height=height,
            ),
        )
        persist_overlay_geometry(
            x,
            y,
            width,
            height,
            self.config_path,
            self.template_path,
        )

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
        viewer = getattr(self, "_history_viewer", None)
        if viewer is None:
            viewer = HistoryWindow(self.paths.history_path, self.icon)
            viewer.export_requested.connect(self.export_history)
            self._history_viewer = viewer
        else:
            viewer.refresh()
        viewer.show()
        viewer.raise_()
        viewer.activateWindow()

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

    def remove_local_models(self) -> None:
        catalog_path = self.paths.resource_dir / "packaging" / "model-catalog.json"
        try:
            profiles = load_model_catalog(catalog_path)
        except Exception as error:
            QMessageBox.critical(None, "无法读取模型目录", str(error))
            return
        answer = QMessageBox.question(
            None,
            "删除本地模型",
            "将停止实时翻译并删除受 LinguaRelay 清单管理的语音识别与翻译模型，"
            "并清理对应下载缓存。\n\n"
            f"模型目录：{self.model_root}\n\n"
            "配置、字幕历史和目录中的其他文件会保留。软件将在完成后退出，是否继续？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return

        self.overlay.set_status("stopping", "正在停止实时翻译并释放模型…")
        try:
            self.service.stop()
            self.service.release_resources()
            gc.collect()
            removed: list[Path] = []
            for profile in profiles:
                removed.extend(uninstall_model_pack(self.model_root, profile.manifest))
                removed.extend(
                    self._remove_model_download_cache(profile.manifest.archive_name)
                )
        except Exception as error:
            QMessageBox.critical(
                None,
                "模型删除失败",
                f"未能安全删除本地模型：{error}\n\n请退出 LinguaRelay 后重试。",
            )
            return

        result = "本地模型和下载缓存已删除。" if removed else "未发现可删除的本地模型。"
        QMessageBox.information(
            None,
            "模型已卸载",
            result + "\n配置与字幕历史已保留；下次启动时可重新安装模型。",
        )
        self.app.quit()

    def _remove_model_download_cache(self, archive_name: str) -> tuple[Path, ...]:
        download_root = (self.paths.data_dir / "downloads").resolve(strict=False)
        archive = download_root / archive_name
        candidates = (archive, archive.with_suffix(archive.suffix + ".part"))
        removed: list[Path] = []
        for candidate in candidates:
            if candidate.resolve(strict=False).parent != download_root:
                raise ValueError(f"refusing to remove unsafe download path: {candidate}")
            if candidate.is_file() and not candidate.is_symlink():
                candidate.unlink()
                removed.append(candidate)
        return tuple(removed)

    def uninstall_application(self) -> None:
        uninstaller = Path(sys.executable).resolve().parent / "unins000.exe"
        if not getattr(sys, "frozen", False) or not uninstaller.is_file():
            QMessageBox.information(
                None,
                "卸载 LinguaRelay",
                "当前运行的不是已安装版本。请在 Windows“设置 → 应用 → 已安装的应用”中"
                "找到 LinguaRelay，或运行安装目录中的 unins000.exe。",
            )
            return
        answer = QMessageBox.question(
            None,
            "卸载 LinguaRelay",
            "即将退出软件并启动 Windows 卸载程序。是否继续？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        started = QProcess.startDetached(str(uninstaller), [])
        success = started[0] if isinstance(started, tuple) else bool(started)
        if not success:
            QMessageBox.critical(None, "无法启动卸载程序", str(uninstaller))
            return
        self.app.quit()

    def _update_status_action(self, state: str, message: str) -> None:
        self.status_action.setText(f"状态：{message}")
        self.tray.setToolTip(f"LinguaRelay · {message}")
        paused = state == "paused"
        self.overlay.set_paused(paused)
        if paused:
            self.pause_action.setText("继续")
        elif state not in {"error", "stopped"}:
            self.pause_action.setText("暂停")
        if state == "error":
            self.pause_action.setText("重试启动")
            self.tray.showMessage("LinguaRelay", message, QSystemTrayIcon.MessageIcon.Critical)
        elif state == "running" and not self._models_ready_notified:
            self._models_ready_notified = True
            self.tray.showMessage(
                "LinguaRelay 已就绪",
                "语音识别与翻译模型加载完成，正在监听系统音频。",
                QSystemTrayIcon.MessageIcon.Information,
            )

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

    def show_about(self) -> None:
        QMessageBox.about(
            None,
            "关于 LinguaRelay",
            f"LinguaRelay v{__version__}\n\n"
            "实时系统音频翻译字幕\n\n"
            "制作人：Leeleelee\n"
            "版权所有 © 2026 Leeleelee\n"
            "根据 MIT License 开源发布。",
        )

    def shutdown(self) -> None:
        self.hotkey.stop()
        with suppress(TimeoutError):
            self.service.stop()


def run_app(config_path: Path | None = None) -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName("LinguaRelay")
    app.setApplicationDisplayName("LinguaRelay")
    paths = AppPaths.discover()
    app.setWindowIcon(_make_icon(paths.resource_dir))
    journal = RuntimeJournal(paths.data_dir, version=__version__)
    recovery = journal.begin()
    journal.install_exception_hooks()
    development_models = Path.cwd() / "models"
    target_model_root = (
        paths.model_dir
        if getattr(sys, "frozen", False)
        else development_models
        if development_models.is_dir()
        else paths.model_dir
    )
    catalog_path = paths.resource_dir / "packaging" / "model-catalog.json"
    try:
        installation = ensure_model_installation(
            target_model_root,
            catalog_path,
            paths.data_dir / "downloads",
            _local_model_candidates(paths),
        )
        if installation is None:
            return 0
        active_config = config_path or paths.config_path
        persist_setting(
            "asr",
            "model",
            installation.profile.asr_model,
            active_config,
            paths.resource_dir / "config.example.toml",
        )
        controller = DesktopController(
            app,
            active_config,
            model_root=installation.root,
            recovered=recovery.previous_run_crashed,
        )
        controller.run()
        return app.exec()
    finally:
        journal.close_cleanly()


def _make_icon(resource_dir: Path) -> QIcon:
    return QIcon(str(resource_dir / "assets" / "linguarelay.ico"))


def _other_language(code: str) -> str:
    return next(candidate for candidate in SUPPORTED_LANGUAGES if candidate != code)


def _local_model_candidates(paths: AppPaths) -> tuple[Path, ...]:
    candidates: list[Path] = []
    configured = os.environ.get("LINGUA_RELAY_MODEL_DIR", "").strip()
    if configured:
        candidates.append(Path(configured))
    candidates.extend(
        (
            paths.model_dir,
            Path.cwd() / "models",
            Path(sys.executable).resolve().parent / "models",
            Path.home() / "LinguaRelay" / "models",
        )
    )
    return tuple(candidates)
