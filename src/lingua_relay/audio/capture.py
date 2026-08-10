from __future__ import annotations

import math
import queue
import threading
import time
from dataclasses import dataclass

import numpy as np

from lingua_relay.audio.buffer import LatestAudioBuffer
from lingua_relay.audio.devices import WasapiDeviceManager
from lingua_relay.audio.processing import FixedSampleChunker, Pcm16MonoResampler, measure_level
from lingua_relay.audio.types import AudioChunk, AudioDevice, CaptureSnapshot, CaptureState
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
            name="lingua-relay-wasapi",
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

        device = self.devices.resolve(self.settings.device)
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
        current = self.devices.resolve(self.settings.device)
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
