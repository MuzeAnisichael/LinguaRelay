from __future__ import annotations

from collections.abc import Iterable

import numpy as np
import soxr

from lingua_relay.audio.types import AudioLevel


class Pcm16MonoResampler:
    """Convert interleaved signed 16-bit PCM to streaming mono float32."""

    def __init__(self, input_rate: int, output_rate: int, channels: int) -> None:
        if input_rate <= 0 or output_rate <= 0 or channels <= 0:
            raise ValueError("sample rates and channels must be positive")
        self.input_rate = input_rate
        self.output_rate = output_rate
        self.channels = channels
        self._resampler = (
            soxr.ResampleStream(input_rate, output_rate, 1, dtype="float32", quality="MQ")
            if input_rate != output_rate
            else None
        )

    def push(self, pcm: bytes, *, last: bool = False) -> np.ndarray:
        values = np.frombuffer(pcm, dtype="<i2")
        if values.size % self.channels:
            raise ValueError("PCM packet does not contain complete channel frames")
        frames = values.reshape(-1, self.channels)
        mono = frames.astype(np.float32).mean(axis=1) / 32768.0
        if self._resampler is None:
            return mono
        return self._resampler.resample_chunk(mono, last=last)


class FixedSampleChunker:
    def __init__(self, samples_per_chunk: int) -> None:
        if samples_per_chunk < 1:
            raise ValueError("samples_per_chunk must be at least one")
        self.samples_per_chunk = samples_per_chunk
        self._pending = np.empty(0, dtype=np.float32)

    def push(self, samples: np.ndarray) -> Iterable[np.ndarray]:
        if samples.size:
            normalized = np.asarray(samples, dtype=np.float32).reshape(-1)
            self._pending = np.concatenate((self._pending, normalized))
        while self._pending.size >= self.samples_per_chunk:
            chunk = self._pending[: self.samples_per_chunk].copy()
            self._pending = self._pending[self.samples_per_chunk :]
            chunk.flags.writeable = False
            yield chunk

    @property
    def pending_samples(self) -> int:
        return int(self._pending.size)


def measure_level(samples: np.ndarray, silence_dbfs: float) -> AudioLevel:
    if samples.size == 0:
        return AudioLevel(rms=0.0, peak=0.0, dbfs=float("-inf"), silent=True)
    values = np.asarray(samples, dtype=np.float32)
    rms = float(np.sqrt(np.mean(np.square(values, dtype=np.float64))))
    peak = float(np.max(np.abs(values)))
    dbfs = float(20 * np.log10(max(rms, 1e-12)))
    return AudioLevel(rms=rms, peak=peak, dbfs=dbfs, silent=dbfs < silence_dbfs)
