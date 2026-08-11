from pathlib import Path

from lingua_relay.events import CaptionEvent
from lingua_relay.history import JsonlHistory


def test_appends_unicode_caption(tmp_path: Path) -> None:
    path = tmp_path / "history.jsonl"
    history = JsonlHistory(path)
    event = CaptionEvent(
        source_text="Hello",
        translated_text="你好",
        source_language="en",
        target_language="zh-CN",
        state="final",
        started_at_ms=0,
        ended_at_ms=500,
    )

    history.append(event)

    rows = list(history.read_all())
    assert rows[0]["translated_text"] == "你好"
    assert rows[0]["segment_id"] == event.segment_id


def test_missing_history_is_empty(tmp_path: Path) -> None:
    assert tuple(JsonlHistory(tmp_path / "missing.jsonl").read_all()) == ()


def test_exports_csv_and_srt(tmp_path: Path) -> None:
    history = JsonlHistory(tmp_path / "history.jsonl")
    history.append(
        CaptionEvent(
            source_text="Hello",
            translated_text="你好",
            source_language="en",
            target_language="zh",
            state="final",
            started_at_ms=1_000,
            ended_at_ms=2_500,
        )
    )

    csv_path = history.export(tmp_path / "captions.csv")
    srt_path = history.export(tmp_path / "captions.srt")

    assert "translated_text" in csv_path.read_text(encoding="utf-8-sig")
    assert "00:00:00,000 --> 00:00:01,500" in srt_path.read_text(encoding="utf-8")
    assert "你好" in srt_path.read_text(encoding="utf-8")
