from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass, field, replace
from ipaddress import ip_address
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

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
    height: int = 180
    x: int | None = None
    y: int | None = None
    bottom_margin: int = 96
    opacity: float = 0.92
    click_through: bool = False
    display_mode: str = "bilingual"
    position: str = "bottom"
    source_font_size: int = 12
    translation_font_size: int = 18
    source_font_family: str = "Segoe UI"
    translation_font_family: str = "Microsoft YaHei UI"
    source_color: str = "#D5DAE3"
    translation_color: str = "#FFFFFF"
    background_color: str = "#101218"
    background_opacity: float = 0.88
    status_visible: bool = True
    retention_seconds: float = 8.0
    toggle_shortcut: str = "Ctrl+Alt+L"


@dataclass(frozen=True, slots=True)
class AudioSettings:
    backend: str = "wasapi"
    source: str = "system"
    device: str = "default"
    microphone_device: str = "default"
    process_id: int = 0
    process_name: str = ""
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
    revision: str = ""
    device: str = "auto"
    compute_type: str = "auto"
    beam_size: int = 1
    repetition_penalty: float = 1.05
    no_repeat_ngram_size: int = 3
    compression_ratio_threshold: float = 2.4
    log_prob_threshold: float = -1.0
    no_speech_threshold: float = 0.6
    vad_enabled: bool = True
    vad_threshold: float = 0.5
    min_speech_ms: int = 320
    min_silence_ms: int = 640
    preferred_silence_ms: int = 320
    partial_interval_ms: int = 320
    adaptive_partial_enabled: bool = True
    punctuation_boundary_enabled: bool = True
    punctuation_boundary_min_seconds: float = 0.96
    suppress_credit_hallucinations: bool = True
    context_hint: str = ""
    preferred_segment_seconds: float = 3.2
    max_caption_seconds: float = 6.0
    max_window_seconds: float = 6.0
    max_segment_seconds: float = 6.0
    inference_queue_capacity: int = 4
    event_queue_capacity: int = 16


@dataclass(frozen=True, slots=True)
class TranslationSettings:
    provider: str = "m2m100_ct2"
    model: str = "facebook/m2m100_418M"
    revision: str = "55c2e61bbf05dfb8d7abccdc3fae6fc8512fd636"
    model_path: Path = Path("models/m2m100_418m_ct2")
    device: str = "auto"
    compute_type: str = "auto"
    beam_size: int = 1
    repetition_penalty: float = 1.05
    no_repeat_ngram_size: int = 3
    max_input_tokens: int = 256
    max_decoding_length: int = 256
    cache_size: int = 512
    queue_capacity: int = 4
    event_queue_capacity: int = 16
    translate_partials: bool = True


