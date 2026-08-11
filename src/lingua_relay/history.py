from __future__ import annotations

import csv
import json
import shutil
import threading
from collections.abc import Iterable
from pathlib import Path

from lingua_relay.events import CaptionEvent


class JsonlHistory:
    """Append-only caption history. Revisions keep the same segment_id."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self._lock = threading.Lock()

    def append(self, event: CaptionEvent) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(event.to_dict(), ensure_ascii=False, separators=(",", ":"))
        with self._lock, self.path.open("a", encoding="utf-8", newline="\n") as stream:
            stream.write(line)
            stream.write("\n")
            stream.flush()

    def read_all(self) -> Iterable[dict[str, object]]:
        if not self.path.exists():
            return ()
        with self.path.open(encoding="utf-8") as stream:
            return tuple(json.loads(line) for line in stream if line.strip())

    def export(self, destination: str | Path) -> Path:
        target = Path(destination)
        target.parent.mkdir(parents=True, exist_ok=True)
        suffix = target.suffix.casefold()
        rows = tuple(self.read_all())
        if suffix == ".jsonl":
            if self.path.exists():
                shutil.copyfile(self.path, target)
            else:
                target.write_text("", encoding="utf-8")
        elif suffix == ".csv":
            fields = (
                "created_at",
                "source_language",
                "target_language",
                "source_text",
                "translated_text",
                "state",
                "segment_id",
                "error",
            )
            with target.open("w", encoding="utf-8-sig", newline="") as stream:
                writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore")
                writer.writeheader()
                writer.writerows(rows)
        elif suffix == ".srt":
            blocks: list[str] = []
            starts = [int(row.get("started_at_ms") or 0) for row in rows]
            origin = min(starts, default=0)
            for index, row in enumerate(rows, start=1):
                start = _srt_timestamp(int(row.get("started_at_ms") or 0) - origin)
                end = _srt_timestamp(int(row.get("ended_at_ms") or 0) - origin)
                text = str(row.get("translated_text") or row.get("source_text") or "")
                blocks.append(f"{index}\n{start} --> {end}\n{text}\n")
            target.write_text("\n".join(blocks), encoding="utf-8")
        else:
            raise ValueError("history export must use .jsonl, .csv, or .srt")
        return target


def _srt_timestamp(milliseconds: int) -> str:
    milliseconds = max(0, milliseconds)
    hours, remainder = divmod(milliseconds, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    seconds, millis = divmod(remainder, 1_000)
    return f"{hours:02}:{minutes:02}:{seconds:02},{millis:03}"
