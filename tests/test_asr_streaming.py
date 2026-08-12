import queue
import threading
import time

import numpy as np

from lingua_relay.asr.streaming import StreamingAsrEngine, StreamingSegmenter
from lingua_relay.asr.types import AsrResult
from lingua_relay.audio.types import AudioChunk, AudioLevel
from lingua_relay.config import AsrSettings


def chunk(sequence: int, *, silent: bool = False, captured_at_ns: int | None = None) -> AudioChunk:
    samples = np.zeros(5_120, dtype=np.float32) if silent else np.full(5_120, 0.1, np.float32)
    return AudioChunk(
        samples=samples,
        sequence=sequence,
        captured_at_ns=captured_at_ns if captured_at_ns is not None else sequence * 320_000_000,
        sample_rate=16_000,
        device_id="test",
        device_name="test",
        level=AudioLevel(
            rms=0.0 if silent else 0.1, peak=0.0 if silent else 0.1, dbfs=-20, silent=silent
        ),
    )


def test_segmenter_emits_overlapping_partial_windows_and_final() -> None:
    settings = AsrSettings(
        min_speech_ms=320,
        min_silence_ms=640,
        partial_interval_ms=640,
        max_window_seconds=0.96,
        max_segment_seconds=2.0,
    )
    segmenter = StreamingSegmenter(settings)

    assert segmenter.push(chunk(0), language="zh") == ()
    first = segmenter.push(chunk(1), language="zh")
    assert len(first) == 1 and first[0].state == "partial"
    assert len(first[0].samples) == 10_240
    segmenter.push(chunk(2), language="zh")
    second = segmenter.push(chunk(3), language="zh")
    assert len(second) == 1 and len(second[0].samples) == 15_360
    segmenter.push(chunk(4, silent=True), language="zh")
    final = segmenter.push(chunk(5, silent=True), language="zh")

    assert len(final) == 1
    assert final[0].state == "final"
    assert len(final[0].samples) == 30_720
    assert final[0].language == "zh"


def test_segmenter_never_uses_automatic_language_detection() -> None:
    segmenter = StreamingSegmenter(AsrSettings())

    try:
        segmenter.push(chunk(0), language="auto")
    except ValueError as error:
        assert "unsupported ASR language" in str(error)
    else:
        raise AssertionError("auto language must not be accepted")


def test_segmenter_uses_short_pause_after_preferred_duration() -> None:
    settings = AsrSettings(
        min_speech_ms=320,
        min_silence_ms=960,
        preferred_silence_ms=320,
        partial_interval_ms=640,
        preferred_segment_seconds=0.64,
        max_window_seconds=1.0,
        max_segment_seconds=2.0,
    )
    segmenter = StreamingSegmenter(settings)

    segmenter.push(chunk(0), language="ja")
    segmenter.push(chunk(1), language="ja")
    final = segmenter.push(chunk(2, silent=True), language="ja")

    assert len(final) == 1
    assert final[0].state == "final"
    assert len(final[0].samples) == 15_360


def test_segmenter_hard_caps_continuous_speech() -> None:
    settings = AsrSettings(
        min_speech_ms=320,
        min_silence_ms=640,
        preferred_silence_ms=320,
        partial_interval_ms=640,
        preferred_segment_seconds=0.64,
        max_caption_seconds=1.28,
        max_window_seconds=24.0,
        max_segment_seconds=24.0,
    )
    segmenter = StreamingSegmenter(settings)

    requests = ()
    for sequence in range(4):
        requests = segmenter.push(chunk(sequence), language="ko")

    assert len(requests) == 1
    assert requests[0].state == "final"
    assert len(requests[0].samples) == 20_480


class FakeRecognizer:
    def __init__(self) -> None:
        self.calls = 0

    def transcribe(
        self, samples: np.ndarray, *, language: str, vad_filter: bool | None = None
    ) -> AsrResult:
        self.calls += 1
        text = "hello" if self.calls == 1 else "hello world"
        return AsrResult(
            text=text,
            language=language,
            duration_ms=len(samples) / 16,
            inference_ms=0.1,
        )


