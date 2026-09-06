"""Offline release diagnostics; never load user settings, models, or recordings."""

from __future__ import annotations

import argparse
import importlib
import json
import os
import sys
import tempfile
import time
import wave
from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from lingua_relay import __version__

REQUIRED_CHECKS = ("runtime_imports", "sqlite_project", "media_roundtrip", "qt_widgets_media")


def _runtime_imports(_root: Path) -> dict[str, Any]:
    modules = (
        "av",
        "ctranslate2",
        "faster_whisper",
        "httpx",
        "numpy",
        "onnxruntime",
        "opencc",
        "psutil",
        "sentencepiece",
        "soxr",
        "tokenizers",
    )
    if sys.platform == "win32":
        modules += ("pyaudiowpatch",)
    versions = {}
    for name in modules:
        module = importlib.import_module(name)
        versions[name] = str(getattr(module, "__version__", "imported"))
    return {"modules": versions}


def _sqlite_project(root: Path) -> dict[str, Any]:
    from lingua_relay.offline.project import Cue, OfflineProjectStore

    store = OfflineProjectStore(root / "projects")
    project = store.create_project(
        title="Self-test / 自测", kind="audio", source_language="en", target_language="zh"
    )
    cue = Cue(None, project.id, 0, 0, 1000, "Release check.", "发行检查。")
    store.replace_cues(project.id, [cue])
    restored = store.list_cues(project.id)
    if len(restored) != 1 or restored[0].translated_text != cue.translated_text:
        raise RuntimeError("SQLite project/cue roundtrip failed")
    return {"projects": len(store.list_projects()), "cues": len(restored)}


def _media_roundtrip(root: Path) -> dict[str, Any]:
    from lingua_relay.offline.media import decode_media_to_wav, export_audio, probe_media

    source = root / "silence.wav"
    with wave.open(str(source), "wb") as stream:
        stream.setnchannels(1)
        stream.setsampwidth(2)
        stream.setframerate(8000)
        stream.writeframes(b"\0\0" * 8000)
    normalized = decode_media_to_wav(source, root / "normalized.wav")
    exported = export_audio(normalized, root / "silence.mp3")
    info = probe_media(exported)
    decoded = decode_media_to_wav(exported, root / "decoded.wav")
    with wave.open(str(decoded), "rb") as stream:
        rate, channels, frames = (
            stream.getframerate(),
            stream.getnchannels(),
            stream.getnframes(),
        )
    if rate != 16000 or channels != 1 or not 14000 <= frames <= 18000:
        raise RuntimeError("WAV/MP3 decode roundtrip produced invalid PCM")
    if info.audio_streams != 1 or exported.stat().st_size == 0:
        raise RuntimeError("MP3 export/probe failed")
    return {"sample_rate": rate, "samples": frames, "mp3_bytes": exported.stat().st_size}


