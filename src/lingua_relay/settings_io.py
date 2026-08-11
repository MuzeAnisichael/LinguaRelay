from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def persist_audio_device(
    device_id: str,
    config_path: str | Path = "config.toml",
    template_path: str | Path = "config.example.toml",
) -> Path:
    return persist_setting("audio", "device", device_id, config_path, template_path)


def persist_route(
    source: str,
    target: str,
    config_path: str | Path = "config.toml",
    template_path: str | Path = "config.example.toml",
) -> Path:
    path = persist_setting("app", "source_language", source, config_path, template_path)
    return persist_setting("app", "target_language", target, path, template_path)


def persist_display_mode(
    display_mode: str,
    config_path: str | Path = "config.toml",
    template_path: str | Path = "config.example.toml",
) -> Path:
    if display_mode not in {"translated", "bilingual"}:
        raise ValueError("display_mode must be translated or bilingual")
    return persist_setting("overlay", "display_mode", display_mode, config_path, template_path)


def persist_setting(
    section_name: str,
    key: str,
    value: Any,
    config_path: str | Path = "config.toml",
    template_path: str | Path = "config.example.toml",
) -> Path:
    path = Path(config_path)
    if path.exists():
        lines = path.read_text(encoding="utf-8").splitlines()
    else:
        template = Path(template_path)
        lines = template.read_text(encoding="utf-8").splitlines() if template.exists() else []

    encoded = _toml_value(value)
    section = ""
    replaced = False
    section_end = len(lines)
    for index, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            if section == section_name and section_end == len(lines):
                section_end = index
            section = stripped[1:-1].strip()
            continue
        if section == section_name and stripped.startswith(key) and "=" in stripped:
            lines[index] = f"{key} = {encoded}"
            replaced = True
            break

    if not replaced:
        header = f"[{section_name}]"
        if header not in lines:
            if lines and lines[-1]:
                lines.append("")
            lines.extend((header, f"{key} = {encoded}"))
        else:
            lines.insert(section_end, f"{key} = {encoded}")

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _toml_value(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, Path):
        value = str(value).replace("\\", "/")
    return json.dumps(str(value), ensure_ascii=False)
