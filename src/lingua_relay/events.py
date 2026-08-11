from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal
from uuid import uuid4

SegmentState = Literal["partial", "final", "revised"]
ProcessingScope = Literal["local", "cloud"]


@dataclass(frozen=True, slots=True)
class CaptionEvent:
    source_text: str
    translated_text: str
    source_language: str
    target_language: str
    state: SegmentState
    started_at_ms: int
    ended_at_ms: int | None = None
    segment_id: str = field(default_factory=lambda: str(uuid4()))
    revision: int = 0
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    timings_ms: dict[str, float] = field(default_factory=dict)
    error: str | None = None
    parent_revision: int | None = None
    original_translation: str | None = None
    revision_source: str = "fast_mt"
    processing_scope: ProcessingScope | None = None
    correction_provider: str | None = None
    correction_model: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
