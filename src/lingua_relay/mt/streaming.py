from __future__ import annotations

import math
import queue
import threading
import time
from typing import TYPE_CHECKING

from lingua_relay.asr.buffer import InferenceBacklog, LatestEventBuffer
from lingua_relay.asr.types import AsrEvent
from lingua_relay.config import TranslationSettings
from lingua_relay.events import CaptionEvent
from lingua_relay.history import JsonlHistory
from lingua_relay.mt.types import TranslationRequest, TranslationResult, TranslationSnapshot
from lingua_relay.translation import TranslationRouteRegistry

if TYPE_CHECKING:
    from lingua_relay.telemetry import TraceCollector


class StreamingTranslationEngine:
    """Bounded ASR-to-MT worker that preserves finals and source-text fallback."""

    def __init__(
        self,
        registry: TranslationRouteRegistry,
        settings: TranslationSettings,
        *,
        history: JsonlHistory | None = None,
        output_timeout: float = 1.0,
        trace: TraceCollector | None = None,
    ) -> None:
        if not math.isfinite(output_timeout) or output_timeout < 0:
            raise ValueError("output_timeout must be finite and nonnegative")
        self.registry = registry
        self.settings = settings
        self.history = history
        self._output_timeout = output_timeout
        self._trace = trace
        self._requests = InferenceBacklog(settings.queue_capacity)
        self._events = LatestEventBuffer(settings.event_queue_capacity)
        self._thread: threading.Thread | None = None
        self._running = threading.Event()
        self._aborted = threading.Event()
        self._stopped = False
        self._lock = threading.Lock()
        self._events_emitted = 0
        self._stale_results_dropped = 0
        self._translation_errors = 0
        self._history_errors = 0
        self._last_error: str | None = None
        self._overloaded = False
        self._final_requests_aborted = 0
        self._final_outputs_rejected = 0
        self._final_events_aborted = 0

    def start(self) -> None:
        if self._stopped:
            raise RuntimeError("a stopped translation engine cannot restart; create a new engine")
        if self._thread is not None and self._thread.is_alive():
            return
        self._running.set()
        self._thread = threading.Thread(target=self._work, name="lingua-relay-mt", daemon=True)
        self._thread.start()

    def submit(self, event: AsrEvent, *, target: str, timeout: float = 0.0) -> bool:
        if not math.isfinite(timeout) or timeout < 0:
            raise ValueError("timeout must be finite and nonnegative")
        if self._stopped or not self._running.is_set():
            raise RuntimeError("streaming translation is not running")
        if event.state == "partial" and not self.settings.translate_partials:
            return False
        if not event.text.strip():
            return False
        request = TranslationRequest(
            event=event,
            source=event.language,
            target=target,
            state=event.state,
            segment_id=event.segment_id,
            revision=event.revision,
            submitted_at_ns=time.monotonic_ns(),
        )
        accepted = (
            self._requests.put_partial(request)  # type: ignore[arg-type]
            if event.state == "partial"
            else self._requests.put_final(request, timeout=timeout)  # type: ignore[arg-type]
        )
        if accepted:
            self._record(request, "mt_submitted", request.submitted_at_ns)
        return accepted

    @property
    def worker_alive(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def request_stop(self) -> None:
        """Close admission, leaving accepted work/output available for cooperative draining."""
        self._stopped = True
        self._running.clear()
        self._requests.close()

    def finish_stop(self, timeout: float = 30.0) -> None:
        """Join within the caller's remaining budget; never release a live worker."""
        if not math.isfinite(timeout) or timeout < 0:
            raise ValueError("timeout must be finite and nonnegative")
        if self._thread is not None:
            self._thread.join(timeout)
            if self._thread.is_alive():
                raise TimeoutError("translation worker did not stop in time")
        self._events.close()
        self._thread = None
        self._stopped = True

    def stop(self, timeout: float = 30.0) -> None:
        if not math.isfinite(timeout) or timeout < 0:
            raise ValueError("timeout must be finite and nonnegative")
        deadline = time.monotonic() + timeout
        self.request_stop()
        try:
            self.finish_stop(max(0.0, deadline - time.monotonic()))
        except TimeoutError:
            self.abort()
            raise

    def abort(self) -> None:
        """Cancel queued work and suppress late native results; do not kill the worker."""
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
            self._record(item, "cancelled")  # type: ignore[arg-type]

    def _record(self, request: TranslationRequest, stage: str, at_ns: int | None = None) -> None:
        if self._trace is not None:
            self._trace.record(request.segment_id, request.revision, stage, at_ns)

    def _discard_cancelled(self, request: TranslationRequest, *, completed: bool) -> bool:
        if not self._aborted.is_set():
            return False
        with self._lock:
            self._final_requests_aborted += int(request.state == "final")
            self._stale_results_dropped += int(completed)
        self._record(request, "suppressed" if completed else "cancelled")
        return True

    def get_event(self, timeout: float | None = None) -> CaptionEvent:
        return self._events.get(timeout)  # type: ignore[return-value]

    def snapshot(self) -> TranslationSnapshot:
        request = self._requests.snapshot()
        event_depth, event_capacity, output_drops = self._events.snapshot()
        with self._lock:
            return TranslationSnapshot(
                running=self._running.is_set(),
                requests_added=request.items_added,
                partials_replaced=request.partials_replaced,
                partials_dropped=request.partials_dropped + output_drops,
                stale_results_dropped=self._stale_results_dropped,
                events_emitted=self._events_emitted,
                translation_errors=self._translation_errors,
                queue_depth=request.depth,
                queue_capacity=request.capacity,
                event_queue_depth=event_depth,
                event_queue_capacity=event_capacity,
                last_error=self._last_error,
                worker_alive=self.worker_alive,
                overloaded=self._overloaded,
                final_requests_added=request.finals_added,
                final_submit_rejections=request.final_submit_rejections,
                final_requests_aborted=self._final_requests_aborted,
                final_outputs_rejected=self._final_outputs_rejected,
                final_events_aborted=self._final_events_aborted,
                history_errors=self._history_errors,
            )

    def _work(self) -> None:
        try:
            self._run_worker()
        finally:
            self._stopped = True
            self._running.clear()
            self._requests.close()
            self._events.close()

    def _run_worker(self) -> None:
        while True:
            try:
                request = self._requests.get(timeout=0.2)  # type: ignore[assignment]
            except queue.Empty:
                if self._requests.snapshot().depth == 0 and not self._running.is_set():
                    break
                continue
            assert isinstance(request, TranslationRequest)
            if self._discard_cancelled(request, completed=False):
                continue
            self._record(request, "mt_started")
            error_text: str | None = None
            try:
                route = self.registry.resolve(request.source, request.target)
                result = route.translator.translate(
                    request.event.text, source=request.source, target=request.target
                )
                if isinstance(result, str):
                    result = TranslationResult(result, request.source, request.target, 0.0)
            except Exception as error:  # provider boundary: keep the source caption alive
                result = TranslationResult("", request.source, request.target, 0.0)
                error_text = f"{type(error).__name__}: {error}"
                with self._lock:
                    self._translation_errors += 1
                    self._last_error = error_text
                self._record(request, "failed")

            completed_ns = time.monotonic_ns()
            self._record(request, "mt_completed", completed_ns)
            if self._discard_cancelled(request, completed=True):
                continue

            caption = CaptionEvent(
                source_text=request.event.text,
                translated_text=result.text,
                source_language=request.source,
                target_language=request.target,
                state=request.event.state,  # type: ignore[arg-type]
                started_at_ms=request.event.started_at_ms,
                ended_at_ms=request.event.ended_at_ms,
                segment_id=request.segment_id,
                revision=request.revision,
                timings_ms={
                    **request.event.timings_ms,
                    "translation": result.inference_ms,
                    "translation_queue": max(
                        0.0,
                        (completed_ns - request.submitted_at_ns) / 1e6 - result.inference_ms,
                    ),
                    "asr_to_caption": (completed_ns - request.event.emitted_at_ns) / 1e6,
                },
                error=error_text,
            )
            if self._events.put(caption, timeout=self._output_timeout):  # type: ignore[arg-type]
                with self._lock:
                    self._events_emitted += 1
                if caption.state == "final" and self.history is not None:
                    try:
                        self.history.append(caption)
                    except OSError as error:
                        # The caption is already published. A disk failure must not
                        # kill translation or replay it; report persistence separately.
                        with self._lock:
                            self._history_errors += 1
                            self._last_error = f"History write failed: {type(error).__name__}"
                        if self._trace is not None:
                            self._trace.increment("mt_history_errors")
            elif self._discard_cancelled(request, completed=True):
                continue
            elif request.state == "final":
                with self._lock:
                    self._final_outputs_rejected += 1
                    self._overloaded = True
                    self._last_error = "translation output queue exceeded its wait deadline"
                self._record(request, "rejected")
                # Keep already-published finals readable; only explicit abort discards them.
                self._cancel_pending(discard_output=False)
            else:
                self._record(request, "suppressed")
