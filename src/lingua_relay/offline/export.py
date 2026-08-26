from __future__ import annotations

import csv
import json
from pathlib import Path

from lingua_relay.offline.media import export_audio
from lingua_relay.offline.project import Cue, OfflineProjectStore


def export_project(store: OfflineProjectStore, project_id: str, destination: str | Path) -> Path:
    project = store.get_project(project_id)
    target = Path(destination)
    target.parent.mkdir(parents=True, exist_ok=True)
    suffix = target.suffix.lower()
    if suffix in {".wav", ".flac", ".mp3"}:
        if project.audio_path is None:
            raise ValueError("project has no processed audio")
        return export_audio(project.audio_path, target)
    cues = store.list_cues(project_id)
    if not cues:
        raise ValueError("project has no captions to export")
    if suffix == ".vtt":
        target.write_text(_webvtt(cues), encoding="utf-8-sig")
    elif suffix == ".srt":
        target.write_text(_srt(cues), encoding="utf-8-sig")
    elif suffix == ".ass":
        target.write_text(_ass(cues), encoding="utf-8-sig")
    elif suffix == ".txt":
        target.write_text(
            "\n".join(cue.translated_text or cue.source_text for cue in cues) + "\n",
            encoding="utf-8",
        )
    elif suffix == ".csv":
        with target.open("w", encoding="utf-8-sig", newline="") as stream:
            writer = csv.writer(stream)
            writer.writerow(("start_ms", "end_ms", "source_text", "translated_text"))
            writer.writerows(
                (cue.start_ms, cue.end_ms, cue.source_text, cue.translated_text) for cue in cues
            )
    elif suffix == ".jsonl":
        with target.open("w", encoding="utf-8") as stream:
            for cue in cues:
                stream.write(
                    json.dumps(
                        {
                            "start_ms": cue.start_ms,
                            "end_ms": cue.end_ms,
                            "source_text": cue.source_text,
                            "translated_text": cue.translated_text,
                            "confidence": cue.confidence,
                            "words": json.loads(cue.words_json),
                        },
                        ensure_ascii=False,
                    )
                    + "\n"
                )
    else:
        raise ValueError("supported exports: MP3, WAV, FLAC, VTT, SRT, ASS, TXT, CSV, JSONL")
    return target


def _webvtt(cues: tuple[Cue, ...]) -> str:
    blocks = ["WEBVTT", ""]
    for cue in cues:
        blocks.extend(
            (
                f"{_timestamp(cue.start_ms, '.')} --> {_timestamp(cue.end_ms, '.')}",
                cue.translated_text or cue.source_text,
                "",
            )
        )
    return "\n".join(blocks)


def _srt(cues: tuple[Cue, ...]) -> str:
    blocks: list[str] = []
    for index, cue in enumerate(cues, 1):
        blocks.extend(
            (
                str(index),
                f"{_timestamp(cue.start_ms, ',')} --> {_timestamp(cue.end_ms, ',')}",
                cue.translated_text or cue.source_text,
                "",
            )
        )
    return "\n".join(blocks)


def _ass(cues: tuple[Cue, ...]) -> str:
    lines = [
        "[Script Info]",
        "ScriptType: v4.00+",
        "PlayResX: 1920",
        "PlayResY: 1080",
        "",
        "[V4+ Styles]",
        "Format: Name,Fontname,Fontsize,PrimaryColour,OutlineColour,BorderStyle,"
        "Outline,Shadow,Alignment,MarginL,MarginR,MarginV,Encoding",
        "Style: Default,Microsoft YaHei UI,52,&H00FFFFFF,&H80000000,1,2,0,2,40,40,36,1",
        "",
        "[Events]",
        "Format: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text",
    ]
    for cue in cues:
        text = (cue.translated_text or cue.source_text).replace("\n", r"\N")
        lines.append(
            f"Dialogue: 0,{_ass_timestamp(cue.start_ms)},{_ass_timestamp(cue.end_ms)},"
            f"Default,,0,0,0,,{text}"
        )
    return "\n".join(lines) + "\n"


def _timestamp(milliseconds: int, decimal: str) -> str:
    hours, remainder = divmod(max(0, milliseconds), 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    seconds, millis = divmod(remainder, 1000)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}{decimal}{millis:03d}"


def _ass_timestamp(milliseconds: int) -> str:
    hours, remainder = divmod(max(0, milliseconds), 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    seconds, millis = divmod(remainder, 1000)
    return f"{hours}:{minutes:02d}:{seconds:02d}.{millis // 10:02d}"
