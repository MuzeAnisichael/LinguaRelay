from __future__ import annotations

import queue
import threading
import time
from collections import deque
from collections.abc import Callable

from lingua_relay.asr.buffer import InferenceBacklog, LatestEventBuffer
from lingua_relay.config import CorrectionSettings
from lingua_relay.correction.controls import CircuitBreaker, RateLimiter
from lingua_relay.correction.glossary import glossary_for_route
from lingua_relay.correction.types import (
    CorrectionProvider,
    CorrectionRequest,
    CorrectionSnapshot,
    GlossaryEntry,
)
from lingua_relay.events import CaptionEvent
from lingua_relay.history import JsonlHistory


class AsynchronousRevisionEngine:
    """Bounded correction worker; provider latency never blocks the fast-caption caller."""

    def __init__(
        self,
        provider: CorrectionProvider,
        settings: CorrectionSettings,
        *,
        history: JsonlHistory | None = None,
        glossary: tuple[GlossaryEntry, ...] = (),
        on_status: Callable[[str, str], None] | None = None,
    ) -> None:
        self.provider = provider
        self.settings = settings
        self.history = history
        self.glossary = glossary
        self.on_status = on_status or (lambda _state, _message: None)
        self._requests = InferenceBacklog(settings.queue_capacity)
        self._events = LatestEventBuffer(settings.event_queue_capacity)
        self._limiter = RateLimiter(settings.requests_per_minute)
        self._circuit = CircuitBreaker(settings.failure_threshold, settings.recovery_seconds)
        self._contexts: dict[tuple[str, str], deque[CaptionEvent]] = {}
        self._latest_revision: dict[str, int] = {}
        self._running = threading.Event()
        self._enabled = threading.Event()
        self._enabled.set()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self._revisions_emitted = 0
        self._unchanged_results = 0
        self._stale_results_dropped = 0
        self._rate_limited = 0
        self._circuit_rejected = 0
        self._provider_errors = 0
        self._output_drops = 0
        self._last_error: str | None = None

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._running.set()
        self._thread = threading.Thread(
            target=self._work, name="lingua-relay-correction", daemon=True
        )
        self._thread.start()
        self.on_status("ready", self._scope_message("修正 provider 已就绪"))

    def submit(self, event: CaptionEvent) -> bool:
        if not self._running.is_set() or not self._enabled.is_set():
            return False
        if event.state not in {"partial", "final"} or not event.translated_text.strip():
            return False
        with self._lock:
            route = (event.source_language, event.target_language)
            route_context = self._contexts.setdefault(
                route, deque(maxlen=max(1, self.settings.context_segments))
            )
            context = (
                tuple(route_context)[-self.settings.context_segments :]
                if self.settings.context_segments
                else ()
            )
            if event.state == "final":
                route_context.append(event)
            self._latest_revision[event.segment_id] = event.revision
        request = CorrectionRequest(
            event=event,
            context=context,
            glossary=glossary_for_route(
                self.glossary, event.source_language, event.target_language
            ),
            state=event.state,
            segment_id=event.segment_id,
            revision=event.revision,
            submitted_at_ns=time.monotonic_ns(),
        )
        if event.state == "partial":
            return self._requests.put_partial(request)  # type: ignore[arg-type]
        return self._requests.put_final(request, timeout=0)  # type: ignore[arg-type]

    def set_enabled(self, enabled: bool) -> None:
        if enabled:
            self._enabled.set()
        else:
            self._enabled.clear()

    def stop(self, timeout: float = 15.0) -> None:
        if not self._running.is_set():
            return
        self._running.clear()
        self._requests.close()
        if self._thread is not None:
            self._thread.join(timeout)
            if self._thread.is_alive():
                raise TimeoutError("correction worker did not stop in time")
        self._events.close()
        self._thread = None

    def get_event(self, timeout: float | None = None) -> CaptionEvent:
        return self._events.get(timeout)  # type: ignore[return-value]

    def snapshot(self) -> CorrectionSnapshot:
        request = self._requests.snapshot()
        event_depth, event_capacity, buffer_drops = self._events.snapshot()
        circuit = self._circuit.snapshot()
        with self._lock:
            return CorrectionSnapshot(
                running=self._running.is_set(),
                circuit_state=circuit.state,
                processing_scope=self.provider.scope,
                requests_added=request.items_added,
                partials_replaced=request.partials_replaced,
                partials_dropped=request.partials_dropped,
                revisions_emitted=self._revisions_emitted,
                unchanged_results=self._unchanged_results,
                stale_results_dropped=self._stale_results_dropped,
                rate_limited=self._rate_limited,
                circuit_rejected=self._circuit_rejected,
                provider_errors=self._provider_errors,
                output_drops=self._output_drops + buffer_drops,
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
                    return
                continue
            assert isinstance(request, CorrectionRequest)
            if not self._enabled.is_set():
                continue
            if not self._circuit.allow_request():
                with self._lock:
                    self._circuit_rejected += 1
                self.on_status("circuit_open", self._scope_message("修正暂不可用，快译继续"))
                continue
            if not self._limiter.acquire():
                with self._lock:
                    self._rate_limited += 1
                self.on_status("rate_limited", self._scope_message("修正已限流，快译继续"))
                continue
            self.on_status("processing", self._scope_message("正在异步修正"))
            try:
                result = self.provider.revise(request)
            except Exception as error:  # provider boundary: the fast event already survived
                message = f"{type(error).__name__}: {error}"
                self._circuit.record_failure()
                with self._lock:
                    self._provider_errors += 1
                    self._last_error = message
                self.on_status("error", self._scope_message("修正失败，快译继续"))
                continue
            self._circuit.record_success()
            if not self._enabled.is_set():
                continue
            with self._lock:
                latest = self._latest_revision.get(request.segment_id, request.revision)
                if request.state == "final":
                    self._latest_revision.pop(request.segment_id, None)
            if request.state == "partial" and request.revision < latest:
                with self._lock:
                    self._stale_results_dropped += 1
                continue
            if result.text.strip() == request.event.translated_text.strip():
                with self._lock:
                    self._unchanged_results += 1
                    self._last_error = None
                self.on_status("ready", self._scope_message("修正 provider 已就绪"))
                continue
            completed_ns = time.monotonic_ns()
            revised = CaptionEvent(
                source_text=request.event.source_text,
                translated_text=result.text,
                source_language=request.event.source_language,
                target_language=request.event.target_language,
                state="revised",
                started_at_ms=request.event.started_at_ms,
                ended_at_ms=request.event.ended_at_ms,
                segment_id=request.event.segment_id,
                revision=request.event.revision + 1,
                timings_ms={
                    **request.event.timings_ms,
                    "correction": result.inference_ms,
                    "correction_queue": max(
                        0.0,
                        (completed_ns - request.submitted_at_ns) / 1e6 - result.inference_ms,
                    ),
                },
                parent_revision=request.event.revision,
                original_translation=request.event.translated_text,
                revision_source="llm_correction",
                processing_scope=result.scope,
                correction_provider=result.provider,
                correction_model=result.model,
            )
            if self.history is not None and request.state == "final":
                self.history.append(revised)
            if self._events.put(revised, timeout=0):  # type: ignore[arg-type]
                with self._lock:
                    self._revisions_emitted += 1
                    self._last_error = None
            else:
                with self._lock:
                    self._output_drops += 1
            self.on_status("ready", self._scope_message("修正 provider 已就绪"))

    def _scope_message(self, message: str) -> str:
        prefix = "本地处理" if self.provider.scope == "local" else "云端传输"
        return f"{prefix} · {message}"
