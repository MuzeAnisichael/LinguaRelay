from __future__ import annotations

import math
import os
import queue
import subprocess
import threading
import time
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from lingua_relay.audio.buffer import LatestAudioBuffer
from lingua_relay.audio.devices import WasapiDeviceManager
from lingua_relay.audio.processes import AudioProcessManager
from lingua_relay.audio.processing import FixedSampleChunker, Pcm16MonoResampler, measure_level
from lingua_relay.audio.types import (
    AudioChunk,
    AudioDevice,
    AudioSourceType,
    CaptureSnapshot,
    CaptureState,
)
from lingua_relay.config import AudioSettings


class _RestartCapture(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class _RawPacket:
    pcm: bytes
    captured_at_ns: int


@dataclass(slots=True)
class _Counters:
    chunks_emitted: int = 0
    samples_emitted: int = 0
    raw_packets_dropped: int = 0
    reconnects: int = 0
    last_error: str | None = None


class WasapiLoopbackCapture:
    """Supervised WASAPI loopback capture with bounded, fresh-first output."""

    def __init__(
        self,
        settings: AudioSettings,
        device_manager: WasapiDeviceManager | None = None,
    ) -> None:
        self.settings = settings
        self.devices = device_manager or WasapiDeviceManager()
        capacity = max(1, math.ceil(settings.buffer_seconds * 1000 / settings.chunk_ms))
        self._output = LatestAudioBuffer(capacity)
        self._stop = threading.Event()
        self._running = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self._state = CaptureState.STOPPED
        self._device: AudioDevice | None = None
        self._counters = _Counters()
        self._sequence = 0

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._output.clear()
        with self._lock:
            self._counters = _Counters()
            self._sequence = 0
        self._stop.clear()
        self._running.clear()
        self._set_state(CaptureState.STARTING)
        self._thread = threading.Thread(
            target=self._supervise,
            name=self._thread_name(),
            daemon=True,
        )
        self._thread.start()

    def stop(self, timeout: float = 5.0) -> None:
        self._stop.set()
        thread = self._thread
        if thread is not None:
            thread.join(timeout)
            if thread.is_alive():
                raise TimeoutError("WASAPI capture thread did not stop in time")
        self._thread = None
        self._running.clear()
        self._set_state(CaptureState.STOPPED, device=None)

    def wait_until_running(self, timeout: float = 10.0) -> bool:
        return self._running.wait(timeout)

    def get_chunk(self, timeout: float | None = None) -> AudioChunk:
        return self._output.get(timeout=timeout)

    def snapshot(self) -> CaptureSnapshot:
        buffer = self._output.snapshot()
        with self._lock:
            return CaptureSnapshot(
                state=self._state,
                device=self._device,
                chunks_emitted=self._counters.chunks_emitted,
                samples_emitted=self._counters.samples_emitted,
                raw_packets_dropped=self._counters.raw_packets_dropped,
                output_chunks_dropped=buffer.items_dropped,
                reconnects=self._counters.reconnects,
                last_error=self._counters.last_error,
                queue_depth=buffer.depth,
                queue_capacity=buffer.capacity,
            )

    def __enter__(self) -> WasapiLoopbackCapture:
        self.start()
        return self

    def __exit__(self, *_: object) -> None:
        self.stop()

    def _supervise(self) -> None:
        delay = self.settings.reconnect_initial_seconds
        first_attempt = True
        while not self._stop.is_set():
            self._set_state(CaptureState.STARTING if first_attempt else CaptureState.RECONNECTING)
            try:
                self._run_session()
                delay = self.settings.reconnect_initial_seconds
            except Exception as error:  # the supervisor is the capture fault boundary
                if self._stop.is_set():
                    break
                with self._lock:
                    self._counters.reconnects += 1
                    self._counters.last_error = f"{type(error).__name__}: {error}"
                self._running.clear()
                self._set_state(CaptureState.RECONNECTING, device=None)
                self._stop.wait(delay)
                delay = min(delay * 2, self.settings.reconnect_max_seconds)
            first_attempt = False
        self._running.clear()
        self._set_state(CaptureState.STOPPED, device=None)

    def _run_session(self) -> None:
        try:
            import pyaudiowpatch as pyaudio
        except ImportError as error:
            self._set_state(CaptureState.FAILED)
            raise RuntimeError("PyAudioWPatch is not installed") from error

        device = self._resolve_device()
        source_frames = max(1, round(device.sample_rate * self.settings.raw_frame_ms / 1000))
        raw_duration = source_frames / device.sample_rate
        raw_queue: queue.Queue[_RawPacket] = queue.Queue(
            maxsize=max(8, math.ceil(2 / raw_duration))
        )

        def on_audio(
            pcm: bytes,
            _frame_count: int,
            _time_info: dict[str, float],
            status_flags: int,
        ) -> tuple[bytes, int]:
            if status_flags:
                self._increment_raw_drops()
            packet = _RawPacket(pcm=pcm, captured_at_ns=time.monotonic_ns())
            try:
                raw_queue.put_nowait(packet)
            except queue.Full:
                try:
                    raw_queue.get_nowait()
                except queue.Empty:
                    pass
                else:
                    self._increment_raw_drops()
                try:
                    raw_queue.put_nowait(packet)
                except queue.Full:
                    self._increment_raw_drops()
            return pcm, pyaudio.paComplete if self._stop.is_set() else pyaudio.paContinue

        audio = pyaudio.PyAudio()
        stream = None
        try:
            stream = audio.open(
                format=pyaudio.paInt16,
                channels=device.channels,
                rate=device.sample_rate,
                input=True,
                input_device_index=device.index,
                frames_per_buffer=source_frames,
                stream_callback=on_audio,
                start=False,
            )
            stream.start_stream()
            self._set_state(CaptureState.RUNNING, device=device, clear_error=True)
            self._running.set()
            self._process_session(stream, raw_queue, device, source_frames)
        finally:
            self._running.clear()
            if stream is not None:
                try:
                    if stream.is_active():
                        stream.stop_stream()
                finally:
                    stream.close()
            audio.terminate()

    def _process_session(
        self,
        stream: object,
        raw_queue: queue.Queue[_RawPacket],
        device: AudioDevice,
        source_frames: int,
    ) -> None:
        resampler = Pcm16MonoResampler(
            input_rate=device.sample_rate,
            output_rate=self.settings.sample_rate,
            channels=device.channels,
        )
        output_size = max(1, round(self.settings.sample_rate * self.settings.chunk_ms / 1000))
        chunker = FixedSampleChunker(output_size)
        silence_packet = bytes(source_frames * device.channels * 2)
        raw_duration = source_frames / device.sample_rate
        next_silence_at = time.monotonic() + raw_duration * 2
        next_device_poll = time.monotonic() + self.settings.device_poll_seconds
        next_chunk_at_ns: int | None = None

        while not self._stop.is_set():
            now = time.monotonic()
            timeout = max(0.001, min(raw_duration, next_device_poll - now))
            try:
                packet = raw_queue.get(timeout=timeout)
            except queue.Empty:
                current = time.monotonic()
                if current >= next_silence_at:
                    packet = _RawPacket(silence_packet, time.monotonic_ns())
                    next_silence_at += raw_duration
                    if current - next_silence_at > raw_duration * 5:
                        next_silence_at = current + raw_duration
                else:
                    packet = None
            else:
                next_silence_at = time.monotonic() + raw_duration * 2

            if packet is not None:
                if next_chunk_at_ns is None:
                    next_chunk_at_ns = packet.captured_at_ns - int(raw_duration * 1_000_000_000)
                converted = resampler.push(packet.pcm)
                for samples in chunker.push(converted):
                    self._emit(samples, device, next_chunk_at_ns)
                    next_chunk_at_ns += int(
                        len(samples) * 1_000_000_000 / self.settings.sample_rate
                    )

            current = time.monotonic()
            if current >= next_device_poll:
                self._verify_device(device)
                next_device_poll = current + self.settings.device_poll_seconds
            if not stream.is_active() and not self._stop.is_set():  # type: ignore[attr-defined]
                raise _RestartCapture("WASAPI stream became inactive")

    def _verify_device(self, active: AudioDevice) -> None:
        current = self._resolve_device()
        identity = (
            current.device_id,
            current.index,
            current.output_index,
            current.sample_rate,
            current.channels,
        )
        active_identity = (
            active.device_id,
            active.index,
            active.output_index,
            active.sample_rate,
            active.channels,
        )
        if identity != active_identity:
            raise _RestartCapture(
                f"audio device changed from {active.device_id} to {current.device_id}"
            )

    def _resolve_device(self) -> AudioDevice:
        return self.devices.resolve(self.settings.device)

    @staticmethod
    def _thread_name() -> str:
        return "lingua-relay-system-audio"

    def _emit(self, samples: np.ndarray, device: AudioDevice, captured_at_ns: int) -> None:
        level = measure_level(samples, self.settings.silence_dbfs)
        with self._lock:
            sequence = self._sequence
            self._sequence += 1
            self._counters.chunks_emitted += 1
            self._counters.samples_emitted += len(samples)
        self._output.put(
            AudioChunk(
                samples=samples,
                sequence=sequence,
                captured_at_ns=captured_at_ns,
                sample_rate=self.settings.sample_rate,
                device_id=device.device_id,
                device_name=device.name,
                level=level,
            )
        )

    def _set_state(
        self,
        state: CaptureState,
        *,
        device: AudioDevice | None = None,
        clear_error: bool = False,
    ) -> None:
        with self._lock:
            self._state = state
            self._device = device
            if clear_error:
                self._counters.last_error = None

    def _increment_raw_drops(self) -> None:
        with self._lock:
            self._counters.raw_packets_dropped += 1


class WasapiMicrophoneCapture(WasapiLoopbackCapture):
    """WASAPI input capture using the same bounded normalization path as loopback."""

    def _resolve_device(self) -> AudioDevice:
        return self.devices.resolve_microphone(self.settings.microphone_device)

    @staticmethod
    def _thread_name() -> str:
        return "lingua-relay-microphone"


class _ProcessStream:
    def __init__(self, process: subprocess.Popen[bytes]) -> None:
        self.process = process

    def is_active(self) -> bool:
        return self.process.poll() is None


class ProcessLoopbackCapture(WasapiLoopbackCapture):
    """True per-process WASAPI loopback backed by the bundled native helper."""

    _SOURCE_RATE = 48_000
    _SOURCE_CHANNELS = 2

    def __init__(
        self,
        settings: AudioSettings,
        *,
        helper_path: Path,
        process_manager: AudioProcessManager | None = None,
    ) -> None:
        super().__init__(settings)
        self.helper_path = helper_path
        self.processes = process_manager or AudioProcessManager()

    @staticmethod
    def _thread_name() -> str:
        return "lingua-relay-process-audio"

    def _run_session(self) -> None:
        if not self.helper_path.is_file():
            self._set_state(CaptureState.FAILED)
            raise RuntimeError(
                "process audio helper is missing; reinstall LinguaRelay or rebuild the helper"
            )
        target = self.processes.resolve(self.settings.process_id, self.settings.process_name)
        device = AudioDevice(
            device_id=target.selector,
            index=target.process_id,
            name=target.name,
            sample_rate=self._SOURCE_RATE,
            channels=self._SOURCE_CHANNELS,
            source_type=AudioSourceType.PROCESS,
        )
        source_frames = max(1, round(self._SOURCE_RATE * self.settings.raw_frame_ms / 1000))
        raw_duration = source_frames / self._SOURCE_RATE
        raw_queue: queue.Queue[_RawPacket] = queue.Queue(
            maxsize=max(8, math.ceil(2 / raw_duration))
        )
        startupinfo = None
        if os.name == "nt":
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        process = subprocess.Popen(
            [str(self.helper_path), "--process-id", str(target.process_id)],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            startupinfo=startupinfo,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        assert process.stdout is not None
        reader = threading.Thread(
            target=self._read_helper,
            args=(process.stdout, raw_queue, source_frames),
            name="lingua-relay-process-audio-reader",
            daemon=True,
        )
        reader.start()
        try:
            self._set_state(CaptureState.RUNNING, device=device, clear_error=True)
            self._running.set()
            self._process_session(_ProcessStream(process), raw_queue, device, source_frames)
        except _RestartCapture as error:
            detail = self._helper_error(process)
            raise _RestartCapture(detail or str(error)) from error
        finally:
            self._running.clear()
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=2)
            reader.join(timeout=2)
            process.stdout.close()
            if process.stderr is not None:
                process.stderr.close()

    def _read_helper(
        self,
        stream: object,
        raw_queue: queue.Queue[_RawPacket],
        source_frames: int,
    ) -> None:
        frame_bytes = source_frames * self._SOURCE_CHANNELS * 2
        pending = bytearray()
        while not self._stop.is_set():
            chunk = stream.read(frame_bytes - len(pending))  # type: ignore[attr-defined]
            if not chunk:
                return
            pending.extend(chunk)
            if len(pending) < frame_bytes:
                continue
            packet = _RawPacket(bytes(pending), time.monotonic_ns())
            pending.clear()
            try:
                raw_queue.put_nowait(packet)
            except queue.Full:
                with suppress(queue.Empty):
                    raw_queue.get_nowait()
                self._increment_raw_drops()
                try:
                    raw_queue.put_nowait(packet)
                except queue.Full:
                    self._increment_raw_drops()

    def _verify_device(self, active: AudioDevice) -> None:
        current = self.processes.resolve(active.index, self.settings.process_name)
        if current.process_id != active.index:
            raise _RestartCapture(
                f"audio target process restarted from {active.index} to {current.process_id}"
            )

    @staticmethod
    def _helper_error(process: subprocess.Popen[bytes]) -> str:
        if process.poll() is None or process.stderr is None:
            return ""
        try:
            return process.stderr.read().decode("utf-8", errors="replace").strip()
        except OSError:
            return ""


def resolve_process_capture_helper(resource_dir: Path) -> Path:
    candidates = (
        resource_dir / "native" / "LinguaRelay.AudioCapture.exe",
        resource_dir
        / "native"
        / "ProcessAudioCapture"
        / "bin"
        / "Release"
        / "net10.0-windows10.0.19041.0"
        / "win-x64"
        / "publish"
        / "LinguaRelay.AudioCapture.exe",
    )
    return next((candidate for candidate in candidates if candidate.is_file()), candidates[0])


def create_audio_capture(settings: AudioSettings, *, resource_dir: Path) -> WasapiLoopbackCapture:
    if settings.source == "system":
        return WasapiLoopbackCapture(settings)
    if settings.source == "microphone":
        return WasapiMicrophoneCapture(settings)
    if settings.source == "process":
        return ProcessLoopbackCapture(
            settings,
            helper_path=resolve_process_capture_helper(resource_dir),
        )
    raise ValueError(f"unsupported audio source: {settings.source}")
