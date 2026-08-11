from pathlib import Path

import pytest

from lingua_relay.config import Settings


def test_defaults_match_first_language_route() -> None:
    settings = Settings.load()

    assert settings.app.source_language == "en"
    assert settings.app.target_language == "zh"
    assert settings.correction.mode == "off"
    assert settings.audio.save_audio is False
    assert settings.asr.device == "auto"
    assert settings.overlay.display_mode == "bilingual"
    assert settings.translation.provider == "m2m100_ct2"


def test_loads_toml_and_converts_history_path(tmp_path: Path) -> None:
    config = tmp_path / "config.toml"
    config.write_text(
        '[app]\nsource_language="ja"\ntarget_language="zh-CN"\nhistory_path="captions.jsonl"\n',
        encoding="utf-8",
    )

    settings = Settings.load(config)

    assert settings.app.source_language == "ja"
    assert settings.app.target_language == "zh"
    assert settings.app.history_path == Path("captions.jsonl")


def test_rejects_unknown_fields() -> None:
    with pytest.raises(ValueError, match="unknown settings"):
        Settings.from_mapping({"audio": {"surprise": True}})


def test_rejects_same_language() -> None:
    settings = Settings.from_mapping({"app": {"source_language": "en", "target_language": "en"}})

    with pytest.raises(ValueError, match="must be different"):
        settings.validate()


def test_rejects_invalid_silence_threshold() -> None:
    settings = Settings.from_mapping({"audio": {"silence_dbfs": 1}})

    with pytest.raises(ValueError, match="silence_dbfs"):
        settings.validate()


def test_rejects_english_only_asr_model() -> None:
    settings = Settings.from_mapping({"asr": {"model": "small.en"}})

    with pytest.raises(ValueError, match="multilingual"):
        settings.validate()


def test_rejects_partial_interval_that_does_not_align_to_audio_chunks() -> None:
    settings = Settings.from_mapping({"asr": {"partial_interval_ms": 500}})

    with pytest.raises(ValueError, match="multiple"):
        settings.validate()
