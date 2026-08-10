from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

import numpy as np


class CaptureState(StrEnum):
    STOPPED = "stopped"
    STARTING = "starting"
    RUNNING = "running"
    RECONNECTING = "reconnecting"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class AudioDevice:
    device_id: str
    index: int
    name: str
    sample_rate: int
    channels: int
    output_index: int | None = None
    is_default: bool = False


@dataclass(frozen=True, slots=True)
class AudioLevel:
    rms: float
    peak: float
    dbfs: float
    silent: bool


@dataclass(frozen=True, slots=True)
class AudioChunk:
    samples: np.ndarray
    sequence: int
    captured_at_ns: int
    sample_rate: int
    device_id: str
    device_name: str
    level: AudioLevel

    @property
    def duration_ms(self) -> float:
        return len(self.samples) * 1000 / self.sample_rate


@dataclass(frozen=True, slots=True)
class CaptureSnapshot:
    state: CaptureState
    device: AudioDevice | None
    chunks_emitted: int
    samples_emitted: int
    raw_packets_dropped: int
    output_chunks_dropped: int
    reconnects: int
    last_error: str | None
    queue_depth: int
    queue_capacity: int


def device_id_from_name(name: str) -> str:
    suffix = " [Loopback]"
    base = name[: -len(suffix)] if name.endswith(suffix) else name
    return f"wasapi:{base.strip()}"
