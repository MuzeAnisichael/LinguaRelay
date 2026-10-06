from __future__ import annotations

from dataclasses import dataclass

from lingua_relay.asr.types import AsrEvent


@dataclass(frozen=True, slots=True)
class TranslationResult:
    text: str
    source: str
    target: str
    inference_ms: float
    cache_hit: bool = False


@dataclass(frozen=True, slots=True)
class TranslationRequest:
    event: AsrEvent
    source: str
    target: str
    state: str
    segment_id: str
    revision: int
    submitted_at_ns: int


@dataclass(frozen=True, slots=True)
class TranslationSnapshot:
    running: bool
    requests_added: int
    partials_replaced: int
    partials_dropped: int
    # Completed native results suppressed after abort, not all superseded partial work.
    stale_results_dropped: int
    events_emitted: int
    translation_errors: int
    queue_depth: int
    queue_capacity: int
    event_queue_depth: int
    event_queue_capacity: int
    last_error: str | None
    worker_alive: bool = False
    overloaded: bool = False
    final_requests_added: int = 0
    # Rejected admission attempts; a caller may retry the same final successfully.
    final_submit_rejections: int = 0
    final_requests_aborted: int = 0
    final_outputs_rejected: int = 0
    final_events_aborted: int = 0
    history_errors: int = 0
