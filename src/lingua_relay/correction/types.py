from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from lingua_relay.events import CaptionEvent, ProcessingScope


@dataclass(frozen=True, slots=True)
class GlossaryEntry:
    source: str
    target: str
    source_language: str | None = None
    target_language: str | None = None


@dataclass(frozen=True, slots=True)
class CorrectionRequest:
    event: CaptionEvent
    context: tuple[CaptionEvent, ...]
    glossary: tuple[GlossaryEntry, ...]
    state: str
    segment_id: str
    revision: int
    submitted_at_ns: int


@dataclass(frozen=True, slots=True)
class RevisionResult:
    text: str
    inference_ms: float
    provider: str
    model: str
    scope: ProcessingScope


@dataclass(frozen=True, slots=True)
class CorrectionSnapshot:
    running: bool
    circuit_state: str
    processing_scope: ProcessingScope
    requests_added: int
    partials_replaced: int
    partials_dropped: int
    revisions_emitted: int
    unchanged_results: int
    stale_results_dropped: int
    rate_limited: int
    circuit_rejected: int
    provider_errors: int
    output_drops: int
    queue_depth: int
    queue_capacity: int
    event_queue_depth: int
    event_queue_capacity: int
    last_error: str | None


class CorrectionProvider(Protocol):
    name: str
    model: str
    scope: ProcessingScope

    def revise(self, request: CorrectionRequest) -> RevisionResult: ...
