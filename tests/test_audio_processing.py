import numpy as np
import pytest

from lingua_relay.audio.processing import (
    FixedSampleChunker,
    Pcm16MonoResampler,
    measure_level,
)


def test_downmixes_stereo_pcm_to_float32_mono() -> None:
    frames = np.array([[16_384, 16_384], [-16_384, -16_384]], dtype="<i2")
    converter = Pcm16MonoResampler(input_rate=16_000, output_rate=16_000, channels=2)

    result = converter.push(frames.tobytes())

    assert result.dtype == np.float32
    assert result.tolist() == pytest.approx([0.5, -0.5])


def test_streaming_resampler_produces_expected_duration() -> None:
    converter = Pcm16MonoResampler(input_rate=48_000, output_rate=16_000, channels=2)
    source = np.zeros((48_000, 2), dtype="<i2")
    outputs = []
    for packet in np.array_split(source, 50):
        outputs.append(converter.push(packet.tobytes()))
    outputs.append(converter.push(b"", last=True))

    result = np.concatenate(outputs)

    assert len(result) == pytest.approx(16_000, abs=2)


def test_chunker_emits_fixed_read_only_chunks() -> None:
    chunker = FixedSampleChunker(5)

    first = list(chunker.push(np.arange(3, dtype=np.float32)))
    second = list(chunker.push(np.arange(3, 9, dtype=np.float32)))

    assert first == []
    assert [chunk.tolist() for chunk in second] == [[0, 1, 2, 3, 4]]
    assert second[0].flags.writeable is False
    assert chunker.pending_samples == 4


def test_level_meter_classifies_silence() -> None:
    silent = measure_level(np.zeros(100, dtype=np.float32), silence_dbfs=-55)
    signal = measure_level(np.full(100, 0.1, dtype=np.float32), silence_dbfs=-55)

    assert silent.silent
    assert signal.silent is False
    assert signal.dbfs == pytest.approx(-20, abs=0.01)
