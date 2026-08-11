from __future__ import annotations

import json
from pathlib import Path

from lingua_relay.runtime_state import RuntimeJournal


def test_runtime_journal_detects_unclean_run_and_cleans_marker(tmp_path: Path) -> None:
    first = RuntimeJournal(tmp_path, version="0.1.0")
    assert not first.begin().previous_run_crashed
    second = RuntimeJournal(tmp_path, version="0.1.0")
    assert second.begin().previous_run_crashed
    second.close_cleanly()
    assert not (tmp_path / "running.json").exists()


def test_runtime_journal_writes_bounded_crash_report(tmp_path: Path) -> None:
    journal = RuntimeJournal(tmp_path, version="0.1.0")
    journal.begin()
    try:
        raise RuntimeError("simulated")
    except RuntimeError as error:
        report = journal.record_crash(type(error), error, error.__traceback__)
    payload = json.loads(report.read_text(encoding="utf-8"))
    assert payload["exception_type"] == "RuntimeError"
    assert payload["message"] == "simulated"
