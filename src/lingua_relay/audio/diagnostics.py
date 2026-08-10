from __future__ import annotations

import json
import queue
import time
import tracemalloc
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

import numpy as np

from lingua_relay.audio.capture import WasapiLoopbackCapture
from lingua_relay.audio.types import CaptureState
from lingua_relay.config import AudioSettings


@dataclass(frozen=True, slots=True)
class StressReport:
    started_at: str
    requested_seconds: float
    elapsed_seconds: float
    device_id: str | None
    device_name: str | None
    output_sample_rate: int
    chunk_ms: int
    chunks_consumed: int
    silent_chunks: int
    sequence_gaps: int
    timestamp_regressions: int
    malformed_chunks: int
    reconnects: int
    raw_packets_dropped: int
    output_chunks_dropped: int
    rss_start_bytes: int
    rss_end_bytes: int
    rss_peak_bytes: int
    rss_growth_bytes: int
    python_heap_growth_bytes: int
    passed: bool
    failures: tuple[str, ...]

    def write(self, path: str | Path) -> None:
        report_path = Path(path)
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(
            json.dumps(asdict(self), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )


def monitor_audio(settings: AudioSettings, seconds: float) -> int:
    if seconds <= 0:
        raise ValueError("seconds must be positive")
    with WasapiLoopbackCapture(settings) as capture:
        if not capture.wait_until_running(timeout=10):
            snapshot = capture.snapshot()
            print(f"capture failed to start: {snapshot.last_error or snapshot.state}")
            return 1
        snapshot = capture.snapshot()
        assert snapshot.device is not None
        print(
            f"capturing {snapshot.device.device_id} at {snapshot.device.sample_rate} Hz -> "
            f"{settings.sample_rate} Hz mono"
        )
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            try:
                chunk = capture.get_chunk(timeout=1.0)
            except queue.Empty:
                snapshot = capture.snapshot()
                print(f"waiting: state={snapshot.state} error={snapshot.last_error}")
                continue
            width = 32
            filled = min(width, round(chunk.level.peak * width))
            meter = "#" * filled + "-" * (width - filled)
            print(
                f"\rseq={chunk.sequence:06d} [{meter}] "
                f"{chunk.level.dbfs:7.1f} dBFS "
                f"{'silence' if chunk.level.silent else 'signal ':7s}",
                end="",
                flush=True,
            )
        print()
        final = capture.snapshot()
        print(
            f"chunks={final.chunks_emitted} raw_drops={final.raw_packets_dropped} "
            f"output_drops={final.output_chunks_dropped} reconnects={final.reconnects}"
        )
        return 0


def loopback_signal_test(
    settings: AudioSettings,
    duration_seconds: float = 1.0,
    frequency_hz: float = 523.25,
    amplitude: float = 0.04,
) -> dict[str, object]:
    if not 0 < duration_seconds <= 5:
        raise ValueError("duration_seconds must be between 0 and 5")
    if not 0 < amplitude <= 0.1:
        raise ValueError("amplitude must be between 0 and 0.1")
    import pyaudiowpatch as pyaudio

    with WasapiLoopbackCapture(settings) as capture:
        if not capture.wait_until_running(timeout=10):
            snapshot = capture.snapshot()
            raise RuntimeError(f"capture failed to start: {snapshot.last_error or snapshot.state}")

        active = capture.snapshot().device
        assert active is not None
        with pyaudio.PyAudio() as audio:
            if active.output_index is None:
                raise RuntimeError(f"no render endpoint found for {active.device_id}")
            output = audio.get_device_info_by_index(active.output_index)
            output_rate = int(round(float(output["defaultSampleRate"])))
            output_channels = max(1, min(2, int(output["maxOutputChannels"])))
            frame_count = round(output_rate * duration_seconds)
            radians_per_frame = 2 * np.pi * frequency_hz / output_rate
            phase = np.arange(frame_count, dtype=np.float64) * radians_per_frame
            envelope = np.ones(frame_count, dtype=np.float64)
            fade_frames = min(frame_count // 2, round(output_rate * 0.02))
            if fade_frames:
                fade = np.linspace(0, 1, fade_frames, endpoint=False)
                envelope[:fade_frames] = fade
                envelope[-fade_frames:] = fade[::-1]
            mono = np.asarray(np.sin(phase) * envelope * amplitude * 32767, dtype="<i2")
            pcm = np.repeat(mono[:, None], output_channels, axis=1)
            with audio.open(
                format=pyaudio.paInt16,
                channels=output_channels,
                rate=output_rate,
                output=True,
                output_device_index=int(output["index"]),
            ) as stream:
                stream.write(pcm.tobytes())

        deadline = time.monotonic() + 2.0
        max_dbfs: float | None = None
        signal_chunks = 0
        chunks_checked = 0
        while time.monotonic() < deadline:
            try:
                chunk = capture.get_chunk(timeout=0.5)
            except queue.Empty:
                continue
            chunks_checked += 1
            max_dbfs = chunk.level.dbfs if max_dbfs is None else max(max_dbfs, chunk.level.dbfs)
            signal_chunks += int(not chunk.level.silent)
        snapshot = capture.snapshot()

    passed = signal_chunks > 0 and max_dbfs is not None and max_dbfs >= settings.silence_dbfs + 6
    return {
        "passed": passed,
        "failure_reason": None if passed else "no_loopback_signal_detected",
        "capture_state": str(snapshot.state),
        "device_id": snapshot.device.device_id if snapshot.device else None,
        "tone_frequency_hz": frequency_hz,
        "tone_duration_seconds": duration_seconds,
        "tone_amplitude": amplitude,
        "chunks_checked": chunks_checked,
        "signal_chunks": signal_chunks,
        "max_dbfs": max_dbfs,
        "raw_packets_dropped": snapshot.raw_packets_dropped,
        "output_chunks_dropped": snapshot.output_chunks_dropped,
        "reconnects": snapshot.reconnects,
    }


def stress_audio(
    settings: AudioSettings,
    seconds: float,
    max_memory_growth_mib: float,
    report_path: Path | None = None,
) -> StressReport:
    if seconds <= 0:
        raise ValueError("seconds must be positive")
    if max_memory_growth_mib <= 0:
        raise ValueError("max_memory_growth_mib must be positive")

    try:
        import psutil
    except ImportError as error:
        raise RuntimeError("psutil is required for the stress diagnostic") from error

    process = psutil.Process()
    tracemalloc.start()
    rss_start = process.memory_info().rss
    rss_peak = rss_start
    heap_start, _ = tracemalloc.get_traced_memory()
    started_at = datetime.now(UTC).isoformat()
    started = time.monotonic()
    chunks = 0
    silent_chunks = 0
    sequence_gaps = 0
    timestamp_regressions = 0
    malformed_chunks = 0
    expected_sequence: int | None = None
    previous_timestamp: int | None = None
    device_id: str | None = None
    device_name: str | None = None

    with WasapiLoopbackCapture(settings) as capture:
        if not capture.wait_until_running(timeout=10):
            snapshot = capture.snapshot()
            raise RuntimeError(f"capture failed to start: {snapshot.last_error or snapshot.state}")
        initial = capture.snapshot()
        if initial.device is not None:
            device_id = initial.device.device_id
            device_name = initial.device.name

        deadline = started + seconds
        next_progress = started + 60
        expected_samples = round(settings.sample_rate * settings.chunk_ms / 1000)
        while time.monotonic() < deadline:
            remaining = deadline - time.monotonic()
            try:
                chunk = capture.get_chunk(timeout=max(0.01, min(1.0, remaining)))
            except queue.Empty:
                continue
            chunks += 1
            silent_chunks += int(chunk.level.silent)
            if expected_sequence is not None and chunk.sequence != expected_sequence:
                sequence_gaps += abs(chunk.sequence - expected_sequence)
            expected_sequence = chunk.sequence + 1
            if previous_timestamp is not None and chunk.captured_at_ns <= previous_timestamp:
                timestamp_regressions += 1
            previous_timestamp = chunk.captured_at_ns
            if (
                chunk.sample_rate != settings.sample_rate
                or chunk.samples.ndim != 1
                or len(chunk.samples) != expected_samples
                or chunk.samples.dtype.name != "float32"
            ):
                malformed_chunks += 1
            rss_peak = max(rss_peak, process.memory_info().rss)
            if time.monotonic() >= next_progress:
                snapshot = capture.snapshot()
                print(
                    f"stress {time.monotonic() - started:.0f}/{seconds:.0f}s: "
                    f"chunks={chunks} rss={process.memory_info().rss / 1024**2:.1f} MiB "
                    f"state={snapshot.state} reconnects={snapshot.reconnects}",
                    flush=True,
                )
                next_progress += 60
        snapshot = capture.snapshot()

    elapsed = time.monotonic() - started
    rss_end = process.memory_info().rss
    heap_end, _ = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    max_growth = round(max_memory_growth_mib * 1024**2)
    expected_chunks = seconds * 1000 / settings.chunk_ms
    failures: list[str] = []
    if chunks < expected_chunks * 0.8:
        failures.append(f"received {chunks} chunks; expected at least {expected_chunks * 0.8:.0f}")
    if malformed_chunks:
        failures.append(f"encountered {malformed_chunks} malformed chunks")
    if sequence_gaps:
        failures.append(f"encountered {sequence_gaps} sequence gaps")
    if timestamp_regressions:
        failures.append(f"encountered {timestamp_regressions} timestamp regressions")
    if rss_end - rss_start > max_growth:
        failures.append(
            f"RSS grew {(rss_end - rss_start) / 1024**2:.1f} MiB; limit is "
            f"{max_memory_growth_mib:.1f} MiB"
        )
    if snapshot.state not in {CaptureState.RUNNING, CaptureState.STOPPED}:
        failures.append(f"capture ended in {snapshot.state}: {snapshot.last_error}")

    report = StressReport(
        started_at=started_at,
        requested_seconds=seconds,
        elapsed_seconds=elapsed,
        device_id=device_id,
        device_name=device_name,
        output_sample_rate=settings.sample_rate,
        chunk_ms=settings.chunk_ms,
        chunks_consumed=chunks,
        silent_chunks=silent_chunks,
        sequence_gaps=sequence_gaps,
        timestamp_regressions=timestamp_regressions,
        malformed_chunks=malformed_chunks,
        reconnects=snapshot.reconnects,
        raw_packets_dropped=snapshot.raw_packets_dropped,
        output_chunks_dropped=snapshot.output_chunks_dropped,
        rss_start_bytes=rss_start,
        rss_end_bytes=rss_end,
        rss_peak_bytes=rss_peak,
        rss_growth_bytes=rss_end - rss_start,
        python_heap_growth_bytes=heap_end - heap_start,
        passed=not failures,
        failures=tuple(failures),
    )
    if report_path is not None:
        report.write(report_path)
    return report
