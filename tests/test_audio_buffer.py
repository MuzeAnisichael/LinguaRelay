import numpy as np

from lingua_relay.audio.buffer import LatestAudioBuffer
from lingua_relay.audio.types import AudioChunk, AudioLevel


def make_chunk(sequence: int) -> AudioChunk:
    return AudioChunk(
        samples=np.zeros(16, dtype=np.float32),
        sequence=sequence,
        captured_at_ns=sequence,
        sample_rate=16_000,
        device_id="wasapi:test",
        device_name="test",
        level=AudioLevel(rms=0, peak=0, dbfs=float("-inf"), silent=True),
    )


def test_bounded_buffer_discards_oldest_audio() -> None:
    buffer = LatestAudioBuffer(capacity=2)

    buffer.put(make_chunk(0))
    buffer.put(make_chunk(1))
    buffer.put(make_chunk(2))

    assert buffer.get_nowait().sequence == 1
    assert buffer.get_nowait().sequence == 2
    assert buffer.snapshot().items_dropped == 1
