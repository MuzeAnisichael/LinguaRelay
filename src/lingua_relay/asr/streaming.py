from __future__ import annotations

import math
import queue
import re
import threading
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING
from uuid import uuid4

import numpy as np

from lingua_relay.asr.buffer import InferenceBacklog, LatestEventBuffer
from lingua_relay.asr.types import AsrEvent, AsrSnapshot, InferenceRequest
from lingua_relay.audio.types import AudioChunk
from lingua_relay.config import AsrSettings
from lingua_relay.languages import SUPPORTED_LANGUAGES, normalize_language
from lingua_relay.ports import SpeechRecognizer
from lingua_relay.stabilizer import StablePrefix

if TYPE_CHECKING:
    from lingua_relay.telemetry import TraceCollector


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
        self._medium_partial_step_samples = max(
            self._partial_step_samples, round(640 * sample_rate / 1000)
        )
        self._long_partial_step_samples = max(
            self._partial_step_samples, round(960 * sample_rate / 1000)
        )
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
            active.next_partial_samples = active.sample_count + self._next_partial_step(
                active.sample_count
            )
        return tuple(requests)

    def _next_partial_step(self, sample_count: int) -> int:
        """Keep the first words responsive without repeatedly decoding long audio every 320 ms."""
        if not self.settings.adaptive_partial_enabled:
            return self._partial_step_samples
        elapsed_seconds = sample_count / self.sample_rate
        if elapsed_seconds < 1.6:
            return self._partial_step_samples
        if elapsed_seconds < 3.2:
            return self._medium_partial_step_samples
        return self._long_partial_step_samples

    def flush(self) -> InferenceRequest | None:
        if self._active is None:
            return None
        if self._active.sample_count < self._min_speech_samples:
            self._active = None
            return None
        return self._finish()

    def finish_segment(self, segment_id: str) -> InferenceRequest | None:
        """Finish the active segment when ASR has confirmed a sentence boundary."""
        active = self._active
        if active is None or active.segment_id != segment_id:
            return None
        if active.sample_count < self._min_speech_samples:
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

    def __init__(
        self,
        recognizer: SpeechRecognizer,
        settings: AsrSettings,
        *,
        output_timeout: float = 1.0,
        trace: TraceCollector | None = None,
    ) -> None:
        if not math.isfinite(output_timeout) or output_timeout < 0:
            raise ValueError("output_timeout must be finite and nonnegative")
        self.recognizer = recognizer
        self.settings = settings
        self._output_timeout = output_timeout
        self._trace = trace
        self.segmenter = StreamingSegmenter(settings)
        self._requests = InferenceBacklog(settings.inference_queue_capacity)
        self._events = LatestEventBuffer(settings.event_queue_capacity)
        self._thread: threading.Thread | None = None
        self._running = threading.Event()
        self._aborted = threading.Event()
        self._stopped = False
        self._lock = threading.Lock()
        self._submission_lock = threading.RLock()
        self._stabilizers: dict[str, StablePrefix] = {}
        self._sentence_boundaries: queue.SimpleQueue[str] = queue.SimpleQueue()
        self._boundary_segments: set[str] = set()
        self._events_emitted = 0
        self._stale_results_dropped = 0
        self._hallucinations_suppressed = 0
        self._inference_errors = 0
        self._last_error: str | None = None
        self._overloaded = False
        self._final_requests_aborted = 0
        self._final_outputs_rejected = 0
        self._final_events_aborted = 0

    def start(self) -> None:
        if self._stopped:
            raise RuntimeError("a stopped ASR engine cannot restart; create a new engine")
        if self._thread is not None and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._work, name="lingua-relay-asr", daemon=True)
        self._running.set()
        self._thread.start()

    def submit_chunk(self, chunk: AudioChunk, *, language: str, timeout: float = 0.0) -> None:
        deadline = _deadline(timeout)
        if not self._submission_lock.acquire(timeout=timeout):
            raise TimeoutError("ASR segmenter is busy")
        try:
            if self._stopped or not self._running.is_set():
                raise RuntimeError("streaming ASR is not running")
            self._finish_sentence_boundaries(deadline)
            for request in self.segmenter.push(chunk, language=language):
                self._submit(request, timeout=max(0.0, deadline - time.monotonic()))
        finally:
            self._submission_lock.release()

    def flush(self, timeout: float = 0.0) -> None:
        deadline = _deadline(timeout)
        if not self._submission_lock.acquire(timeout=timeout):
            raise TimeoutError("ASR segmenter is busy")
        try:
            self._finish_sentence_boundaries(deadline)
            request = self.segmenter.flush()
            if request is not None:
                self._submit(request, timeout=max(0.0, deadline - time.monotonic()))
        finally:
            self._submission_lock.release()

    @property
    def worker_alive(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def request_stop(self, *, flush_timeout: float = 0.0) -> None:
        """Close admission even if the last segment cannot fit in the final queue."""
        _deadline(flush_timeout)
        if self._stopped:
            return
        self._stopped = True
        try:
            self.flush(timeout=flush_timeout)
        finally:
            self._running.clear()
            self._requests.close()

    def finish_stop(self, timeout: float = 30.0) -> None:
        """Join only; callers keep draining output until their shared deadline."""
        _deadline(timeout)
        thread = self._thread
        if thread is not None:
            thread.join(timeout)
            if thread.is_alive():
                raise TimeoutError("ASR inference worker did not stop in time")
        self._events.close()
        self._thread = None
        self._stopped = True

    def stop(self, timeout: float = 30.0) -> None:
        deadline = _deadline(timeout)
        flush_error: TimeoutError | None = None
        try:
            self.request_stop(flush_timeout=0.0)
        except TimeoutError as error:
            flush_error = error
        try:
            self.finish_stop(max(0.0, deadline - time.monotonic()))
        except TimeoutError:
            self.abort()
            raise
        if flush_error is not None:
            raise flush_error

    def abort(self) -> None:
        """Cancel queue work/output, retaining ownership of any live native call."""
        self._cancel_pending(discard_output=True)

    def _cancel_pending(self, *, discard_output: bool) -> None:
        self._stopped = True
        self._running.clear()
        self._aborted.set()
        requests = self._requests.abort()
        events = self._events.abort() if discard_output else ()
        self._events.close()
        with self._lock:
            self._final_requests_aborted += sum(item.state == "final" for item in requests)
            self._final_events_aborted += sum(item.state == "final" for item in events)
        for item in (*requests, *events):
            self._record(item, "cancelled")

    def _record(
        self, request: InferenceRequest | AsrEvent, stage: str, at_ns: int | None = None
    ) -> None:
        if self._trace is not None:
            self._trace.record(request.segment_id, request.revision, stage, at_ns)

    def _discard_cancelled(self, request: InferenceRequest, *, completed: bool) -> bool:
        if not self._aborted.is_set():
            return False
        with self._lock:
            self._final_requests_aborted += int(request.state == "final")
            self._stale_results_dropped += int(completed)
        self._record(request, "suppressed" if completed else "cancelled")
        return True

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
                hallucinations_suppressed=self._hallucinations_suppressed,
                events_emitted=self._events_emitted,
                inference_errors=self._inference_errors,
                inference_queue_depth=requests.depth,
                inference_queue_capacity=requests.capacity,
                event_queue_depth=event_depth,
                event_queue_capacity=event_capacity,
                last_error=self._last_error,
                worker_alive=self.worker_alive,
                overloaded=self._overloaded,
                final_requests_added=requests.finals_added,
                final_submit_rejections=requests.final_submit_rejections,
                final_requests_aborted=self._final_requests_aborted,
                final_outputs_rejected=self._final_outputs_rejected,
                final_events_aborted=self._final_events_aborted,
            )

    def _submit(self, request: InferenceRequest, *, timeout: float = 0.0) -> None:
        accepted = (
            self._requests.put_partial(request)
            if request.state == "partial"
            else self._requests.put_final(request, timeout=timeout)
        )
        if self._trace is not None:
            self._record(request, "audio_start", request.started_at_ns)
            self._record(request, "audio_end", request.ended_at_ns)
            if accepted:
                self._record(request, "asr_submitted", request.submitted_at_ns)
            else:
                self._record(request, "rejected")
        if not accepted and request.state == "final":
            with self._lock:
                self._overloaded = True
                self._last_error = "ASR final request queue exceeded its wait deadline"
            raise TimeoutError("bounded ASR queue could not accept a final request")

    def _finish_sentence_boundaries(self, deadline: float) -> None:
        while True:
            try:
                segment_id = self._sentence_boundaries.get_nowait()
            except queue.Empty:
                return
            request = self.segmenter.finish_segment(segment_id)
            if request is not None:
                self._submit(request, timeout=max(0.0, deadline - time.monotonic()))

    def _work(self) -> None:
        try:
            self._run_worker()
        finally:
            self._stopped = True
            self._running.clear()
            self._requests.close()
            self._events.close()
            self._stabilizers.clear()
            with self._lock:
                self._boundary_segments.clear()

    def _run_worker(self) -> None:
        while True:
            try:
                request = self._requests.get(timeout=0.2)
            except queue.Empty:
                if self._requests.snapshot().depth == 0 and not self._running.is_set():
                    break
                if self._thread is None:
                    break
                continue
            if self._discard_cancelled(request, completed=False):
                continue
            self._record(request, "asr_started")
            try:
                result = self.recognizer.transcribe(
                    request.samples,
                    language=request.language,
                    vad_filter=request.state == "final" and self.settings.vad_enabled,
                )
            except Exception as error:  # model inference is this worker's fault boundary
                if self._discard_cancelled(request, completed=True):
                    continue
                with self._lock:
                    self._inference_errors += 1
                    self._last_error = f"{type(error).__name__}: {error}"
                    if request.state == "final":
                        self._stabilizers.pop(request.segment_id, None)
                        self._boundary_segments.discard(request.segment_id)
                self._record(request, "failed")
                continue

            completed_ns = time.monotonic_ns()
            self._record(request, "asr_completed", completed_ns)
            if self._discard_cancelled(request, completed=True):
                continue
            if self.settings.suppress_credit_hallucinations and _is_caption_credit_hallucination(
                result.text
            ):
                with self._lock:
                    self._hallucinations_suppressed += 1
                    if request.state == "final":
                        self._stabilizers.pop(request.segment_id, None)
                        self._boundary_segments.discard(request.segment_id)
                self._record(request, "suppressed")
                continue
            if request.state == "partial" and not result.text.strip():
                self._record(request, "suppressed")
                continue

            stabilizer = self._stabilizers.setdefault(
                request.segment_id, StablePrefix(language=request.language)
            )
            if request.state == "final":
                stabilized = stabilizer.finalize_state(result.text)
                self._stabilizers.pop(request.segment_id, None)
                with self._lock:
                    self._boundary_segments.discard(request.segment_id)
            else:
                stabilized = stabilizer.update_state(result.text)
                duration_seconds = len(request.samples) / self.segmenter.sample_rate
                if (
                    self.settings.punctuation_boundary_enabled
                    and duration_seconds >= self.settings.punctuation_boundary_min_seconds
                    and _has_sentence_boundary(stabilized.stable_text)
                ):
                    with self._lock:
                        if request.segment_id not in self._boundary_segments:
                            self._boundary_segments.add(request.segment_id)
                            self._sentence_boundaries.put(request.segment_id)

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
            if self._events.put(event, timeout=self._output_timeout):
                with self._lock:
                    self._events_emitted += 1
            elif self._discard_cancelled(request, completed=True):
                continue
            elif request.state == "final":
                with self._lock:
                    self._final_outputs_rejected += 1
                    self._overloaded = True
                    self._last_error = "ASR output queue exceeded its wait deadline"
                self._record(request, "rejected")
                self._cancel_pending(discard_output=False)
            else:
                self._record(request, "suppressed")


def _deadline(timeout: float) -> float:
    if not math.isfinite(timeout) or timeout < 0:
        raise ValueError("timeout must be finite and nonnegative")
    return time.monotonic() + timeout


def _validate_language(language: str) -> str:
    normalized = normalize_language(language)
    if normalized not in SUPPORTED_LANGUAGES:
        raise ValueError(f"unsupported ASR language: {language}")
    return normalized


def _has_sentence_boundary(text: str) -> bool:
    return text.rstrip().endswith(("。", "！", "？", ".", "!", "?", "…", "；", ";", "\n"))


def _is_caption_credit_hallucination(text: str) -> bool:
    """Detect short credit templates Whisper commonly emits over music or silence."""
    normalized = re.sub(r"[\W_]+", "", text, flags=re.UNICODE).casefold()
    if not normalized or len(normalized) > 64:
        return False
    if "zitherharp" in normalized:
        return True
    prefixes = (
        "字幕制作人",
        "字幕制作",
        "字幕由",
        "subtitlesby",
        "subtitleby",
        "captionsby",
        "captionedby",
        "字幕作成",
        "字幕制作",
        "자막제작",
        "자막제공",
    )
    return normalized.startswith(prefixes)
