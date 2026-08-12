from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from lingua_relay.ui.history_view import HistoryWindow, latest_history_rows  # noqa: E402


def test_latest_history_rows_collapses_llm_revisions() -> None:
    rows = (
        {
            "segment_id": "one",
            "revision": 0,
            "state": "final",
            "translated_text": "fast",
            "created_at": "2026-01-01T00:00:00+00:00",
        },
        {
            "segment_id": "one",
            "revision": 1,
            "state": "revised",
            "translated_text": "revised",
            "created_at": "2026-01-01T00:00:01+00:00",
        },
    )

    latest = latest_history_rows(rows)

    assert len(latest) == 1
    assert latest[0]["translated_text"] == "revised"


def test_history_window_searches_source_and_translation(tmp_path) -> None:
    app = QApplication.instance() or QApplication([])
    history = tmp_path / "history.jsonl"
    history.write_text(
        '{"segment_id":"one","revision":0,"state":"final",'
        '"source_language":"en","target_language":"zh",'
        '"source_text":"hello world","translated_text":"你好世界",'
        '"created_at":"2026-01-01T00:00:00+00:00"}\n',
        encoding="utf-8",
    )
    window = HistoryWindow(history)

    window.search.setText("你好")
    app.processEvents()
    assert window.table.rowCount() == 1

    window.search.setText("missing")
    app.processEvents()
    assert window.table.rowCount() == 0