@dataclass(frozen=True, slots=True)
class CorrectionSettings:
    mode: str = "off"
    provider: str = "none"
    endpoint: str = "http://127.0.0.1:8080/v1"
    api_key_env: str = "LINGUA_RELAY_API_KEY"
    model: str = ""
    glossary_path: Path = Path("data/glossary.json")
    context_segments: int = 6
    timeout_seconds: float = 8.0
    requests_per_minute: int = 30
    queue_capacity: int = 8
    event_queue_capacity: int = 16
    failure_threshold: int = 3
    recovery_seconds: float = 30.0
    max_output_chars: int = 4_000
    max_tokens: int = 512
    temperature: float = 0.1


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
            translation=_dataclass_from_section(
                TranslationSettings,
                raw.get("translation", {}),
                {"model_path": Path},
            ),
            correction=_dataclass_from_section(
                CorrectionSettings,
                raw.get("correction", {}),
                {"glossary_path": Path},
            ),
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
        if self.correction.provider not in {"none", "local", "openai_compatible"}:
            raise ValueError("correction.provider must be none, local, or openai_compatible")
        if self.correction.mode != "off" and self.correction.provider == "none":
            raise ValueError("enabled correction.mode requires a correction provider")
        if self.correction.provider != "none":
            _validate_correction_endpoint(self.correction.provider, self.correction.endpoint)
            if not self.correction.model.strip():
                raise ValueError("correction.model must not be empty when a provider is configured")
        if not self.correction.api_key_env.isidentifier():
            raise ValueError("correction.api_key_env must be an environment variable name")
        if self.correction.context_segments < 0:
            raise ValueError("correction.context_segments must not be negative")
        if self.correction.timeout_seconds <= 0:
            raise ValueError("correction.timeout_seconds must be positive")
        if self.correction.requests_per_minute < 1:
            raise ValueError("correction.requests_per_minute must be positive")
        if self.correction.queue_capacity < 2 or self.correction.event_queue_capacity < 2:
            raise ValueError("correction queues must have capacity of at least two")
        if self.correction.failure_threshold < 1 or self.correction.recovery_seconds <= 0:
            raise ValueError("correction circuit-breaker settings are invalid")
        if self.correction.max_output_chars < 1 or self.correction.max_tokens < 1:
            raise ValueError("correction output limits must be positive")
        if not 0 <= self.correction.temperature <= 2:
            raise ValueError("correction.temperature must be between 0 and 2")
        if self.audio.sample_rate <= 0 or self.audio.chunk_ms <= 0 or self.audio.raw_frame_ms <= 0:
            raise ValueError("audio sample_rate, chunk_ms, and raw_frame_ms must be positive")
        if self.audio.source not in {"system", "process", "microphone"}:
            raise ValueError("audio.source must be system, process, or microphone")
        if self.audio.source == "process" and (
            self.audio.process_id < 1 and not self.audio.process_name.strip()
        ):
            raise ValueError("process audio requires a process id or process name")
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
        if not 0.1 <= self.overlay.background_opacity <= 1.0:
            raise ValueError("overlay.background_opacity must be between 0.1 and 1.0")
        if not 0 <= self.overlay.retention_seconds <= 120:
            raise ValueError("overlay.retention_seconds must be between 0 and 120")
        if self.overlay.width < 360 or self.overlay.height < 96:
            raise ValueError("overlay dimensions must be at least 360 x 96")
        if (self.overlay.x is None) != (self.overlay.y is None):
            raise ValueError("overlay.x and overlay.y must be configured together")
        if self.overlay.display_mode not in {"translated", "bilingual"}:
            raise ValueError("overlay.display_mode must be translated or bilingual")
        if self.overlay.position not in {"top", "bottom"}:
            raise ValueError("overlay.position must be top or bottom")
        if self.overlay.source_font_size < 8 or self.overlay.translation_font_size < 8:
            raise ValueError("overlay font sizes must be at least 8")
        if (
            not self.overlay.source_font_family.strip()
            or not self.overlay.translation_font_family.strip()
        ):
            raise ValueError("overlay font families must not be empty")
        for name, color in (
            ("source_color", self.overlay.source_color),
            ("translation_color", self.overlay.translation_color),
            ("background_color", self.overlay.background_color),
        ):
            if re.fullmatch(r"#[0-9a-fA-F]{6}", color) is None:
                raise ValueError(f"overlay.{name} must be a #RRGGBB color")
        if self.asr.provider != "faster_whisper":
            raise ValueError("asr.provider must be faster_whisper in M2")
        if not self.asr.model or self.asr.model.endswith(".en"):
            raise ValueError("asr.model must be a multilingual Whisper model")
        if self.asr.device not in {"auto", "cpu", "cuda"}:
            raise ValueError("asr.device must be auto, cpu, or cuda")
        if self.asr.compute_type not in {
            "auto",
            "default",
            "float16",
            "float32",
            "int8",
            "int8_float16",
            "int8_float32",
        }:
            raise ValueError("unsupported asr.compute_type")
        if self.asr.beam_size < 1:
            raise ValueError("asr.beam_size must be positive")
        if self.asr.repetition_penalty < 1:
            raise ValueError("asr.repetition_penalty must be at least one")
        if self.asr.no_repeat_ngram_size < 0:
            raise ValueError("asr.no_repeat_ngram_size must not be negative")
        if self.asr.compression_ratio_threshold <= 0:
            raise ValueError("asr.compression_ratio_threshold must be positive")
        if not -20 <= self.asr.log_prob_threshold <= 0:
            raise ValueError("asr.log_prob_threshold must be between -20 and 0")
        if not 0 <= self.asr.no_speech_threshold <= 1:
            raise ValueError("asr.no_speech_threshold must be between 0 and 1")
        if not 0 < self.asr.vad_threshold < 1:
            raise ValueError("asr.vad_threshold must be between 0 and 1")
        if (
            self.asr.min_speech_ms <= 0
            or self.asr.min_silence_ms <= 0
            or self.asr.preferred_silence_ms <= 0
        ):
            raise ValueError("ASR speech and silence durations must be positive")
        if self.asr.preferred_silence_ms > self.asr.min_silence_ms:
            raise ValueError("asr.preferred_silence_ms must not exceed min_silence_ms")
        if self.asr.partial_interval_ms < self.audio.chunk_ms:
            raise ValueError("asr.partial_interval_ms must be at least audio.chunk_ms")
        if self.asr.partial_interval_ms % self.audio.chunk_ms:
            raise ValueError("asr.partial_interval_ms must be a multiple of audio.chunk_ms")
        if len(self.asr.context_hint) > 1_000:
            raise ValueError("asr.context_hint must not exceed 1000 characters")
        if self.asr.punctuation_boundary_min_seconds < self.asr.partial_interval_ms / 1000:
            raise ValueError("asr.punctuation_boundary_min_seconds is too short")
        if self.asr.max_window_seconds < self.asr.partial_interval_ms / 1000:
            raise ValueError("asr.max_window_seconds is too short")
        if self.asr.max_segment_seconds < self.asr.max_window_seconds:
            raise ValueError("asr.max_segment_seconds must cover max_window_seconds")
        if not 0 < self.asr.preferred_segment_seconds <= self.asr.max_segment_seconds:
            raise ValueError("asr.preferred_segment_seconds must fit inside max_segment_seconds")
        if self.asr.max_caption_seconds < self.asr.partial_interval_ms / 1000:
            raise ValueError("asr.max_caption_seconds is too short")
        if self.asr.inference_queue_capacity < 2 or self.asr.event_queue_capacity < 2:
            raise ValueError("ASR queues must have capacity of at least two")
        if self.translation.provider != "m2m100_ct2":
            raise ValueError("translation.provider must be m2m100_ct2 in M3")
        if not self.translation.model or not self.translation.revision:
            raise ValueError("translation model and revision must not be empty")
        if self.translation.device not in {"auto", "cpu", "cuda"}:
            raise ValueError("translation.device must be auto, cpu, or cuda")
        if self.translation.compute_type not in {
            "auto",
            "default",
            "float16",
            "float32",
            "int8",
            "int8_float16",
            "int8_float32",
        }:
            raise ValueError("unsupported translation.compute_type")
        if self.translation.beam_size < 1:
            raise ValueError("translation.beam_size must be positive")
        if self.translation.repetition_penalty < 1:
            raise ValueError("translation.repetition_penalty must be at least one")
        if self.translation.no_repeat_ngram_size < 0:
            raise ValueError("translation.no_repeat_ngram_size must not be negative")
        if self.translation.max_input_tokens < 8 or self.translation.max_decoding_length < 8:
            raise ValueError("translation token limits must be at least eight")
        if self.translation.cache_size < 0:
            raise ValueError("translation.cache_size must not be negative")
        if self.translation.queue_capacity < 2 or self.translation.event_queue_capacity < 2:
            raise ValueError("translation queues must have capacity of at least two")


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


