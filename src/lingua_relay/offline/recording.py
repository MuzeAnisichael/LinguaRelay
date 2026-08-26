from __future__ import annotations

import json
import os
import time
import wave
from datetime import UTC, datetime
from pathlib import Path

import numpy as np

from lingua_relay.audio.types import AudioChunk
from lingua_relay.offline.project import OfflineProjectStore


class RecordingSession:
    """Crash-recoverable speech recording assembled from normalized capture chunks."""

    def __init__(self, store: OfflineProjectStore, project_id: str) -> None:
        self.store = store
        self.project_id = project_id
        self.directory = store.project_dir(project_id)
        self.fragments_dir = self.directory / "fragments"
        self.fragments_dir.mkdir(parents=True, exist_ok=True)
        self.manifest_path = self.directory / "recording.json"
        self._writer: wave.Wave_write | None = None
        self._fragments: list[Path] = []
        self._sample_rate: int | None = None
        self._samples_written = 0
        self._state = "ready"
        self._pause_started_ns: int | None = None
        self._pause_started_at: str | None = None

    @property
    def state(self) -> str:
        return self._state

    @property
    def duration_ms(self) -> int:
        if not self._sample_rate:
            return 0
        return round(self._samples_written * 1000 / self._sample_rate)

    def start(self) -> None:
        if self._state != "ready":
            raise RuntimeError(f"cannot start recording from {self._state}")
        self._state = "recording"
        self.store.update_project(self.project_id, status="recording", progress=0, error="")
        self._write_manifest()

    def write(self, chunk: AudioChunk) -> None:
        if self._state != "recording":
            return
        samples = np.asarray(chunk.samples, dtype=np.float32).reshape(-1)
        if not len(samples):
            return
        if self._sample_rate is None:
            self._sample_rate = chunk.sample_rate
        elif chunk.sample_rate != self._sample_rate:
            raise ValueError("recording sample rate changed while active")
        if self._writer is None:
            self._open_fragment()
        assert self._writer is not None
        pcm = (np.clip(samples, -1.0, 1.0) * 32767).astype("<i2", copy=False)
        # writeframes patches the RIFF sizes on every chunk, so the active
        # fragment remains readable after a power loss or forced termination.
        self._writer.writeframes(pcm.tobytes())
        self._samples_written += len(samples)

    def pause(self) -> None:
        if self._state != "recording":
            raise RuntimeError("recording is not active")
        self._close_fragment()
        self._state = "paused"
        self._pause_started_ns = time.monotonic_ns()
        self._pause_started_at = _now()
        self.store.update_project(
            self.project_id, status="recording_paused", duration_ms=self.duration_ms
        )
        self._write_manifest()

    def resume(self) -> None:
        if self._state != "paused":
            raise RuntimeError("recording is not paused")
        ended_at = _now()
        if self._pause_started_ns is not None and self._pause_started_at is not None:
            elapsed = round((time.monotonic_ns() - self._pause_started_ns) / 1e6)
            self.store.add_interruption(
                self.project_id,
                started_at=self._pause_started_at,
                ended_at=ended_at,
                real_duration_ms=elapsed,
            )
        self._pause_started_ns = None
        self._pause_started_at = None
        self._state = "recording"
        self.store.update_project(self.project_id, status="recording")
        self._write_manifest()

    def stop(self) -> Path:
        if self._state not in {"recording", "paused"}:
            raise RuntimeError("recording is not active")
        if self._state == "paused" and self._pause_started_ns and self._pause_started_at:
            self.store.add_interruption(
                self.project_id,
                started_at=self._pause_started_at,
                ended_at=_now(),
                real_duration_ms=round((time.monotonic_ns() - self._pause_started_ns) / 1e6),
            )
        self._close_fragment()
        if not self._fragments:
            raise RuntimeError("录制中没有捕获到音频")
        output = self.directory / "recording.wav"
        _merge_wave_fragments(self._fragments, output, self._sample_rate or 16_000)
        self._state = "stopped"
        self.store.update_project(
            self.project_id,
            status="ready",
            progress=0,
            audio_path=output,
            duration_ms=self.duration_ms,
        )
        self._write_manifest()
        return output

    def abort(self, detail: str) -> None:
        self._close_fragment()
        self._state = "failed"
        self.store.update_project(
            self.project_id, status="failed", error=detail, duration_ms=self.duration_ms
        )
        self._write_manifest()

    def _open_fragment(self) -> None:
        path = self.fragments_dir / f"segment-{len(self._fragments) + 1:04d}.wav"
        writer = wave.open(str(path), "wb")  # noqa: SIM115 - closed at pause/stop
        writer.setnchannels(1)
        writer.setsampwidth(2)
        writer.setframerate(self._sample_rate or 16_000)
        self._writer = writer
        self._fragments.append(path)
        self._write_manifest()

    def _close_fragment(self) -> None:
        if self._writer is not None:
            self._writer.close()
            self._writer = None

    def _write_manifest(self) -> None:
        payload = {
            "schema": 1,
            "project_id": self.project_id,
            "state": self._state,
            "sample_rate": self._sample_rate,
            "samples_written": self._samples_written,
            "duration_ms": self.duration_ms,
            "fragments": [path.name for path in self._fragments],
            "updated_at": _now(),
        }
        temporary = self.manifest_path.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temporary, self.manifest_path)


def recover_recording(store: OfflineProjectStore, project_id: str) -> Path:
    """Assemble complete fragments left by an interrupted app run."""

    directory = store.project_dir(project_id)
    manifest = json.loads((directory / "recording.json").read_text(encoding="utf-8"))
    fragments_root = (directory / "fragments").resolve(strict=False)
    fragments: list[Path] = []
    for value in manifest.get("fragments", []):
        name = str(value)
        if Path(name).name != name:
            raise ValueError("录音恢复清单包含无效的片段路径")
        candidate = (fragments_root / name).resolve(strict=False)
        if candidate.parent != fragments_root:
            raise ValueError("录音恢复清单包含越界的片段路径")
        fragments.append(candidate)
    valid = [path for path in fragments if path.is_file() and path.stat().st_size >= 44]
    if not valid:
        raise RuntimeError("没有可恢复的录音片段")
    output = directory / "recording-recovered.wav"
    sample_rate = int(manifest.get("sample_rate") or 16_000)
    _merge_wave_fragments(valid, output, sample_rate)
    duration_ms = _wave_duration_ms(output)
    store.update_project(
        project_id,
        status="ready",
        error="",
        audio_path=output,
        duration_ms=duration_ms,
    )
    return output


def _merge_wave_fragments(fragments: list[Path], output: Path, sample_rate: int) -> None:
    temporary = output.with_suffix(".wav.tmp")
    with wave.open(str(temporary), "wb") as destination:
        destination.setnchannels(1)
        destination.setsampwidth(2)
        destination.setframerate(sample_rate)
        for path in fragments:
            with wave.open(str(path), "rb") as source:
                if source.getnchannels() != 1 or source.getsampwidth() != 2:
                    raise ValueError(f"unsupported recording fragment: {path}")
                if source.getframerate() != sample_rate:
                    raise ValueError(f"recording fragment sample rate changed: {path}")
                destination.writeframes(source.readframes(source.getnframes()))
    os.replace(temporary, output)


def _wave_duration_ms(path: Path) -> int:
    with wave.open(str(path), "rb") as stream:
        return round(stream.getnframes() * 1000 / stream.getframerate())


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds")
