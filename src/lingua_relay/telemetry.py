"""Bounded, in-memory pipeline measurements without caption or device payloads.

``ui_updated`` acknowledges a widget update, never physical display/paint latency.
Trace percentiles describe only the retained window; eviction is always reported.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import threading
import time
from collections import OrderedDict
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass
from typing import Any

STAGES = frozenset(
    {
        "audio_start",
        "audio_end",
        "asr_submitted",
        "asr_started",
        "asr_completed",
        "mt_submitted",
        "mt_started",
        "mt_completed",
        "service_adopted",
        "ui_updated",
        "transcript_ui_updated",
        "failed",
        "cancelled",
        "rejected",
        "suppressed",
    }
)
TERMINAL_FAILURES = frozenset({"failed", "cancelled", "rejected", "suppressed"})
LATENCY_PAIRS = {
    "segment_start_to_asr_ms": ("audio_start", "asr_completed"),
    "segment_start_to_mt_ms": ("audio_start", "mt_completed"),
    "segment_start_to_service_ms": ("audio_start", "service_adopted"),
    "segment_start_to_ui_update_ms": ("audio_start", "ui_updated"),
    "audio_end_to_ui_update_ms": ("audio_end", "ui_updated"),
    "asr_queue_ms": ("asr_submitted", "asr_started"),
    "asr_inference_ms": ("asr_started", "asr_completed"),
    "mt_queue_ms": ("mt_submitted", "mt_started"),
    "mt_inference_ms": ("mt_started", "mt_completed"),
    "service_to_ui_update_ms": ("service_adopted", "ui_updated"),
}
_NAME = re.compile(r"[a-z][a-z0-9_]{0,63}\Z")


def _integer(value: object, name: str, *, minimum: int = 0) -> int:
    if type(value) is not int or value < minimum:
        raise ValueError(f"{name} must be an integer >= {minimum}")
    return value


def _name(value: object) -> str:
    if not isinstance(value, str) or _NAME.fullmatch(value) is None:
        raise ValueError("metric names must be fixed lowercase identifiers, not payloads")
    return value


def _finite(value: object, name: str) -> float:
    if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
        raise ValueError(f"{name} must be a finite nonnegative number")
    return float(value)


def _percentile(values: Sequence[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    return ordered[max(0, math.ceil(len(ordered) * fraction) - 1)]


class TraceCollector:
    """Thread-safe bounded window; callers supply fixed stages, never raw text.

    Segment identifiers are hashed before retention. Counter label cardinality is
    separately bounded; discarded labels/trace entries remain visible in totals.
    The collector never writes files, starts threads, or calls a network service.
    """

    def __init__(
        self, capacity: int = 512, *, clock: Callable[[], int] = time.monotonic_ns
    ) -> None:
        self.capacity = _integer(capacity, "capacity", minimum=1)
        self._clock = clock
        self._lock = threading.Lock()
        self._traces: OrderedDict[tuple[str, int], dict[str, int]] = OrderedDict()
        self._counters: dict[str, int] = {}
        self._records = 0
        self._duplicates = 0
        self._evicted = 0
        self._counter_labels_dropped = 0
        self._rss_samples = 0
        self._rss_first: int | None = None
        self._rss_latest: int | None = None
        self._rss_peak: int | None = None

    def record(self, segment_id: str, revision: int, stage: str, at_ns: int | None = None) -> bool:
        if not isinstance(segment_id, str) or not segment_id or len(segment_id) > 1024:
            raise ValueError("segment_id must be a nonempty identifier of at most 1024 characters")
        revision = _integer(revision, "revision")
        if stage not in STAGES:
            raise ValueError("unknown trace stage")
        timestamp = _integer(self._clock() if at_ns is None else at_ns, "at_ns")
        key = (hashlib.sha256(segment_id.encode("utf-8")).hexdigest(), revision)
        with self._lock:
            self._records += 1
            if key not in self._traces:
                if len(self._traces) >= self.capacity:
                    self._traces.popitem(last=False)
                    self._evicted += 1
                self._traces[key] = {}
            stages = self._traces[key]
            if stage in stages:
                self._duplicates += 1
                return False
            stages[stage] = timestamp
        return True

    def increment(self, name: str, amount: int = 1) -> None:
        name = _name(name)
        amount = _integer(amount, "amount")
        with self._lock:
            if name not in self._counters and len(self._counters) >= 64:
                self._counter_labels_dropped += 1
                return
            self._counters[name] = self._counters.get(name, 0) + amount

    def observe_rss(self, rss_bytes: int | None = None) -> bool:
        """Sample process RSS on explicit request; unavailable is not zero."""
        if rss_bytes is None:
            try:
                import psutil

                rss_bytes = psutil.Process().memory_info().rss
            except ImportError:
                return False
            except (OSError, psutil.Error):
                return False
        value = _integer(rss_bytes, "rss_bytes", minimum=1)
        with self._lock:
            self._rss_samples += 1
            if self._rss_first is None:
                self._rss_first = value
            self._rss_latest = value
            self._rss_peak = max(value, self._rss_peak or value)
        return True

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            traces = [
                {"trace_id": key[0], "revision": key[1], "stages": dict(stages)}
                for key, stages in self._traces.items()
            ]
            resources = {
                "rss_samples": self._rss_samples,
                "rss_first_bytes": self._rss_first,
                "rss_latest_bytes": self._rss_latest,
                "rss_peak_bytes": self._rss_peak,
                "rss_growth_bytes": (
                    self._rss_latest - self._rss_first
                    if self._rss_latest is not None and self._rss_first is not None
                    else None
                ),
            }
            result = {
                "schema_version": 1,
                "clock": "monotonic_ns",
                "capacity": self.capacity,
                "retained_traces": len(traces),
                "record_calls": self._records,
                "duplicate_stages": self._duplicates,
                "evicted_trace_entries": self._evicted,
                "counter_labels_dropped": self._counter_labels_dropped,
                "counters": dict(self._counters),
                "resources": resources,
                "traces": traces,
            }
        rows = [trace["stages"] for trace in traces]
        result["latencies"] = {
            name: _latency_summary(rows, start, end) for name, (start, end) in LATENCY_PAIRS.items()
        }
        result["outcomes"] = {
            **{stage: sum(stage in row for row in rows) for stage in sorted(STAGES)},
            "asr_unresolved": sum(_unresolved(row, "asr") for row in rows),
            "mt_unresolved": sum(_unresolved(row, "mt") for row in rows),
            "translation_not_adopted": sum(
                "mt_completed" in row and "service_adopted" not in row for row in rows
            ),
            "ui_not_acknowledged": sum(
                "service_adopted" in row and "ui_updated" not in row for row in rows
            ),
        }
        result["scope_notes"] = [
            "Latency and outcome denominators cover retained segment/revision entries only.",
            "Evicted entries may reappear without earlier stages; no lifetime coverage claim.",
            "Missing UI acknowledgement is not audio loss or proof that no pixels appeared.",
            "ui_updated is a widget-update acknowledgement, not a paint/display timestamp.",
            "RSS peak is the maximum explicit sample, not a continuously monitored maximum.",
        ]
        return result


def _unresolved(stages: Mapping[str, int], prefix: str) -> bool:
    return (
        f"{prefix}_submitted" in stages
        and f"{prefix}_completed" not in stages
        and not TERMINAL_FAILURES.intersection(stages)
    )


def _latency_summary(rows: Sequence[Mapping[str, int]], start: str, end: str) -> dict[str, Any]:
    paired = [row for row in rows if start in row and end in row]
    values = [(row[end] - row[start]) / 1e6 for row in paired if row[end] >= row[start]]
    return {
        "start_stage": start,
        "end_stage": end,
        "total_retained": len(rows),
        "measured": len(values),
        "missing_start": sum(start not in row for row in rows),
        "missing_end": sum(end not in row for row in rows),
        "invalid_order": sum(row[end] < row[start] for row in paired),
        "failed": sum("failed" in row for row in rows),
        "cancelled": sum("cancelled" in row for row in rows),
        "rejected": sum("rejected" in row for row in rows),
        "suppressed": sum("suppressed" in row for row in rows),
        "p50_ms": _percentile(values, 0.5),
        "p95_ms": _percentile(values, 0.95),
        "max_ms": max(values) if values else None,
        "percentile_method": "nearest_rank",
    }


def configuration_fingerprint(configuration: Mapping[str, Any]) -> str:
    """Hash an explicit benchmark configuration, not the user's full settings."""
    if not isinstance(configuration, Mapping) or not configuration:
        raise ValueError("configuration must be a nonempty mapping")
    try:
        encoded = json.dumps(dict(configuration), sort_keys=True, allow_nan=False).encode("utf-8")
    except (ValueError, TypeError) as error:
        raise ValueError("configuration must contain finite JSON values") from error
    return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True, slots=True)
