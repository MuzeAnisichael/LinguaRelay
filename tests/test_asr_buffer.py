import queue
import threading
import time

import numpy as np
import pytest

from lingua_relay.asr.buffer import InferenceBacklog, LatestEventBuffer
from lingua_relay.asr.types import AsrEvent, InferenceRequest


def request(segment: str, revision: int, state: str = "partial") -> InferenceRequest:
    return InferenceRequest(
        samples=np.zeros(10, dtype=np.float32),
        language="en",
        state=state,  # type: ignore[arg-type]
        segment_id=segment,
        revision=revision,
        started_at_ns=1,
        ended_at_ns=2,
        submitted_at_ns=time.monotonic_ns(),
    )


def test_backlog_replaces_stale_partial_with_freshest() -> None:
    backlog = InferenceBacklog(3)

    assert backlog.put_partial(request("a", 1))
    assert backlog.put_partial(request("a", 2))

    assert backlog.get(timeout=0).revision == 2
    assert backlog.snapshot().partials_replaced == 1


def test_final_removes_partial_for_same_segment_and_is_preserved() -> None:
    backlog = InferenceBacklog(2)

    backlog.put_partial(request("a", 1))
    assert backlog.put_final(request("a", 2, "final"), timeout=0)

    item = backlog.get(timeout=0)
    assert item.state == "final"
    assert item.revision == 2


def test_partial_is_dropped_when_final_backlog_occupies_capacity() -> None:
    backlog = InferenceBacklog(2)
    backlog.put_final(request("a", 1, "final"), timeout=0)
    backlog.put_final(request("b", 1, "final"), timeout=0)

    assert backlog.put_partial(request("c", 1)) is False
    assert backlog.snapshot().partials_dropped == 1


def event(segment: str) -> AsrEvent:
    return AsrEvent("text", "text", "", "text", "en", "final", segment, 1, 0, 1, 2)


@pytest.mark.parametrize("kind", ["requests", "events"])
def test_close_wakes_full_final_producer_and_preserves_accepted_items(kind):
    buffer = InferenceBacklog(2) if kind == "requests" else LatestEventBuffer(2)
    put = buffer.put_final if kind == "requests" else buffer.put
    make = (lambda name: request(name, 1, "final")) if kind == "requests" else event
    assert put(make("a"), timeout=0)
    assert put(make("b"), timeout=0)
    entered_wait = threading.Event()
    original_wait = buffer._condition.wait

    def wait(timeout=None):
        entered_wait.set()
        return original_wait(timeout)

    buffer._condition.wait = wait
    accepted = []
    producer = threading.Thread(target=lambda: accepted.append(put(make("c"), timeout=2)))
    producer.start()
    try:
        assert entered_wait.wait(1)
        buffer.close()
        producer.join(1)
        assert not producer.is_alive()
        assert accepted == [False]
        assert [buffer.get(timeout=0).segment_id for _ in range(2)] == ["a", "b"]
        with pytest.raises(queue.Empty):
            buffer.get(timeout=0)
    finally:
        buffer.close()
        producer.join(2)


@pytest.mark.parametrize("kind", ["requests", "events"])
def test_closed_empty_buffer_wakes_consumer(kind):
    buffer = InferenceBacklog(2) if kind == "requests" else LatestEventBuffer(2)
    entered_wait = threading.Event()
    original_wait = buffer._condition.wait

    def wait(timeout=None):
        entered_wait.set()
        return original_wait(timeout)

    buffer._condition.wait = wait
    completed = threading.Event()

    def consume():
        with pytest.raises(queue.Empty):
            buffer.get(timeout=2)
        completed.set()

    consumer = threading.Thread(target=consume)
    consumer.start()
    try:
        assert entered_wait.wait(1)
        buffer.close()
        assert completed.wait(1)
    finally:
        buffer.close()
        consumer.join(2)
    assert not consumer.is_alive()


def test_abort_returns_pending_work_once_and_rejects_later_submissions():
    backlog = InferenceBacklog(3)
    backlog.put_final(request("a", 1, "final"), timeout=0)
    backlog.put_partial(request("b", 1))
    assert [item.segment_id for item in backlog.abort()] == ["a", "b"]
    assert backlog.abort() == ()
    assert not backlog.put_final(request("c", 1, "final"), timeout=0)
    assert backlog.snapshot().final_submit_rejections == 1
    assert backlog.snapshot().depth == 0
