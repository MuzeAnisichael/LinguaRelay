from __future__ import annotations

import json
from pathlib import Path

from lingua_relay.correction.types import GlossaryEntry
from lingua_relay.languages import SUPPORTED_LANGUAGES, normalize_language

_MAX_GLOSSARY_BYTES = 1_000_000


def load_glossary(path: str | Path) -> tuple[GlossaryEntry, ...]:
    glossary_path = Path(path)
    if not glossary_path.exists():
        return ()
    if glossary_path.stat().st_size > _MAX_GLOSSARY_BYTES:
        raise ValueError("glossary exceeds the 1 MB safety limit")
    raw = json.loads(glossary_path.read_text(encoding="utf-8"))
    items = raw.get("entries") if isinstance(raw, dict) else raw
    if not isinstance(items, list):
        raise ValueError("glossary must be a JSON list or an object containing 'entries'")
    result: list[GlossaryEntry] = []
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            raise ValueError(f"glossary entry {index} must be an object")
        source = str(item.get("source", "")).strip()
        target = str(item.get("target", "")).strip()
        if not source or not target:
            raise ValueError(f"glossary entry {index} requires source and target")
        source_language = _optional_language(item.get("source_language"), index)
        target_language = _optional_language(item.get("target_language"), index)
        result.append(GlossaryEntry(source, target, source_language, target_language))
    return tuple(result)


def glossary_for_route(
    entries: tuple[GlossaryEntry, ...], source: str, target: str
) -> tuple[GlossaryEntry, ...]:
    return tuple(
        entry
        for entry in entries
        if (entry.source_language is None or entry.source_language == source)
        and (entry.target_language is None or entry.target_language == target)
    )


def _optional_language(value: object, index: int) -> str | None:
    if value is None or str(value).strip() in {"", "*"}:
        return None
    language = normalize_language(str(value))
    if language not in SUPPORTED_LANGUAGES:
        raise ValueError(f"unsupported language in glossary entry {index}: {value}")
    return language
