from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Language:
    code: str
    english_name: str
    native_name: str
    whisper_code: str


SUPPORTED_LANGUAGES: dict[str, Language] = {
    "zh": Language("zh", "Chinese (Simplified)", "简体中文", "zh"),
    "ja": Language("ja", "Japanese", "日本語", "ja"),
    "en": Language("en", "English", "English", "en"),
    "ko": Language("ko", "Korean", "한국어", "ko"),
}

LANGUAGE_ALIASES = {
    "zh-cn": "zh",
    "zh-hans": "zh",
    "jp": "ja",
    "kr": "ko",
}


def normalize_language(code: str) -> str:
    normalized = code.strip().lower().replace("_", "-")
    return LANGUAGE_ALIASES.get(normalized, normalized)


def translation_routes() -> tuple[tuple[str, str], ...]:
    return tuple(
        (source, target)
        for source in SUPPORTED_LANGUAGES
        for target in SUPPORTED_LANGUAGES
        if source != target
    )
