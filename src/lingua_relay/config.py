from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from lingua_relay.languages import SUPPORTED_LANGUAGES, normalize_language


@dataclass(frozen=True, slots=True)
class AppSettings:
    source_language: str = "en"
    target_language: str = "zh"
    history_enabled: bool = True
    history_path: Path = Path("data/history.jsonl")


@dataclass(frozen=True, slots=True)
class OverlaySettings:
    width: int = 920
    bottom_margin: int = 96
    opacity: float = 0.92
    click_through: bool = False


@dataclass(frozen=True, slots=True)
class AudioSettings:
    backend: str = "wasapi"
    device: str = "default"
    sample_rate: int = 16_000
    chunk_ms: int = 320
    raw_frame_ms: int = 20
    buffer_seconds: float = 4.0
    device_poll_seconds: float = 2.0
    reconnect_initial_seconds: float = 0.5
    reconnect_max_seconds: float = 5.0
    silence_dbfs: float = -55.0
    save_audio: bool = False


@dataclass(frozen=True, slots=True)
class AsrSettings:
    provider: str = "faster_whisper"
    model: str = "small"
    device: str = "cpu"
    compute_type: str = "int8"
    beam_size: int = 1
    vad_enabled: bool = True


@dataclass(frozen=True, slots=True)
class TranslationSettings:
    provider: str = "route_registry"
    model: str = "auto"


@dataclass(frozen=True, slots=True)
class CorrectionSettings:
    mode: str = "off"
    provider: str = "none"
    model: str = ""
    context_segments: int = 6
    timeout_seconds: float = 8.0


@dataclass(frozen=True, slots=True)
class Settings:
    app: AppSettings = field(default_factory=AppSettings)
    overlay: OverlaySettings = field(default_factory=OverlaySettings)
    audio: AudioSettings = field(default_factory=AudioSettings)
    asr: AsrSettings = field(default_factory=AsrSettings)
    translation: TranslationSettings = field(default_factory=TranslationSettings)
    correction: CorrectionSettings = field(default_factory=CorrectionSettings)

    @classmethod
    def load(cls, path: str | Path | None = None) -> Settings:
        if path is None:
            config_path = Path("config.toml")
            if not config_path.exists():
                settings = cls()
                settings.validate()
                return settings
        else:
            config_path = Path(path)
        if config_path.exists():
            with config_path.open("rb") as stream:
                raw = tomllib.load(stream)
            settings = cls.from_mapping(raw)
        else:
            raise FileNotFoundError(config_path)
        settings.validate()
        return settings

    @classmethod
    def from_mapping(cls, raw: dict[str, Any]) -> Settings:
        app_section = dict(raw.get("app", {}))
        for key in ("source_language", "target_language"):
            if key in app_section:
                app_section[key] = normalize_language(str(app_section[key]))
        return cls(
            app=_dataclass_from_section(AppSettings, app_section, {"history_path": Path}),
            overlay=_dataclass_from_section(OverlaySettings, raw.get("overlay", {})),
            audio=_dataclass_from_section(AudioSettings, raw.get("audio", {})),
            asr=_dataclass_from_section(AsrSettings, raw.get("asr", {})),
            translation=_dataclass_from_section(TranslationSettings, raw.get("translation", {})),
            correction=_dataclass_from_section(CorrectionSettings, raw.get("correction", {})),
        )

    def validate(self) -> None:
        supported = set(SUPPORTED_LANGUAGES)
        if self.app.source_language not in supported:
            raise ValueError(f"unsupported source_language: {self.app.source_language}")
        if self.app.target_language not in supported:
            raise ValueError(f"unsupported target_language: {self.app.target_language}")
        if self.app.source_language == self.app.target_language:
            raise ValueError("source_language and target_language must be different")
        if self.correction.mode not in {"off", "asynchronous", "live"}:
            raise ValueError("correction.mode must be off, asynchronous, or live")
        if self.audio.sample_rate <= 0 or self.audio.chunk_ms <= 0 or self.audio.raw_frame_ms <= 0:
            raise ValueError("audio sample_rate, chunk_ms, and raw_frame_ms must be positive")
        if self.audio.buffer_seconds < self.audio.chunk_ms / 1000:
            raise ValueError("audio.buffer_seconds must hold at least one output chunk")
        if self.audio.device_poll_seconds <= 0:
            raise ValueError("audio.device_poll_seconds must be positive")
        if not -120 <= self.audio.silence_dbfs < 0:
            raise ValueError("audio.silence_dbfs must be between -120 and 0")
        if not 0 < self.audio.reconnect_initial_seconds <= self.audio.reconnect_max_seconds:
            raise ValueError("audio reconnect interval is invalid")
        if not 0.2 <= self.overlay.opacity <= 1.0:
            raise ValueError("overlay.opacity must be between 0.2 and 1.0")


def _dataclass_from_section(
    target: type[Any],
    section: dict[str, Any],
    converters: dict[str, type[Any]] | None = None,
) -> Any:
    converters = converters or {}
    known_fields = target.__dataclass_fields__
    unknown = set(section) - set(known_fields)
    if unknown:
        names = ", ".join(sorted(unknown))
        raise ValueError(f"unknown settings for {target.__name__}: {names}")
    values = {
        name: converters.get(name, lambda value: value)(value) for name, value in section.items()
    }
    return target(**values)
