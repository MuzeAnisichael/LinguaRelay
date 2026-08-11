from __future__ import annotations

import queue
import threading
import time
from dataclasses import dataclass
from uuid import uuid4

import numpy as np

from lingua_relay.asr.buffer import InferenceBacklog, LatestEventBuffer
from lingua_relay.asr.types import AsrEvent, AsrSnapshot, InferenceRequest
from lingua_relay.audio.types import AudioChunk
from lingua_relay.config import AsrSettings
from lingua_relay.languages import SUPPORTED_LANGUAGES, normalize_language
from lingua_relay.ports import SpeechRecognizer
from lingua_relay.stabilizer import StablePrefix


@dataclass(slots=True)
class _ActiveSegment:
    segment_id: str
    language: str
    started_at_ns: int
    ended_at_ns: int
    samples: list[np.ndarray]
    sample_count: int
    silence_samples: int
    revision: int
    next_partial_samples: int


class StreamingSegmenter:
    """Energy-gated overlapping Whisper windows over fixed M1 audio chunks.

    The low-cost M1 silence flag performs online endpointing. Final requests
    also enable faster-whisper's integrated Silero VAD by default.
    """

    def __init__(self, settings: AsrSettings, sample_rate: int = 16_000) -> None:
        self.settings = settings
        self.sample_rate = sample_rate
        self._active: _ActiveSegment | None = None
        self._min_speech_samples = round(settings.min_speech_ms * sample_rate / 1000)
        self._min_silence_samples = round(settings.min_silence_ms * sample_rate / 1000)
        self._preferred_silence_samples = round(settings.preferred_silence_ms * sample_rate / 1000)
        self._partial_step_samples = round(settings.partial_interval_ms * sample_rate / 1000)
        self._max_window_samples = round(settings.max_window_seconds * sample_rate)
        self._max_segment_samples = round(
            min(settings.max_segment_seconds, settings.max_caption_seconds) * sample_rate
        )
        self._preferred_segment_samples = min(
            round(settings.preferred_segment_seconds * sample_rate), self._max_segment_samples
        )

    def push(self, chunk: AudioChunk, *, language: str) -> tuple[InferenceRequest, ...]:
        normalized = _validate_language(language)
        if chunk.sample_rate != self.sample_rate:
            raise ValueError(
                f"streaming ASR expects {self.sample_rate} Hz, got {chunk.sample_rate} Hz"
            )
        if chunk.samples.ndim != 1:
            raise ValueError("streaming ASR expects mono audio")

        requests: list[InferenceRequest] = []
        if self._active is not None and self._active.language != normalized:
            requests.append(self._finish())

        if self._active is None:
            if chunk.level.silent:
                return tuple(requests)
            self._active = _ActiveSegment(
                segment_id=str(uuid4()),
                language=normalized,
                started_at_ns=chunk.captured_at_ns,
                ended_at_ns=chunk.captured_at_ns,
                samples=[],
                sample_count=0,
                silence_samples=0,
                revision=0,
                next_partial_samples=max(self._min_speech_samples, self._partial_step_samples),
            )

        active = self._active
        assert active is not None
        samples = np.asarray(chunk.samples, dtype=np.float32)
        active.samples.append(samples)
        active.sample_count += len(samples)
        active.ended_at_ns = chunk.captured_at_ns + round(len(samples) * 1e9 / self.sample_rate)
        active.silence_samples = active.silence_samples + len(samples) if chunk.level.silent else 0

        if active.sample_count >= self._max_segment_samples:
            requests.append(self._finish())
            return tuple(requests)
        if (
            active.sample_count >= self._preferred_segment_samples
            and active.silence_samples >= self._preferred_silence_samples
        ):
            speech_samples = active.sample_count - active.silence_samples
            if speech_samples >= self._min_speech_samples:
                requests.append(self._finish())
            else:
                self._active = None
            return tuple(requests)
        if active.silence_samples >= self._min_silence_samples:
            speech_samples = active.sample_count - active.silence_samples
            if speech_samples >= self._min_speech_samples:
                requests.append(self._finish())
            else:
                self._active = None
            return tuple(requests)
        if active.sample_count >= active.next_partial_samples:
            requests.append(self._request("partial"))
            active.next_partial_samples = active.sample_count + self._partial_step_samples
        return tuple(requests)

    def flush(self) -> InferenceRequest | None:
        if self._active is None:
            return None
        if self._active.sample_count < self._min_speech_samples:
            self._active = None
            return None
        return self._finish()

    def _finish(self) -> InferenceRequest:
        request = self._request("final")
        self._active = None
        return request

    def _request(self, state: str) -> InferenceRequest:
        active = self._active
        assert active is not None
        active.revision += 1
        joined = np.concatenate(active.samples)
        if state == "partial" and len(joined) > self._max_window_samples:
            joined = joined[-self._max_window_samples :]
        joined = np.ascontiguousarray(joined, dtype=np.float32)
        joined.setflags(write=False)
        now = time.monotonic_ns()
        return InferenceRequest(
            samples=joined,
            language=active.language,
            state=state,  # type: ignore[arg-type]
            segment_id=active.segment_id,
            revision=active.revision,
            started_at_ns=active.started_at_ns,
            ended_at_ns=active.ended_at_ns,
            submitted_at_ns=now,
        )


