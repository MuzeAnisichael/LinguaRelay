from pathlib import Path

from lingua_relay.config import CorrectionSettings
from lingua_relay.correction.batch import revise_history
from lingua_relay.correction.types import CorrectionRequest, RevisionResult
from lingua_relay.events import CaptionEvent
from lingua_relay.history import JsonlHistory


class BatchProvider:
    name = "openai_compatible"
    model = "cloud-mock"
    scope = "cloud"

    def revise(self, request: CorrectionRequest) -> RevisionResult:
        return RevisionResult(
            request.event.translated_text + "!", 2.0, self.name, self.model, self.scope
        )


def test_batch_revision_copies_originals_and_appends_traceable_revisions(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.jsonl"
    output = tmp_path / "revised.jsonl"
    history = JsonlHistory(source)
    for index in range(2):
        history.append(
            CaptionEvent(
                f"source {index}",
                f"fast {index}",
                "en",
                "zh",
                "final",
                index * 100,
                segment_id=f"segment-{index}",
            )
        )

    report = revise_history(
        source,
        output,
        BatchProvider(),
        CorrectionSettings(
            provider="openai_compatible",
            endpoint="https://example.test/v1",
            model="cloud-mock",
            glossary_path=tmp_path / "missing.json",
        ),
    )

    rows = tuple(JsonlHistory(output).read_all())
    assert report.revisions_written == 2
    assert len(rows) == 4
    assert [row["state"] for row in rows[:2]] == ["final", "final"]
    assert [row["state"] for row in rows[2:]] == ["revised", "revised"]
    assert rows[2]["original_translation"] == "fast 0"
    assert rows[2]["processing_scope"] == "cloud"


def test_batch_refuses_to_overwrite_input(tmp_path: Path) -> None:
    path = tmp_path / "history.jsonl"

    try:
        revise_history(path, path, BatchProvider(), CorrectionSettings())
    except ValueError as error:
        assert "differ" in str(error)
    else:
        raise AssertionError("same input/output path was accepted")


def test_batch_revises_latest_version_but_traces_the_fast_original(tmp_path: Path) -> None:
    source = tmp_path / "source.jsonl"
    output = tmp_path / "output.jsonl"
    history = JsonlHistory(source)
    history.append(CaptionEvent("source", "fast", "en", "zh", "final", 0, segment_id="s"))
    history.append(
        CaptionEvent(
            "source",
            "online revision",
            "en",
            "zh",
            "revised",
            0,
            segment_id="s",
            revision=1,
            parent_revision=0,
            original_translation="fast",
            revision_source="llm_correction",
        )
    )

    revise_history(
        source,
        output,
        BatchProvider(),
        CorrectionSettings(glossary_path=tmp_path / "missing.json"),
    )

    revised = tuple(JsonlHistory(output).read_all())[-1]
    assert revised["translated_text"] == "online revision!"
    assert revised["parent_revision"] == 1
    assert revised["revision"] == 2
    assert revised["original_translation"] == "fast"
