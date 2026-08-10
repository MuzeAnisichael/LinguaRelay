import time

import numpy as np

from lingua_relay.asr.buffer import InferenceBacklog
from lingua_relay.asr.types import InferenceRequest


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
