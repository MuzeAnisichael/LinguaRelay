from __future__ import annotations

import queue
import threading
from dataclasses import dataclass

from lingua_relay.audio.types import AudioChunk


@dataclass(frozen=True, slots=True)
class BufferSnapshot:
    depth: int
    capacity: int
    items_added: int
    items_dropped: int


class LatestAudioBuffer:
    """A bounded queue that preserves fresh audio under downstream overload."""

    def __init__(self, capacity: int) -> None:
        if capacity < 1:
            raise ValueError("capacity must be at least one")
        self._queue: queue.Queue[AudioChunk] = queue.Queue(maxsize=capacity)
        self._capacity = capacity
        self._lock = threading.Lock()
        self._items_added = 0
        self._items_dropped = 0

    def put(self, chunk: AudioChunk) -> None:
        with self._lock:
            if self._queue.full():
                try:
                    self._queue.get_nowait()
                except queue.Empty:
                    pass
                else:
                    self._items_dropped += 1
            self._queue.put_nowait(chunk)
            self._items_added += 1

    def get(self, timeout: float | None = None) -> AudioChunk:
        return self._queue.get(timeout=timeout)

    def get_nowait(self) -> AudioChunk:
        return self._queue.get_nowait()

    def clear(self) -> None:
        while True:
            try:
                self._queue.get_nowait()
            except queue.Empty:
                break

    def snapshot(self) -> BufferSnapshot:
        with self._lock:
            return BufferSnapshot(
                depth=self._queue.qsize(),
                capacity=self._capacity,
                items_added=self._items_added,
                items_dropped=self._items_dropped,
            )