def test_engine_emits_partial_and_final_with_stability_state() -> None:
    recognizer = FakeRecognizer()
    settings = AsrSettings(
        min_speech_ms=320,
        min_silence_ms=640,
        partial_interval_ms=640,
        max_window_seconds=1.0,
        max_segment_seconds=2.0,
    )
    engine = StreamingAsrEngine(recognizer, settings)
    base = time.monotonic_ns()
    engine.start()
    engine.submit_chunk(chunk(0, captured_at_ns=base), language="en")
    engine.submit_chunk(chunk(1, captured_at_ns=base + 320_000_000), language="en")
    partial = engine.get_event(timeout=2)
    engine.submit_chunk(chunk(2, silent=True, captured_at_ns=base + 640_000_000), language="en")
    engine.submit_chunk(chunk(3, silent=True, captured_at_ns=base + 960_000_000), language="en")
    final = engine.get_event(timeout=2)
    engine.stop()

    assert partial.state == "partial"
    assert partial.unstable_text == "hello"
    assert final.state == "final"
    assert final.stable_text == "hello world"
    assert final.unstable_text == ""
    assert engine.snapshot().inference_queue_depth == 0


def test_no_event_is_emitted_for_only_silence() -> None:
    engine = StreamingAsrEngine(FakeRecognizer(), AsrSettings())
    engine.start()
    engine.submit_chunk(chunk(0, silent=True), language="ko")

    try:
        engine.get_event(timeout=0.01)
    except queue.Empty:
        pass
    else:
        raise AssertionError("silence should not produce ASR events")
    engine.stop()


class SlowRecognizer:
    def transcribe(
        self, samples: np.ndarray, *, language: str, vad_filter: bool | None = None
    ) -> AsrResult:
        time.sleep(0.01)
        return AsrResult(
            text="bounded queue",
            language=language,
            duration_ms=len(samples) / 16,
            inference_ms=10,
        )


def test_engine_replaces_partials_under_overload_without_exceeding_capacity() -> None:
    settings = AsrSettings(
        min_speech_ms=320,
        min_silence_ms=320,
        partial_interval_ms=320,
        max_window_seconds=2,
        max_segment_seconds=4,
        inference_queue_capacity=2,
        event_queue_capacity=4,
    )
    engine = StreamingAsrEngine(SlowRecognizer(), settings)
    engine.start()
    for sequence in range(10):
        engine.submit_chunk(chunk(sequence), language="en")
    engine.submit_chunk(chunk(10, silent=True), language="en")
    engine.stop(timeout=5)
    snapshot = engine.snapshot()

    assert snapshot.inference_queue_depth <= snapshot.inference_queue_capacity
    assert snapshot.partials_replaced > 0
    assert snapshot.inference_errors == 0


class PunctuatedRecognizer:
    def transcribe(
        self, samples: np.ndarray, *, language: str, vad_filter: bool | None = None
    ) -> AsrResult:
        return AsrResult(
            text="Sentence complete.",
            language=language,
            duration_ms=len(samples) / 16,
            inference_ms=0.1,
        )


def test_stable_sentence_punctuation_finishes_the_active_segment() -> None:
    settings = AsrSettings(
        min_speech_ms=320,
        min_silence_ms=640,
        partial_interval_ms=320,
        punctuation_boundary_min_seconds=0.64,
        max_window_seconds=4,
        max_segment_seconds=4,
    )
    engine = StreamingAsrEngine(PunctuatedRecognizer(), settings)
    engine.start()
    engine.submit_chunk(chunk(0), language="en")
    first = engine.get_event(timeout=2)
    engine.submit_chunk(chunk(1), language="en")
    second = engine.get_event(timeout=2)
    assert first.stable_text == ""
    assert second.stable_text.endswith(".")

    engine.submit_chunk(chunk(2), language="en")
    final = engine.get_event(timeout=2)
    engine.stop()

    assert final.state == "final"
    assert final.segment_id == second.segment_id


class BlockingRecognizer:
    def __init__(self) -> None:
        self.started = threading.Event()
        self.release = threading.Event()
        self.calls = 0

    def transcribe(
        self, samples: np.ndarray, *, language: str, vad_filter: bool | None = None
    ) -> AsrResult:
        self.calls += 1
        if self.calls == 1:
            self.started.set()
            assert self.release.wait(2)
        return AsrResult(
            text=f"partial {self.calls}",
            language=language,
            duration_ms=len(samples) / 16,
            inference_ms=0.1,
        )


def test_completed_partial_is_shown_even_when_a_newer_partial_is_waiting() -> None:
    recognizer = BlockingRecognizer()
    settings = AsrSettings(partial_interval_ms=320, max_window_seconds=4, max_segment_seconds=4)
    engine = StreamingAsrEngine(recognizer, settings)
    engine.start()
    engine.submit_chunk(chunk(0), language="en")
    assert recognizer.started.wait(2)
    engine.submit_chunk(chunk(1), language="en")
    recognizer.release.set()

    first = engine.get_event(timeout=2)
    engine.stop()

    assert first.revision == 1
    assert first.text == "partial 1"
