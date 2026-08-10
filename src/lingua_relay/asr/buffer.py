from __future__ import annotations

import queue
import threading
import time
from collections import deque
from dataclasses import dataclass

from lingua_relay.asr.types import AsrEvent, InferenceRequest


@dataclass(frozen=True, slots=True)
class BacklogSnapshot:
    depth: int
    capacity: int
    items_added: int
    partials_replaced: int
    partials_dropped: int


class InferenceBacklog:
    """Bounded final-preserving backlog with a single fresh partial slot."""

    def __init__(self, capacity: int) -> None:
        if capacity < 2:
            raise ValueError("capacity must be at least two")
        self._capacity = capacity
        self._finals: deque[InferenceRequest] = deque()
        self._partial: InferenceRequest | None = None
        self._condition = threading.Condition()
        self._closed = False
        self._items_added = 0
        self._partials_replaced = 0
        self._partials_dropped = 0

    def put_partial(self, request: InferenceRequest) -> bool:
        if request.state != "partial":
            raise ValueError("put_partial requires a partial request")
        with self._condition:
            if self._closed:
                return False
            if len(self._finals) >= self._capacity:
                self._partials_dropped += 1
                return False
            if self._partial is not None:
                self._partials_replaced += 1
            self._partial = request
            self._items_added += 1
            self._condition.notify()
            return True

    def put_final(self, request: InferenceRequest, timeout: float | None = None) -> bool:
        if request.state != "final":
            raise ValueError("put_final requires a final request")
        deadline = None if timeout is None else time.monotonic() + timeout
        with self._condition:
            if self._partial is not None and self._partial.segment_id == request.segment_id:
                self._partial = None
                self._partials_replaced += 1
            while len(self._finals) + int(self._partial is not None) >= self._capacity:
                if self._partial is not None:
                    self._partial = None
                    self._partials_replaced += 1
                    break
                if self._closed:
                    return False
                remaining = None if deadline is None else deadline - time.monotonic()
                if remaining is not None and remaining <= 0:
                    return False
                self._condition.wait(remaining)
            if self._closed:
                return False
            self._finals.append(request)
            self._items_added += 1
            self._condition.notify()
            return True

    def get(self, timeout: float | None = None) -> InferenceRequest:
        deadline = None if timeout is None else time.monotonic() + timeout
        with self._condition:
            while not self._finals and self._partial is None:
                if self._closed:
                    raise queue.Empty
                remaining = None if deadline is None else deadline - time.monotonic()
                if remaining is not None and remaining <= 0:
                    raise queue.Empty
                self._condition.wait(remaining)
            if self._finals:
                item = self._finals.popleft()
            else:
                assert self._partial is not None
                item = self._partial
                self._partial = None
            self._condition.notify_all()
            return item

    def close(self) -> None:
        with self._condition:
            self._closed = True
            self._condition.notify_all()

    def snapshot(self) -> BacklogSnapshot:
        with self._condition:
            return BacklogSnapshot(
                depth=len(self._finals) + int(self._partial is not None),
                capacity=self._capacity,
                items_added=self._items_added,
                partials_replaced=self._partials_replaced,
                partials_dropped=self._partials_dropped,
            )


class LatestEventBuffer:
    """Keep finals and replace stale partial display events under UI backpressure."""

    def __init__(self, capacity: int) -> None:
        if capacity < 2:
            raise ValueError("capacity must be at least two")
        self._events: deque[AsrEvent] = deque()
        self._capacity = capacity
        self._condition = threading.Condition()
        self._partials_dropped = 0
        self._closed = False

    def put(self, event: AsrEvent, timeout: float | None = None) -> bool:
        deadline = None if timeout is None else time.monotonic() + timeout
        with self._condition:
            if self._closed:
                return False
            if event.state == "partial":
                while len(self._events) >= self._capacity:
                    if not self._discard_oldest_partial():
                        self._partials_dropped += 1
                        return False
            else:
                while len(self._events) >= self._capacity:
                    if not self._discard_oldest_partial():
                        remaining = None if deadline is None else deadline - time.monotonic()
                        if remaining is not None and remaining <= 0:
                            return False
                        self._condition.wait(remaining)
                    if self._closed:
                        return False
            self._events.append(event)
            self._condition.notify()
            return True

    def get(self, timeout: float | None = None) -> AsrEvent:
        deadline = None if timeout is None else time.monotonic() + timeout
        with self._condition:
            while not self._events:
                if self._closed:
                    raise queue.Empty
                remaining = None if deadline is None else deadline - time.monotonic()
                if remaining is not None and remaining <= 0:
                    raise queue.Empty
                self._condition.wait(remaining)
            event = self._events.popleft()
            self._condition.notify_all()
            return event

    def close(self) -> None:
        with self._condition:
            self._closed = True
            self._condition.notify_all()

    def snapshot(self) -> tuple[int, int, int]:
        with self._condition:
            return len(self._events), self._capacity, self._partials_dropped

    def _discard_oldest_partial(self) -> bool:
        for index, item in enumerate(self._events):
            if item.state == "partial":
                del self._events[index]
                self._partials_dropped += 1
                return True
        return False
