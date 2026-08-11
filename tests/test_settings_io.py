from pathlib import Path

from lingua_relay.config import Settings
from lingua_relay.settings_io import persist_audio_device, persist_display_mode, persist_route


def test_persists_device_in_existing_audio_section(tmp_path: Path) -> None:
    config = tmp_path / "config.toml"
    config.write_text(
        '[app]\nsource_language="en"\ntarget_language="zh"\n\n'
        '[audio]\ndevice = "default"\nchunk_ms = 320\n',
        encoding="utf-8",
    )

    persist_audio_device("wasapi:耳机", config)

    assert Settings.load(config).audio.device == "wasapi:耳机"
    assert config.read_text(encoding="utf-8").count("device =") == 1


def test_creates_audio_section_without_template(tmp_path: Path) -> None:
    config = tmp_path / "config.toml"

    persist_audio_device("default", config, tmp_path / "missing.toml")

    assert Settings.load(config).audio.device == "default"


def test_persists_route_and_display_mode(tmp_path: Path) -> None:
    config = tmp_path / "config.toml"

    persist_route("ja", "ko", config, tmp_path / "missing.toml")
    persist_display_mode("translated", config, tmp_path / "missing.toml")

    settings = Settings.load(config)
    assert (settings.app.source_language, settings.app.target_language) == ("ja", "ko")
    assert settings.overlay.display_mode == "translated"
