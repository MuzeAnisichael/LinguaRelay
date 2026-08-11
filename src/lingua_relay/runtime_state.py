from __future__ import annotations

import json
import os
import sys
import threading
import traceback
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from types import TracebackType
from typing import Any


@dataclass(frozen=True, slots=True)
class RecoveryStatus:
    previous_run_crashed: bool


class RuntimeJournal:
    """Atomic run marker and bounded local crash reports for recovery diagnostics."""

    def __init__(self, data_dir: str | Path, *, version: str) -> None:
        self.data_dir = Path(data_dir)
        self.version = version
        self.marker_path = self.data_dir / "running.json"
        self.crash_dir = self.data_dir / "crashes"
        self.session_id = uuid.uuid4().hex
        self._closed = False

    def begin(self) -> RecoveryStatus:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        status = RecoveryStatus(self.marker_path.exists())
        _atomic_json(
            self.marker_path,
            {
                "schema_version": 1,
                "session_id": self.session_id,
                "version": self.version,
                "pid": os.getpid(),
                "started_at": _now(),
            },
        )
        return status

    def record_crash(
        self,
        exception_type: type[BaseException],
        exception: BaseException,
        tb: TracebackType | None,
        *,
        thread_name: str = "main",
    ) -> Path:
        self.crash_dir.mkdir(parents=True, exist_ok=True)
        report = self.crash_dir / f"crash-{datetime.now(UTC):%Y%m%dT%H%M%SZ}-{self.session_id}.json"
        _atomic_json(
            report,
            {
                "schema_version": 1,
                "session_id": self.session_id,
                "version": self.version,
                "occurred_at": _now(),
                "thread": thread_name,
                "exception_type": exception_type.__name__,
                "message": str(exception)[:2_000],
                "traceback": "".join(traceback.format_exception(exception_type, exception, tb))[
                    -32_000:
                ],
            },
        )
        self._prune_reports(5)
        return report

    def install_exception_hooks(self) -> None:
        previous_sys_hook = sys.excepthook

        def sys_hook(
            exception_type: type[BaseException],
            exception: BaseException,
            tb: TracebackType | None,
        ) -> None:
            self.record_crash(exception_type, exception, tb)
            previous_sys_hook(exception_type, exception, tb)

        def thread_hook(args: threading.ExceptHookArgs) -> None:
            self.record_crash(
                args.exc_type,
                args.exc_value,
                args.exc_traceback,
                thread_name=args.thread.name if args.thread else "unknown",
            )

        sys.excepthook = sys_hook
        threading.excepthook = thread_hook

    def close_cleanly(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            raw: dict[str, Any] = json.loads(self.marker_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            raw = {}
        if raw.get("session_id") == self.session_id:
            self.marker_path.unlink(missing_ok=True)

    def _prune_reports(self, keep: int) -> None:
        reports = sorted(self.crash_dir.glob("crash-*.json"), reverse=True)
        for report in reports[keep:]:
            report.unlink(missing_ok=True)


def _atomic_json(path: Path, value: dict[str, Any]) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def _now() -> str:
    return datetime.now(UTC).isoformat()
