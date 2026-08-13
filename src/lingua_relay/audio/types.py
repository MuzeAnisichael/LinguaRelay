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


class AudioSourceType(StrEnum):
    SYSTEM = "system"
    PROCESS = "process"
    MICROPHONE = "microphone"


@dataclass(frozen=True, slots=True)
class AudioDevice:
    device_id: str
    index: int
    name: str
    sample_rate: int
    channels: int
    output_index: int | None = None
    is_default: bool = False
    source_type: AudioSourceType = AudioSourceType.SYSTEM


@dataclass(frozen=True, slots=True)
class AudioProcess:
    process_id: int
    name: str

    @property
    def selector(self) -> str:
        return f"process:{self.process_id}"


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


def microphone_id_from_name(name: str) -> str:
    return f"wasapi-input:{name.strip()}"
