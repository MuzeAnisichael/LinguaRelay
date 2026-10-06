from __future__ import annotations

import json
import threading
from dataclasses import replace

import pytest

from lingua_relay.telemetry import (
    GateObservation,
    TraceCollector,
    configuration_fingerprint,
    evaluate_gates,
)


def test_trace_hashes_identifiers_and_preserves_first_stage_timestamp():
    trace = TraceCollector(clock=lambda: 20)
    assert trace.record("private caption must never appear", 1, "audio_start", 10)
    assert not trace.record("private caption must never appear", 1, "audio_start", 15)
    assert trace.record("private caption must never appear", 1, "service_adopted")
    snapshot = trace.snapshot()
    assert "private caption" not in json.dumps(snapshot)
    assert snapshot["duplicate_stages"] == 1
    assert snapshot["traces"][0]["stages"]["audio_start"] == 10
    assert snapshot["outcomes"]["ui_not_acknowledged"] == 1
    assert snapshot["latencies"]["segment_start_to_ui_update_ms"]["p50_ms"] is None


def test_trace_window_and_counter_labels_are_bounded_and_disclosed():
    trace = TraceCollector(capacity=2)
    for segment in range(5):
        trace.record(str(segment), 1, "audio_start", segment)
    for number in range(70):
        trace.increment(f"counter_{number}")
    snapshot = trace.snapshot()
    assert snapshot["retained_traces"] == 2
    assert snapshot["evicted_trace_entries"] == 3
    assert snapshot["record_calls"] == 5
    assert len(snapshot["counters"]) == 64
    assert snapshot["counter_labels_dropped"] == 6
    assert snapshot["latencies"]["segment_start_to_asr_ms"]["total_retained"] == 2


def test_trace_outcomes_keep_missing_failed_and_bad_clock_samples_visible():
    trace = TraceCollector()
    for segment in ("good", "failed", "missing", "backwards", "cancelled"):
        trace.record(segment, 1, "audio_start", 100)
        trace.record(segment, 1, "asr_submitted", 100)
    trace.record("good", 1, "asr_completed", 2_000_100)
    trace.record("good", 1, "mt_submitted", 2_000_100)
    trace.record("failed", 1, "failed", 300)
    trace.record("backwards", 1, "asr_completed", 90)
    trace.record("cancelled", 1, "cancelled", 300)
    snapshot = trace.snapshot()
    metric = snapshot["latencies"]["segment_start_to_asr_ms"]
    assert metric["total_retained"] == 5
    assert metric["measured"] == 1
    assert metric["p50_ms"] == metric["p95_ms"] == 2.0
    assert metric["missing_end"] == 3
    assert metric["invalid_order"] == 1
    assert metric["failed"] == metric["cancelled"] == 1
    assert snapshot["outcomes"]["asr_unresolved"] == 1
    assert snapshot["outcomes"]["mt_unresolved"] == 1


def test_transcript_update_never_counts_as_translation_ui_ack():
    trace = TraceCollector()
    trace.record("a", 1, "audio_start", 10)
    trace.record("a", 1, "transcript_ui_updated", 20)
    result = trace.snapshot()
    assert result["outcomes"]["ui_updated"] == 0
    assert result["latencies"]["segment_start_to_ui_update_ms"]["measured"] == 0


def test_rss_samples_are_optional_aggregate_observations():
    trace = TraceCollector()
    assert trace.snapshot()["resources"]["rss_peak_bytes"] is None
    for sample in (100, 300, 80):
        assert trace.observe_rss(sample)
    result = trace.snapshot()["resources"]
    assert result == {
        "rss_samples": 3,
        "rss_first_bytes": 100,
        "rss_latest_bytes": 80,
        "rss_peak_bytes": 300,
        "rss_growth_bytes": -20,
    }


def test_concurrent_trace_writers_do_not_lose_counters():
    trace = TraceCollector(capacity=20)

    def worker(index):
        for revision in range(10):
            trace.record(str(index), revision, "asr_submitted")
            trace.increment("submitted")

    threads = [threading.Thread(target=worker, args=(index,)) for index in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(2)
        assert not thread.is_alive()
    snapshot = trace.snapshot()
    assert snapshot["counters"]["submitted"] == 40
    assert snapshot["retained_traces"] == 20
    assert snapshot["evicted_trace_entries"] == 20


@pytest.mark.parametrize(
    "revision,stage,at_ns",
    [
        (-1, "audio_start", 10),
        (True, "audio_start", 10),
        (1, "raw caption", 10),
        (1, "audio_start", float("nan")),
        (1, "audio_start", -1),
    ],
)
def test_trace_rejects_invalid_inputs(revision, stage, at_ns):
    with pytest.raises(ValueError):
        TraceCollector().record("a", revision, stage, at_ns)


def test_configuration_fingerprint_is_order_independent_and_rejects_invalid_data():
    assert configuration_fingerprint({"a": 1, "b": 2}) == configuration_fingerprint(
        {"b": 2, "a": 1}
    )
    for invalid in ({}, {"a": float("nan")}, {"a": object()}):
        with pytest.raises(ValueError):
            configuration_fingerprint(invalid)


def _observation(**changes):
    baseline = GateObservation(
        "functional", "finals_complete", configuration_fingerprint({"mode": "fake"}), True
    )
    return replace(baseline, **changes)


def test_gates_never_promote_missing_quality_or_unapproved_performance_to_pass():
    gates = evaluate_gates(
        [
            _observation(),
            _observation(category="performance", name="queue_p95_ms", value=1.2),
        ]
    )
    assert gates["functional"]["status"] == "pass"
    assert gates["performance"]["status"] == "not_evaluated"
    assert gates["performance"]["reason"] == "no_approved_threshold"
    assert gates["quality"]["status"] == "not_evaluated"
    assert gates["quality"]["reason"] == "no_evidence"


def test_gates_separate_functional_failure_from_evaluated_metrics():
    gates = evaluate_gates(
        [
            _observation(value=False),
            _observation(category="performance", name="queue_p95_ms", value=5.0, limit=3.0),
            _observation(
                category="quality",
                name="reference_score",
                value=80.0,
                limit=75.0,
                direction="min",
                sample_count=100,
            ),
        ]
    )
    assert gates["functional"]["status"] == "fail"
    assert gates["performance"]["status"] == "fail"
    assert gates["quality"]["status"] == "pass"


@pytest.mark.parametrize(
    "changes",
    [
        {"category": "unknown"},
        {"name": "private text"},
        {"configuration_id": None},
        {"value": 1},
        {"sample_count": 0},
        {"sample_count": True},
        {"direction": "equal"},
        {"category": "quality", "value": float("nan")},
        {"category": "performance", "value": float("inf")},
        {"category": "performance", "value": -1.0},
        {"category": "performance", "value": 1.0, "limit": float("inf")},
    ],
)
def test_gates_reject_invalid_observations(changes):
    with pytest.raises(ValueError):
        evaluate_gates([_observation(**changes)])


def test_gates_reject_empty_duplicate_and_mixed_configuration_evidence():
    with pytest.raises(ValueError, match="empty"):
        evaluate_gates([])
    with pytest.raises(ValueError, match="duplicate"):
        evaluate_gates([_observation(), _observation()])
    with pytest.raises(ValueError, match="different configurations"):
        evaluate_gates([_observation(), _observation(name="other", configuration_id="a" * 64)])