def _qt_widgets_media(root: Path) -> dict[str, Any]:
    from PySide6.QtCore import QCoreApplication, QEvent, QUrl, qVersion
    from PySide6.QtMultimedia import QMediaPlayer
    from PySide6.QtWidgets import QApplication

    from lingua_relay.config import OverlaySettings, Settings
    from lingua_relay.offline.project import OfflineProjectStore
    from lingua_relay.ui import settings_view
    from lingua_relay.ui.offline_workbench import OfflineWorkbench
    from lingua_relay.ui.overlay import CaptionOverlay

    # Windows uses its real platform plugin. No window is shown and media is
    # loaded, not played; success does not require a speaker/microphone device.
    app = QApplication.instance() or QApplication(["LinguaRelay self-test"])
    app.setQuitOnLastWindowClosed(False)
    overlay = CaptionOverlay(OverlaySettings())
    workbench = OfflineWorkbench(OfflineProjectStore(root / "qt-projects"))
    workbench.audio_output.setMuted(True)
    player = workbench.player
    settings_dialog = None
    try:
        # Build all settings controls without enumerating real processes or
        # microphones. This tests UI packaging, not the host's hardware state.
        device_manager = settings_view.WasapiDeviceManager
        process_manager = settings_view.AudioProcessManager
        settings_view.WasapiDeviceManager = lambda: SimpleNamespace(
            list_devices=lambda: (), list_microphones=lambda: ()
        )
        settings_view.AudioProcessManager = lambda: SimpleNamespace(list_processes=lambda: ())
        try:
            settings = Settings()
            settings_dialog = settings_view.SettingsDialog(settings)
        finally:
            settings_view.WasapiDeviceManager = device_manager
            settings_view.AudioProcessManager = process_manager
        if (
            settings_dialog.llm_routing.currentData()
            != settings.correction.openrouter_provider_sort
        ):
            raise RuntimeError("OpenRouter settings control did not initialize correctly")
        source = root / "silence.mp3"
        if not source.is_file():
            raise RuntimeError("Generated MP3 is missing; media roundtrip did not complete")
        player.setSource(QUrl.fromLocalFile(str(source.resolve())))
        deadline = time.monotonic() + 15.0
        loaded_states = {
            QMediaPlayer.MediaStatus.LoadedMedia,
            QMediaPlayer.MediaStatus.BufferedMedia,
        }
        while time.monotonic() < deadline:
            app.processEvents()
            if player.error() != QMediaPlayer.Error.NoError:
                raise RuntimeError(f"Qt media load failed: {player.errorString()}")
            if player.mediaStatus() in loaded_states and player.duration() > 0:
                break
            time.sleep(0.01)
        else:
            raise RuntimeError("Qt media did not load the generated MP3 within 15 seconds")
        if any(widget.isVisible() for widget in (overlay, workbench, settings_dialog)):
            raise RuntimeError("Self-test unexpectedly opened a visible window")
        return {
            "qt_version": qVersion(),
            "platform": app.platformName(),
            "media_duration_ms": player.duration(),
            "windows_shown": False,
            "audio_played": False,
            "settings_dialog_loaded": True,
        }
    finally:
        player.stop()
        player.setSource(QUrl())
        overlay.close()
        workbench.close()
        overlay.deleteLater()
        workbench.deleteLater()
        if settings_dialog is not None:
            settings_dialog.close()
            settings_dialog.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        app.processEvents()


CHECKS: tuple[tuple[str, Callable[[Path], dict[str, Any]]], ...] = (
    ("runtime_imports", _runtime_imports),
    ("sqlite_project", _sqlite_project),
    ("media_roundtrip", _media_roundtrip),
    ("qt_widgets_media", _qt_widgets_media),
)


def run_self_test(report_path: Path) -> int:
    report_path = report_path.resolve()
    report_path.parent.mkdir(parents=True, exist_ok=True)
    started = time.perf_counter()
    report: dict[str, Any] = {
        "schema_version": 1,
        "version": __version__,
        "frozen": bool(getattr(sys, "frozen", False)),
        "status": "failed",
        "checks": [],
    }
    # Place all disposable files next to the caller-selected report, never in
    # LinguaRelay's real configuration, model, recording, or project folders.
    with tempfile.TemporaryDirectory(
        prefix="linguarelay-self-test-", dir=report_path.parent
    ) as tmp:
        root = Path(tmp)
        isolated = {
            "APPDATA": str(root / "roaming"),
            "LOCALAPPDATA": str(root / "local"),
            "HF_HOME": str(root / "huggingface"),
            "HF_HUB_OFFLINE": "1",
            "TRANSFORMERS_OFFLINE": "1",
        }
        previous = {name: os.environ.get(name) for name in isolated}
        os.environ.update(isolated)
        try:
            for name, check in CHECKS:
                tick = time.perf_counter()
                result: dict[str, Any] = {"name": name, "status": "passed"}
                try:
                    result["details"] = check(root)
                except Exception as error:
                    result.update(status="failed", error=f"{type(error).__name__}: {error}")
                result["elapsed_ms"] = round((time.perf_counter() - tick) * 1000, 2)
                report["checks"].append(result)
        finally:
            for name, value in previous.items():
                if value is None:
                    os.environ.pop(name, None)
                else:
                    os.environ[name] = value
    passed = all(check["status"] == "passed" for check in report["checks"])
    report["status"] = "passed" if passed else "failed"
    report["elapsed_ms"] = round((time.perf_counter() - started) * 1000, 2)
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return 0 if passed else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run isolated offline release diagnostics")
    parser.add_argument("report", type=Path, help="JSON diagnostic report destination")
    args = parser.parse_args(argv)
    return run_self_test(args.report)


if __name__ == "__main__":
    raise SystemExit(main())
