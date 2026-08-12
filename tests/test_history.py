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


def test_csv_export_keeps_revision_provenance(tmp_path: Path) -> None:
    history = JsonlHistory(tmp_path / "history.jsonl")
    history.append(
        CaptionEvent(
            "source",
            "revised",
            "en",
            "zh",
            "revised",
            0,
            revision=1,
            parent_revision=0,
            original_translation="fast",
            revision_source="llm_correction",
            processing_scope="cloud",
            correction_provider="openai_compatible",
            correction_model="model",
        )
    )

    content = history.export(tmp_path / "captions.csv").read_text(encoding="utf-8-sig")

    assert "original_translation" in content
    assert "fast" in content
    assert "openai_compatible" in content


def test_srt_export_uses_latest_revision_without_duplicate_caption(tmp_path: Path) -> None:
    history = JsonlHistory(tmp_path / "history.jsonl")
    fast = CaptionEvent(
        "source",
        "fast",
        "en",
        "zh",
        "final",
        1_000,
        ended_at_ms=2_000,
        segment_id="one",
    )
    revised = CaptionEvent(
        "source",
        "revised",
        "en",
        "zh",
        "revised",
        1_000,
        ended_at_ms=2_000,
        segment_id="one",
        revision=1,
    )
    history.append(fast)
    history.append(revised)

    content = history.export(tmp_path / "captions.srt").read_text(encoding="utf-8")

    assert "revised" in content
    assert "fast" not in content
    assert content.count(" --> ") == 1


def test_srt_export_keeps_segments_in_playback_order(tmp_path: Path) -> None:
    history = JsonlHistory(tmp_path / "history.jsonl")
    history.append(
        CaptionEvent(
            "first source",
            "first translation",
            "en",
            "zh",
            "final",
            1_000,
            ended_at_ms=2_000,
            segment_id="first",
        )
    )
    history.append(
        CaptionEvent(
            "second source",
            "second translation",
            "en",
            "zh",
            "final",
            3_000,
            ended_at_ms=4_000,
            segment_id="second",
        )
    )

    content = history.export(tmp_path / "captions.srt").read_text(encoding="utf-8")

    assert content.index("first translation") < content.index("second translation")
