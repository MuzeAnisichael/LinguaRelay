from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal

import numpy as np

AsrEventState = Literal["partial", "final"]


@dataclass(frozen=True, slots=True)
class AsrRuntime:
    requested_device: str
    device: str
    compute_type: str
    cuda_devices: int
    cuda_runtime_ready: bool


@dataclass(frozen=True, slots=True)
class AsrWord:
    start_seconds: float
    end_seconds: float
    text: str
    probability: float | None = None


@dataclass(frozen=True, slots=True)
class AsrSegment:
    start_seconds: float
    end_seconds: float
    text: str
    avg_logprob: float | None = None
    no_speech_prob: float | None = None
    words: tuple[AsrWord, ...] = ()


@dataclass(frozen=True, slots=True)
class AsrResult:
    text: str
    language: str
    duration_ms: float
    inference_ms: float
    segments: tuple[AsrSegment, ...] = ()


@dataclass(frozen=True, slots=True)
class InferenceRequest:
    samples: np.ndarray
    language: str
    state: AsrEventState
    segment_id: str
    revision: int
    started_at_ns: int
    ended_at_ns: int
    submitted_at_ns: int


@dataclass(frozen=True, slots=True)
class AsrEvent:
    text: str
    stable_text: str
    unstable_text: str
    newly_stable_text: str
    language: str
    state: AsrEventState
    segment_id: str
    revision: int
    started_at_ms: int
    ended_at_ms: int
    emitted_at_ns: int
    timings_ms: dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class AsrSnapshot:
    running: bool
    requests_added: int
    partials_replaced: int
    partials_dropped: int
    stale_results_dropped: int
    hallucinations_suppressed: int
    events_emitted: int
    inference_errors: int
    inference_queue_depth: int
    inference_queue_capacity: int
    event_queue_depth: int
    event_queue_capacity: int
    last_error: str | None
