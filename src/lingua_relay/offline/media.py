from __future__ import annotations

import shutil
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np


@dataclass(frozen=True, slots=True)
class MediaInfo:
    path: Path
    duration_ms: int
    audio_streams: int
    has_video: bool
    format_name: str


def probe_media(path: str | Path) -> MediaInfo:
    source = Path(path)
    if not source.is_file():
        raise FileNotFoundError(source)
    av = _import_av()
    with av.open(str(source)) as container:
        audio_streams = tuple(container.streams.audio)
        if not audio_streams:
            raise ValueError("媒体文件不包含音轨")
        duration = container.duration or 0
        return MediaInfo(
            path=source.resolve(),
            duration_ms=round(float(duration) / 1000),
            audio_streams=len(audio_streams),
            has_video=bool(container.streams.video),
            format_name=str(container.format.name or source.suffix.lstrip(".")),
        )


def decode_media_to_wav(source: str | Path, output: str | Path) -> Path:
    """Decode the first audio stream to 16 kHz mono PCM for offline ASR."""

    source_path = Path(source)
    target = Path(output)
    target.parent.mkdir(parents=True, exist_ok=True)
    av = _import_av()
    temporary = target.with_suffix(target.suffix + ".tmp")
    with av.open(str(source_path)) as container:
        if not container.streams.audio:
            raise ValueError("媒体文件不包含音轨")
        stream = container.streams.audio[0]
        resampler = av.AudioResampler(format="s16", layout="mono", rate=16_000)
        with wave.open(str(temporary), "wb") as output_wave:
            output_wave.setnchannels(1)
            output_wave.setsampwidth(2)
            output_wave.setframerate(16_000)
            for frame in container.decode(stream):
                converted = resampler.resample(frame)
                for resampled in converted if isinstance(converted, list) else [converted]:
                    if resampled is None:
                        continue
                    array = resampled.to_ndarray()
                    output_wave.writeframes(np.asarray(array, dtype="<i2").reshape(-1).tobytes())
            flushed = resampler.resample(None)
            for resampled in flushed if isinstance(flushed, list) else [flushed]:
                if resampled is not None:
                    array = resampled.to_ndarray()
                    output_wave.writeframes(np.asarray(array, dtype="<i2").reshape(-1).tobytes())
    temporary.replace(target)
    return target


def export_audio(source_wav: str | Path, destination: str | Path) -> Path:
    source = Path(source_wav)
    target = Path(destination)
    target.parent.mkdir(parents=True, exist_ok=True)
    suffix = target.suffix.lower()
    if suffix == ".wav":
        shutil.copyfile(source, target)
        return target
    if suffix not in {".mp3", ".flac"}:
        raise ValueError("audio export supports WAV, FLAC, or MP3")
    av = _import_av()
    with av.open(str(source)) as input_container, av.open(str(target), mode="w") as output:
        input_stream = input_container.streams.audio[0]
        codec = "libmp3lame" if suffix == ".mp3" else "flac"
        output_stream = output.add_stream(codec, rate=16_000)
        output_stream.layout = "mono"
        if suffix == ".mp3":
            output_stream.bit_rate = 64_000
        resampler = av.AudioResampler(
            format=output_stream.codec_context.format.name,
            layout="mono",
            rate=16_000,
        )
        for frame in input_container.decode(input_stream):
            converted = resampler.resample(frame)
            for item in converted if isinstance(converted, list) else [converted]:
                if item is not None:
                    for packet in output_stream.encode(item):
                        output.mux(packet)
        flushed = resampler.resample(None)
        for item in flushed if isinstance(flushed, list) else [flushed]:
            if item is not None:
                for packet in output_stream.encode(item):
                    output.mux(packet)
        for packet in output_stream.encode(None):
            output.mux(packet)
    return target


def read_wave_float32(path: str | Path) -> tuple[np.ndarray, int]:
    with wave.open(str(path), "rb") as stream:
        if stream.getnchannels() != 1 or stream.getsampwidth() != 2:
            raise ValueError("offline ASR WAV must be mono 16-bit PCM")
        sample_rate = stream.getframerate()
        pcm = np.frombuffer(stream.readframes(stream.getnframes()), dtype="<i2")
    return (pcm.astype(np.float32) / 32768.0, sample_rate)


def _import_av() -> Any:
    try:
        import av
    except ImportError as error:
        raise RuntimeError("PyAV is required for audio/video import and export") from error
    return av
