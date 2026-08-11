from __future__ import annotations

import json
import queue
import time
from pathlib import Path

from lingua_relay.config import CorrectionSettings
from lingua_relay.correction.engine import AsynchronousRevisionEngine
from lingua_relay.correction.types import CorrectionRequest, RevisionResult
from lingua_relay.events import CaptionEvent


class _ScriptedProvider:
    name = "local"
    model = "m4-benchmark-double"
    scope = "local"

    def __init__(self, *, delay_seconds: float = 0.0, fail: bool = False) -> None:
        self.delay_seconds = delay_seconds
        self.fail = fail

    def revise(self, request: CorrectionRequest) -> RevisionResult:
        if self.delay_seconds:
            time.sleep(self.delay_seconds)
        if self.fail:
            raise ConnectionError("scripted provider disconnect")
        return RevisionResult(
            request.event.translated_text + " [revised]",
            self.delay_seconds * 1_000,
            self.name,
            self.model,
            self.scope,
        )


def run_fault_gate_benchmark(event_count: int = 6) -> dict[str, object]:
    settings = CorrectionSettings(
        provider="local",
        model="m4-benchmark-double",
        requests_per_minute=1_000,
        queue_capacity=max(8, event_count + 1),
        event_queue_capacity=max(8, event_count + 1),
        failure_threshold=2,
        recovery_seconds=30,
    )
    healthy = AsynchronousRevisionEngine(_ScriptedProvider(delay_seconds=0.025), settings)
    healthy.start()
    fast_events: list[CaptionEvent] = []
    submit_ms: list[float] = []
    for index in range(event_count):
        event = _event(index)
        fast_events.append(event)
        started = time.monotonic_ns()
        healthy.submit(event)
        submit_ms.append((time.monotonic_ns() - started) / 1e6)
    healthy.stop()
    revisions = _drain(healthy)

    disconnected = AsynchronousRevisionEngine(_ScriptedProvider(fail=True), settings)
    disconnected.start()
    disconnected_fast_events: list[CaptionEvent] = []
    for index in range(event_count):
        event = _event(100 + index)
        disconnected_fast_events.append(event)
        disconnected.submit(event)
    disconnected.stop()
    disconnected_revisions = _drain(disconnected)
    disconnected_snapshot = disconnected.snapshot()

    trace_complete = all(
        event.state == "revised"
        and event.parent_revision is not None
        and event.original_translation is not None
        and event.revision_source == "llm_correction"
        for event in revisions
    )
    p95_submit = _percentile(submit_ms, 0.95)
    acceptance = {
        "fast_submit_p95_under_10_ms": p95_submit < 10,
        "healthy_revisions_traceable": len(revisions) == event_count and trace_complete,
        "disconnect_keeps_all_fast_events": len(disconnected_fast_events) == event_count,
        "disconnect_emits_no_false_revision": not disconnected_revisions,
        "circuit_opens_after_failures": disconnected_snapshot.circuit_state == "open",
    }
    acceptance["all_passed"] = all(acceptance.values())
    return {
        "benchmark": "m4-correction-fault-gates",
        "provider": "deterministic in-process test double",
        "event_count_per_scenario": event_count,
        "healthy": {
            "simulated_provider_latency_ms": 25,
            "fast_events_emitted": len(fast_events),
            "revisions_emitted": len(revisions),
            "submit_p95_ms": round(p95_submit, 3),
            "snapshot": _snapshot_dict(healthy.snapshot()),
        },
        "disconnected": {
            "fast_events_emitted": len(disconnected_fast_events),
            "revisions_emitted": len(disconnected_revisions),
            "snapshot": _snapshot_dict(disconnected_snapshot),
        },
        "acceptance": acceptance,
    }


def write_report(report: dict[str, object], path: str | Path) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return target


def _event(index: int) -> CaptionEvent:
    return CaptionEvent(
        source_text=f"source {index}",
        translated_text=f"fast translation {index}",
        source_language="en",
        target_language="zh",
        state="final",
        started_at_ms=index * 100,
        segment_id=f"benchmark-{index}",
    )


def _drain(engine: AsynchronousRevisionEngine) -> list[CaptionEvent]:
    events: list[CaptionEvent] = []
    while True:
        try:
            events.append(engine.get_event(timeout=0))
        except queue.Empty:
            return events


def _percentile(values: list[float], quantile: float) -> float:
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, int(len(ordered) * quantile)))
    return ordered[index]


def _snapshot_dict(snapshot: object) -> dict[str, object]:
    from dataclasses import asdict

    return asdict(snapshot)  # type: ignore[arg-type]