def _validate_correction_endpoint(provider: str, endpoint: str) -> None:
    parsed = urlsplit(endpoint)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("correction.endpoint must be an absolute HTTP(S) URL")
    try:
        _ = parsed.port
    except ValueError as error:
        raise ValueError("correction.endpoint has an invalid port") from error
    if parsed.username or parsed.password or parsed.fragment:
        raise ValueError("correction.endpoint must not contain credentials or a fragment")
    if provider == "openai_compatible" and parsed.scheme != "https":
        raise ValueError("openai_compatible correction.endpoint must use HTTPS")
    if provider != "local":
        return
    host = parsed.hostname.casefold().rstrip(".")
    is_loopback = host == "localhost"
    if not is_loopback:
        try:
            is_loopback = ip_address(host).is_loopback
        except ValueError:
            is_loopback = False
    if not is_loopback:
        raise ValueError("local correction.endpoint must use localhost or a loopback IP")


def migrate_legacy_realtime_defaults(settings: Settings) -> tuple[Settings, bool]:
    """Move unchanged v0.1.2 cadence defaults to the v0.1.5 readability profile."""
    legacy = settings.asr
    if (
        legacy.partial_interval_ms,
        legacy.punctuation_boundary_min_seconds,
        legacy.preferred_segment_seconds,
        legacy.max_caption_seconds,
        legacy.max_window_seconds,
        legacy.max_segment_seconds,
    ) != (320, 1.2, 6.0, 10.0, 10.0, 10.0):
        return settings, False
    upgraded = replace(
        legacy,
        adaptive_partial_enabled=True,
        punctuation_boundary_min_seconds=0.96,
        preferred_segment_seconds=3.2,
        max_caption_seconds=6.0,
        max_window_seconds=6.0,
        max_segment_seconds=6.0,
    )
    return replace(settings, asr=upgraded), True