class StreamingAsrEngine:
    """One inference worker with bounded, final-preserving ASR backpressure."""

    def __init__(self, recognizer: SpeechRecognizer, settings: AsrSettings) -> None:
        self.recognizer = recognizer
        self.settings = settings
        self.segmenter = StreamingSegmenter(settings)
        self._requests = InferenceBacklog(settings.inference_queue_capacity)
        self._events = LatestEventBuffer(settings.event_queue_capacity)
        self._thread: threading.Thread | None = None
        self._running = threading.Event()
        self._lock = threading.Lock()
        self._latest_revision: dict[str, int] = {}
        self._stabilizers: dict[str, StablePrefix] = {}
        self._events_emitted = 0
        self._stale_results_dropped = 0
        self._inference_errors = 0
        self._last_error: str | None = None

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._work, name="lingua-relay-asr", daemon=True)
        self._running.set()
        self._thread.start()

    def submit_chunk(self, chunk: AudioChunk, *, language: str) -> None:
        if not self._running.is_set():
            raise RuntimeError("streaming ASR is not running")
        for request in self.segmenter.push(chunk, language=language):
            self._submit(request)

    def flush(self) -> None:
        request = self.segmenter.flush()
        if request is not None:
            self._submit(request)

    def stop(self, timeout: float = 30.0) -> None:
        if not self._running.is_set():
            return
        self.flush()
        self._running.clear()
        self._requests.close()
        thread = self._thread
        if thread is not None:
            thread.join(timeout)
            if thread.is_alive():
                raise TimeoutError("ASR inference worker did not stop in time")
        self._events.close()
        self._thread = None

    def get_event(self, timeout: float | None = None) -> AsrEvent:
        return self._events.get(timeout)

    def snapshot(self) -> AsrSnapshot:
        requests = self._requests.snapshot()
        event_depth, event_capacity, output_partials_dropped = self._events.snapshot()
        with self._lock:
            return AsrSnapshot(
                running=self._running.is_set(),
                requests_added=requests.items_added,
                partials_replaced=requests.partials_replaced,
                partials_dropped=requests.partials_dropped + output_partials_dropped,
                stale_results_dropped=self._stale_results_dropped,
                events_emitted=self._events_emitted,
                inference_errors=self._inference_errors,
                inference_queue_depth=requests.depth,
                inference_queue_capacity=requests.capacity,
                event_queue_depth=event_depth,
                event_queue_capacity=event_capacity,
                last_error=self._last_error,
            )

    def _submit(self, request: InferenceRequest) -> None:
        accepted = (
            self._requests.put_partial(request)
            if request.state == "partial"
            else self._requests.put_final(request)
        )
        if not accepted and request.state == "final":
            raise TimeoutError("bounded ASR queue could not accept a final request")
        if accepted:
            with self._lock:
                self._latest_revision[request.segment_id] = request.revision

    def _work(self) -> None:
        while True:
            try:
                request = self._requests.get(timeout=0.2)
            except queue.Empty:
                if self._requests.snapshot().depth == 0 and not self._running.is_set():
                    break
                if self._thread is None:
                    break
                continue
            try:
                result = self.recognizer.transcribe(
                    request.samples,
                    language=request.language,
                    vad_filter=request.state == "final" and self.settings.vad_enabled,
                )
            except Exception as error:  # model inference is this worker's fault boundary
                with self._lock:
                    self._inference_errors += 1
                    self._last_error = f"{type(error).__name__}: {error}"
                    if request.state == "final":
                        self._latest_revision.pop(request.segment_id, None)
                        self._stabilizers.pop(request.segment_id, None)
                continue

            completed_ns = time.monotonic_ns()
            with self._lock:
                latest = self._latest_revision.get(request.segment_id, request.revision)
            if request.state == "partial" and request.revision < latest:
                with self._lock:
                    self._stale_results_dropped += 1
                continue
            if request.state == "partial" and not result.text.strip():
                continue

            stabilizer = self._stabilizers.setdefault(
                request.segment_id, StablePrefix(language=request.language)
            )
            if request.state == "final":
                stabilized = stabilizer.finalize_state(result.text)
                self._stabilizers.pop(request.segment_id, None)
                with self._lock:
                    self._latest_revision.pop(request.segment_id, None)
            else:
                stabilized = stabilizer.update_state(result.text)

            event = AsrEvent(
                text=stabilized.text,
                stable_text=stabilized.stable_text,
                unstable_text=stabilized.unstable_text,
                newly_stable_text=stabilized.newly_stable_text,
                language=request.language,
                state=request.state,
                segment_id=request.segment_id,
                revision=request.revision,
                started_at_ms=request.started_at_ns // 1_000_000,
                ended_at_ms=request.ended_at_ns // 1_000_000,
                emitted_at_ns=completed_ns,
                timings_ms={
                    "audio_to_event": (completed_ns - request.started_at_ns) / 1e6,
                    "queue": max(
                        0.0,
                        (completed_ns - request.submitted_at_ns) / 1e6 - result.inference_ms,
                    ),
                    "asr": result.inference_ms,
                },
            )
            if self._events.put(event):
                with self._lock:
                    self._events_emitted += 1


def _validate_language(language: str) -> str:
    normalized = normalize_language(language)
    if normalized not in SUPPORTED_LANGUAGES:
        raise ValueError(f"unsupported ASR language: {language}")
    return normalized