class GateObservation:
    category: str
    name: str
    configuration_id: str
    value: bool | float
    limit: float | None = None
    direction: str = "max"
    sample_count: int = 1


def evaluate_gates(observations: Sequence[GateObservation]) -> dict[str, Any]:
    """Evaluate supplied evidence only; do not invent thresholds or quality data.

    Boolean functional checks are mandatory evidence for functional status.
    Numeric performance/quality observations without approved limits stay
    not_evaluated. Thresholds do not certify the provenance of their samples.
    """
    if not observations:
        raise ValueError("gate observations must not be empty")
    groups: dict[str, list[dict[str, Any]]] = {"functional": [], "performance": [], "quality": []}
    configuration_ids: set[str] = set()
    identities: set[tuple[str, str]] = set()
    for observation in observations:
        if not isinstance(observation, GateObservation) or observation.category not in groups:
            raise ValueError("invalid gate observation category")
        name = _name(observation.name)
        identity = (observation.category, name)
        if identity in identities:
            raise ValueError("duplicate gate observation")
        identities.add(identity)
        if (
            not isinstance(observation.configuration_id, str)
            or re.fullmatch(r"[0-9a-f]{64}", observation.configuration_id) is None
        ):
            raise ValueError("configuration_id must be a SHA-256 fingerprint")
        configuration_ids.add(observation.configuration_id)
        _integer(observation.sample_count, "sample_count", minimum=1)
        if observation.direction not in {"min", "max"}:
            raise ValueError("gate direction must be min or max")
        if observation.category == "functional":
            if type(observation.value) is not bool or observation.limit is not None:
                raise ValueError("functional observations must be boolean without a limit")
            status = "pass" if observation.value else "fail"
        else:
            value = _finite(observation.value, "value")
            if observation.limit is None:
                status = "not_evaluated"
            else:
                limit = _finite(observation.limit, "limit")
                passed = value <= limit if observation.direction == "max" else value >= limit
                status = "pass" if passed else "fail"
        groups[observation.category].append({**asdict(observation), "status": status})
    if len(configuration_ids) != 1:
        raise ValueError("cannot combine evidence from different configurations")
    result = {}
    for category, checks in groups.items():
        states = {check["status"] for check in checks}
        status = "fail" if "fail" in states else "pass" if states == {"pass"} else "not_evaluated"
        result[category] = {
            "status": status,
            "checks": checks,
            "reason": (
                "no_evidence"
                if not checks
                else "no_approved_threshold"
                if status == "not_evaluated"
                else "evaluated_supplied_checks_only"
            ),
        }
    return result
