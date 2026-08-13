from __future__ import annotations

import sys
from types import SimpleNamespace

from lingua_relay.audio.processes import AudioProcessManager


class _Process:
    def __init__(self, process_id: int, name: str) -> None:
        self.info = {"pid": process_id, "name": name}


def test_process_manager_recovers_a_restarted_process_by_name(monkeypatch) -> None:
    fake = SimpleNamespace(
        AccessDenied=RuntimeError,
        NoSuchProcess=RuntimeError,
        process_iter=lambda _fields: (
            _Process(120, "meeting.exe"),
            _Process(180, "meeting.exe"),
            _Process(220, "browser.exe"),
        ),
    )
    monkeypatch.setitem(sys.modules, "psutil", fake)

    target = AudioProcessManager().resolve(99, "meeting.exe")

    assert target.process_id == 180
    assert target.name == "meeting.exe"
