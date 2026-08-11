from __future__ import annotations

import json
import shutil
import time
from dataclasses import asdict, dataclass
from pathlib import Path

from lingua_relay.config import CorrectionSettings
from lingua_relay.correction.controls import CircuitBreaker, RateLimiter
from lingua_relay.correction.glossary import glossary_for_route, load_glossary
from lingua_relay.correction.types import CorrectionProvider, CorrectionRequest
from lingua_relay.events import CaptionEvent
from lingua_relay.history import JsonlHistory


@dataclass(frozen=True, slots=True)
class BatchRevisionReport:
    input_events: int
    eligible_events: int
    revisions_written: int
    unchanged_events: int
    failed_events: int
    output_path: str


def revise_history(
    input_path: str | Path,
    output_path: str | Path,
    provider: CorrectionProvider,
    settings: CorrectionSettings,
) -> BatchRevisionReport:
    source_path = Path(input_path).resolve()
    target_path = Path(output_path).resolve()
    if source_path == target_path:
        raise ValueError("batch revision output must differ from the input history")
    rows = tuple(JsonlHistory(source_path).read_all())
    target_path.parent.mkdir(parents=True, exist_ok=True)
    if source_path.exists():
        shutil.copyfile(source_path, target_path)
    else:
        target_path.write_text("", encoding="utf-8")
    output = JsonlHistory(target_path)
    glossary = load_glossary(settings.glossary_path)
    limiter = RateLimiter(settings.requests_per_minute)
    circuit = CircuitBreaker(settings.failure_threshold, settings.recovery_seconds)
    context: list[CaptionEvent] = []
    eligible = revisions = unchanged = failed = 0
    originals, latest, order = _segment_versions(rows)
    for segment_id in order:
        eligible += 1
        original = _caption_from_row(originals[segment_id])
        event = _caption_from_row(latest[segment_id])
        route_context = tuple(
            item
            for item in context
            if item.source_language == event.source_language
            and item.target_language == event.target_language
        )
        request = CorrectionRequest(
            event=event,
            context=(
                route_context[-settings.context_segments :] if settings.context_segments else ()
            ),
            glossary=glossary_for_route(glossary, event.source_language, event.target_language),
            state="final",
            segment_id=event.segment_id,
            revision=event.revision,
            submitted_at_ns=time.monotonic_ns(),
        )
        context.append(event)
        if not circuit.allow_request():
            failed += 1
            continue
        while not limiter.acquire():
            time.sleep(min(0.1, 60 / settings.requests_per_minute))
        try:
            result = provider.revise(request)
        except Exception:
            circuit.record_failure()
            failed += 1
            continue
        circuit.record_success()
        if result.text.strip() == event.translated_text.strip():
            unchanged += 1
            continue
        output.append(
            CaptionEvent(
                source_text=event.source_text,
                translated_text=result.text,
                source_language=event.source_language,
                target_language=event.target_language,
                state="revised",
                started_at_ms=event.started_at_ms,
                ended_at_ms=event.ended_at_ms,
                segment_id=event.segment_id,
                revision=event.revision + 1,
                timings_ms={**event.timings_ms, "correction": result.inference_ms},
                parent_revision=event.revision,
                original_translation=original.translated_text,
                revision_source="llm_batch_correction",
                processing_scope=result.scope,
                correction_provider=result.provider,
                correction_model=result.model,
            )
        )
        revisions += 1
    return BatchRevisionReport(len(rows), eligible, revisions, unchanged, failed, str(target_path))


def _segment_versions(
    rows: tuple[dict[str, object], ...],
) -> tuple[
    dict[str, dict[str, object]],
    dict[str, dict[str, object]],
    list[str],
]:
    originals: dict[str, dict[str, object]] = {}
    latest: dict[str, dict[str, object]] = {}
    order: list[str] = []
    for row in rows:
        segment_id = str(row.get("segment_id") or "")
        if not segment_id:
            continue
        is_fast_final = (
            row.get("state") == "final" and row.get("revision_source", "fast_mt") == "fast_mt"
        )
        if is_fast_final and segment_id not in originals:
            originals[segment_id] = row
            latest[segment_id] = row
            order.append(segment_id)
        if segment_id not in originals or row.get("state") not in {"final", "revised"}:
            continue
        current_revision = int(latest[segment_id].get("revision") or 0)
        candidate_revision = int(row.get("revision") or 0)
        if candidate_revision >= current_revision:
            latest[segment_id] = row
    return originals, latest, order


def _caption_from_row(row: dict[str, object]) -> CaptionEvent:
    timings = row.get("timings_ms")
    return CaptionEvent(
        source_text=str(row.get("source_text") or ""),
        translated_text=str(row.get("translated_text") or ""),
        source_language=str(row.get("source_language") or ""),
        target_language=str(row.get("target_language") or ""),
        state="final",
        started_at_ms=int(row.get("started_at_ms") or 0),
        ended_at_ms=int(row["ended_at_ms"]) if row.get("ended_at_ms") is not None else None,
        segment_id=str(row.get("segment_id") or ""),
        revision=int(row.get("revision") or 0),
        created_at=str(row.get("created_at") or ""),
        timings_ms={str(key): float(value) for key, value in timings.items()}
        if isinstance(timings, dict)
        else {},
        error=str(row["error"]) if row.get("error") is not None else None,
    )


def write_batch_report(report: BatchRevisionReport, path: str | Path) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(asdict(report), ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
