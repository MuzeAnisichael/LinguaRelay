from __future__ import annotations

import json
from pathlib import Path


def persist_audio_device(
    device_id: str,
    config_path: str | Path = "config.toml",
    template_path: str | Path = "config.example.toml",
) -> Path:
    path = Path(config_path)
    if path.exists():
        lines = path.read_text(encoding="utf-8").splitlines()
    else:
        template = Path(template_path)
        lines = template.read_text(encoding="utf-8").splitlines() if template.exists() else []

    encoded = json.dumps(device_id, ensure_ascii=False)
    section = ""
    replaced = False
    audio_section_end = len(lines)
    for index, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            if section == "audio" and audio_section_end == len(lines):
                audio_section_end = index
            section = stripped[1:-1].strip()
            continue
        if section == "audio" and stripped.startswith("device") and "=" in stripped:
            lines[index] = f"device = {encoded}"
            replaced = True
            break

    if not replaced:
        if "[audio]" not in lines:
            if lines and lines[-1]:
                lines.append("")
            lines.extend(("[audio]", f"device = {encoded}"))
        else:
            lines.insert(audio_section_end, f"device = {encoded}")

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path
