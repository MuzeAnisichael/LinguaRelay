from __future__ import annotations

import json
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
