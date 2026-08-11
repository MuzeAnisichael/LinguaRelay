from __future__ import annotations

import queue
import threading
import time

from lingua_relay.asr.buffer import InferenceBacklog, LatestEventBuffer
from lingua_relay.asr.types import AsrEvent
from lingua_relay.config import TranslationSettings
from lingua_relay.events import CaptionEvent
from lingua_relay.history import JsonlHistory
from lingua_relay.mt.types import TranslationRequest, TranslationResult, TranslationSnapshot
from lingua_relay.translation import TranslationRouteRegistry


class StreamingTranslationEngine:
    """Bounded ASR-to-MT worker that preserves finals and source-text fallback."""

    def __init__(
        self,
        registry: TranslationRouteRegistry,
        settings: TranslationSettings,
        *,
        history: JsonlHistory | None = None,
    ) -> None:
        self.registry = registry
        self.settings = settings
        self.history = history
        self._requests = InferenceBacklog(settings.queue_capacity)
        self._events = LatestEventBuffer(settings.event_queue_capacity)
        self._thread: threading.Thread | None = None
        self._running = threading.Event()
        self._lock = threading.Lock()
        self._latest_revision: dict[str, int] = {}
        self._events_emitted = 0
        self._stale_results_dropped = 0
        self._translation_errors = 0
        self._last_error: str | None = None

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._running.set()
        self._thread = threading.Thread(target=self._work, name="lingua-relay-mt", daemon=True)
        self._thread.start()

    def submit(self, event: AsrEvent, *, target: str) -> bool:
        if not self._running.is_set():
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
            else self._requests.put_final(request)  # type: ignore[arg-type]
        )
        if not accepted and event.state == "final":
            raise TimeoutError("bounded translation queue could not accept a final request")
        if accepted:
            with self._lock:
                self._latest_revision[event.segment_id] = event.revision
        return accepted

    def stop(self, timeout: float = 30.0) -> None:
        if not self._running.is_set():
            return
        self._running.clear()
        self._requests.close()
        if self._thread is not None:
            self._thread.join(timeout)
            if self._thread.is_alive():
                raise TimeoutError("translation worker did not stop in time")
        self._events.close()
        self._thread = None

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
            )

    def _work(self) -> None:
        while True:
            try:
                request = self._requests.get(timeout=0.2)  # type: ignore[assignment]
            except queue.Empty:
                if self._requests.snapshot().depth == 0 and not self._running.is_set():
                    break
                continue
            assert isinstance(request, TranslationRequest)
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

            completed_ns = time.monotonic_ns()
            with self._lock:
                latest = self._latest_revision.get(request.segment_id, request.revision)
            if request.state == "partial" and request.revision < latest:
                with self._lock:
                    self._stale_results_dropped += 1
                continue
            if request.state == "final":
                with self._lock:
                    self._latest_revision.pop(request.segment_id, None)

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
            if self._events.put(caption):  # type: ignore[arg-type]
                with self._lock:
                    self._events_emitted += 1
                if caption.state == "final" and self.history is not None:
                    self.history.append(caption)
