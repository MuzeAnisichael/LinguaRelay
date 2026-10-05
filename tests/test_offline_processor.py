from __future__ import annotations

import threading
import wave
from dataclasses import replace
from types import SimpleNamespace

import pytest

from lingua_relay.asr.types import AsrResult, AsrSegment, AsrWord
from lingua_relay.config import Settings
from lingua_relay.offline.processor import OfflineProcessor, ProcessingOptions
from lingua_relay.offline.project import Cue, OfflineProjectStore


class _Recognizer:
    def transcribe_offline(
        self, _path, *, language: str, beam_size: int, cancel=None, on_progress=None
    ):
        assert language == "en"
        assert beam_size == 5
        assert cancel is not None
        if on_progress:
            on_progress(1.0)
        return AsrResult(
            text="Hello world. This is a test.",
            language="en",
            duration_ms=3100,
            inference_ms=50,
            segments=(
                AsrSegment(
                    0,
                    3.1,
                    "Hello world. This is a test.",
                    avg_logprob=-0.1,
                    words=(
                        AsrWord(0, 0.5, " Hello", 0.99),
                        AsrWord(0.5, 1.2, " world.", 0.98),
                        AsrWord(1.5, 1.8, " This", 0.97),
                        AsrWord(1.8, 2.1, " is", 0.97),
                        AsrWord(2.1, 2.3, " a", 0.97),
                        AsrWord(2.3, 3.1, " test.", 0.96),
                    ),
                ),
            ),
        )


class _Translator:
    def load(self):
        return None

    def translate(self, text: str, *, source: str, target: str):
        assert (source, target) == ("en", "zh")
        return SimpleNamespace(text=f"译：{text}")


def test_offline_processor_creates_readable_time_aligned_cues(tmp_path) -> None:
    audio = tmp_path / "recording.wav"
    with wave.open(str(audio), "wb") as stream:
        stream.setnchannels(1)
        stream.setsampwidth(2)
        stream.setframerate(16_000)
        stream.writeframes(b"\0\0" * 16_000)
    store = OfflineProjectStore(tmp_path / "projects")
    project = store.create_project(
        title="Meeting",
        kind="recording",
        source_language="en",
        target_language="zh",
    )
    store.update_project(project.id, audio_path=audio)
    messages: list[str] = []
    processor = OfflineProcessor(
        store,
        Settings(),
        tmp_path / "models",
        recognizer_factory=lambda _settings: _Recognizer(),
        translator_factory=lambda _settings: _Translator(),
    )
    result = processor.process(
        project.id,
        ProcessingOptions(asr_model="small", quality="balanced"),
        on_progress=lambda _value, message: messages.append(message),
    )

    cues = store.list_cues(project.id)
    assert result.status == "completed"
    assert [cue.source_text for cue in cues] == ["Hello world.", "This is a test."]
    assert cues[0].translated_text == "译：Hello world."
    assert cues[0].start_ms == 0
    assert cues[-1].end_ms == 3100
    assert messages[-1] == "后期识别与翻译完成"


def test_offline_llm_failure_keeps_local_translation(tmp_path) -> None:
    audio = tmp_path / "recording.wav"
    with wave.open(str(audio), "wb") as stream:
        stream.setnchannels(1)
        stream.setsampwidth(2)
        stream.setframerate(16_000)
        stream.writeframes(b"\0\0" * 16_000)
    store = OfflineProjectStore(tmp_path / "projects")
    project = store.create_project(
        title="LLM fallback",
        kind="recording",
        source_language="en",
        target_language="zh",
    )
    store.update_project(project.id, audio_path=audio)
    defaults = Settings()
    settings = replace(
        defaults,
        correction=replace(defaults.correction, provider="local", model="test-model"),
    )

    class _FailedProvider:
        def revise(self, _request):
            raise TimeoutError("offline")

    processor = OfflineProcessor(
        store,
        settings,
        tmp_path / "models",
        recognizer_factory=lambda _settings: _Recognizer(),
        translator_factory=lambda _settings: _Translator(),
        correction_factory=lambda _settings: _FailedProvider(),
    )
    result = processor.process(
        project.id,
        ProcessingOptions(asr_model="small", quality="balanced", use_llm=True),
    )
    assert result.status == "completed"
    assert "大模型精修失败" in result.error
    assert store.list_cues(project.id)[0].translated_text.startswith("译：")


@pytest.mark.parametrize("context_segments", [0, 1, 2])
def test_offline_llm_context_is_bounded_and_zero_disables_history(
    tmp_path, context_segments
) -> None:
    audio = tmp_path / "recording.wav"
    audio.touch()
    store = OfflineProjectStore(tmp_path / "projects")
    project = store.create_project(
        title="Context test", kind="recording", source_language="en", target_language="zh"
    )
    store.update_project(project.id, audio_path=audio)
    defaults = Settings()
    settings = replace(
        defaults,
        correction=replace(
            defaults.correction, provider="local", model="test", context_segments=context_segments
        ),
    )
    contexts = []
    closed = []

    class Recognizer:
        def transcribe_offline(self, *_args, **_kwargs):
            return AsrResult(
                text="",
                language="en",
                duration_ms=4000,
                inference_ms=1,
                segments=tuple(
                    AsrSegment(index, index + 1, f"Sentence {index}.") for index in range(4)
                ),
            )

    class Provider:
        def revise(self, request):
            contexts.append(request.context)
            return SimpleNamespace(text=f"精修：{request.event.source_text}")

        def close(self):
            closed.append(True)

    processor = OfflineProcessor(
        store,
        settings,
        tmp_path / "models",
        recognizer_factory=lambda _settings: Recognizer(),
        translator_factory=lambda _settings: _Translator(),
        correction_factory=lambda _settings: Provider(),
    )
    processor.process(project.id, ProcessingOptions(use_llm=True))

    assert closed == [True]
    assert [len(context) for context in contexts] == [
        min(index, context_segments) for index in range(4)
    ]
    if context_segments:
        assert contexts[-1][-1].source_text == "Sentence 2."
        assert contexts[-1][-1].translated_text == "精修：Sentence 2."


def test_offline_cancel_during_last_llm_call_does_not_mark_completed(tmp_path) -> None:
    audio = tmp_path / "recording.wav"
    audio.touch()
    store = OfflineProjectStore(tmp_path / "projects")
    project = store.create_project(
        title="Cancel test", kind="recording", source_language="en", target_language="zh"
    )
    store.update_project(project.id, audio_path=audio)
    defaults = Settings()
    settings = replace(
        defaults, correction=replace(defaults.correction, provider="local", model="test")
    )
    cancelled = threading.Event()
    closed = []

    class Recognizer:
        def transcribe_offline(self, *_args, **_kwargs):
            return AsrResult(
                text="Hello",
                language="en",
                duration_ms=1000,
                inference_ms=1,
                segments=(AsrSegment(0, 1, "Hello"),),
            )

    class Provider:
        def revise(self, request):
            cancelled.set()
            return SimpleNamespace(text="你好")

        def close(self):
            closed.append(True)

    processor = OfflineProcessor(
        store,
        settings,
        tmp_path / "models",
        recognizer_factory=lambda _settings: Recognizer(),
        translator_factory=lambda _settings: _Translator(),
        correction_factory=lambda _settings: Provider(),
    )
    with pytest.raises(InterruptedError):
        processor.process(project.id, ProcessingOptions(use_llm=True), cancel=cancelled)

    assert store.get_project(project.id).status == "cancelled"
    assert not store.list_cues(project.id)
    assert closed == [True]


def _controlled_processor(tmp_path, settings, provider, *, count=3, translator=None):
    audio = tmp_path / "controlled.wav"
    audio.touch()
    store = OfflineProjectStore(tmp_path / "controlled-projects")
    project = store.create_project(
        title="Controls test", kind="recording", source_language="en", target_language="zh"
    )
    store.update_project(project.id, audio_path=audio)

    class Recognizer:
        def transcribe_offline(self, *_args, **_kwargs):
            return AsrResult(
                text="",
                language="en",
                duration_ms=count * 1000,
                inference_ms=1,
                segments=tuple(
                    AsrSegment(index, index + 1, f"Cue {index}.") for index in range(count)
                ),
            )

    processor = OfflineProcessor(
        store,
        settings,
        tmp_path / "models",
        recognizer_factory=lambda _settings: Recognizer(),
        translator_factory=lambda _settings: translator or _Translator(),
        correction_factory=lambda _settings: provider,
    )
    return processor, store, project


def test_offline_rate_limit_waits_without_dropping_cues(monkeypatch, tmp_path):
    from lingua_relay.correction.controls import RateLimiter
    from lingua_relay.offline import processor as module

    clock = [0.0]
    calls = []
    closed = []

    class ClockEvent(threading.Event):
        def wait(self, timeout=None):
            clock[0] += timeout or 0
            return self.is_set()

    monkeypatch.setattr(module, "RateLimiter", lambda rpm: RateLimiter(rpm, clock=lambda: clock[0]))
    defaults = Settings()
    settings = replace(
        defaults,
        correction=replace(
            defaults.correction, provider="local", model="test", requests_per_minute=1
        ),
    )
    provider = SimpleNamespace(
        revise=lambda request: (
            calls.append(clock[0]) or SimpleNamespace(text=f"精修：{request.event.source_text}")
        ),
        close=lambda: closed.append(True),
    )
    processor, store, project = _controlled_processor(tmp_path, settings, provider)
    messages = []
    result = processor.process(
        project.id,
        ProcessingOptions(use_llm=True),
        cancel=ClockEvent(),
        on_progress=lambda _value, text: messages.append(text),
    )
    assert result.status == "completed"
    assert len(calls) == len(store.list_cues(project.id)) == 3
    assert calls[1] >= 60 and calls[2] - calls[1] >= 60
    assert any("等待大模型调用额度" in message for message in messages)
    assert all(cue.translated_text.startswith("精修：") for cue in store.list_cues(project.id))
    assert closed == [True]


def test_offline_circuit_skips_failed_service_and_retries_after_recovery(monkeypatch, tmp_path):
    from lingua_relay.correction.controls import CircuitBreaker
    from lingua_relay.offline import processor as module

    clock = [0.0]
    times = iter([0.0, 1.0, 11.0, 12.0, 22.0])
    calls = []
    monkeypatch.setattr(
        module,
        "CircuitBreaker",
        lambda threshold, recovery: CircuitBreaker(threshold, recovery, clock=lambda: clock[0]),
    )

    class Translator(_Translator):
        def translate(self, text, *, source, target):
            clock[0] = next(times)
            return super().translate(text, source=source, target=target)

    class Provider:
        def revise(self, request):
            calls.append(request.event.source_text)
            if len(calls) < 3:
                raise TimeoutError("controlled failure")
            return SimpleNamespace(text="已恢复精修")

    defaults = Settings()
    settings = replace(
        defaults,
        correction=replace(
            defaults.correction,
            provider="local",
            model="test",
            failure_threshold=1,
            recovery_seconds=10,
        ),
    )
    processor, store, project = _controlled_processor(
        tmp_path, settings, Provider(), count=5, translator=Translator()
    )
    result = processor.process(project.id, ProcessingOptions(use_llm=True))
    assert calls == ["Cue 0.", "Cue 2.", "Cue 4."]
    assert result.status == "completed"
    assert result.error.startswith("4 条字幕")
    cues = store.list_cues(project.id)
    assert len(cues) == 5
    assert all(cue.translated_text.startswith("译：") for cue in cues[:4])
    assert cues[4].translated_text == "已恢复精修"


def test_offline_rate_wait_cancel_does_not_reserve_half_open_probe(monkeypatch, tmp_path):
    from lingua_relay.correction.controls import CircuitBreaker
    from lingua_relay.offline import processor as module

    clock = [0.0]
    circuit = CircuitBreaker(1, 1, clock=lambda: clock[0])
    permits = iter([True, False])
    closed = []
    monkeypatch.setattr(module, "CircuitBreaker", lambda *_args: circuit)
    monkeypatch.setattr(
        module, "RateLimiter", lambda _rpm: SimpleNamespace(acquire=lambda: next(permits))
    )

    class CancelOnWait(threading.Event):
        def wait(self, _timeout=None):
            self.set()
            return True

    class Provider:
        def revise(self, request):
            raise TimeoutError("controlled failure")

        def close(self):
            closed.append(True)

    class Translator(_Translator):
        def translate(self, text, *, source, target):
            clock[0] += 2
            return super().translate(text, source=source, target=target)

    defaults = Settings()
    settings = replace(
        defaults, correction=replace(defaults.correction, provider="local", model="test")
    )
    processor, store, project = _controlled_processor(
        tmp_path, settings, Provider(), count=2, translator=Translator()
    )
    with pytest.raises(InterruptedError):
        processor.process(project.id, ProcessingOptions(use_llm=True), cancel=CancelOnWait())
    assert store.get_project(project.id).status == "cancelled"
    assert closed == [True]
    assert circuit.allow_request()  # Cancellation did not leave a probe latched in flight.


def test_pre_cancelled_processing_does_not_start_media_or_models(tmp_path, monkeypatch):
    processor, store, project = _controlled_processor(tmp_path, Settings(), None)
    cancelled = threading.Event()
    cancelled.set()

    def unexpected(*_args, **_kwargs):
        pytest.fail("Pre-cancelled work must not start")

    monkeypatch.setattr(processor, "_prepare_audio", unexpected)
    with pytest.raises(InterruptedError):
        processor.process(project.id, ProcessingOptions(), cancel=cancelled, on_progress=unexpected)
    assert store.get_project(project.id).status == "cancelled"
    assert not store.list_cues(project.id)


@pytest.mark.parametrize("stage", ["recognizer_factory", "translator_factory", "translator_load"])
def test_cancellation_during_model_loading_does_not_start_next_stage(tmp_path, stage):
    processor, store, project = _controlled_processor(tmp_path, Settings(), None)
    cancelled = threading.Event()
    calls = []

    def unexpected(*_args, **_kwargs):
        pytest.fail("No later work may run after a cancelled model load")

    if stage == "recognizer_factory":

        def recognizer_factory(_settings):
            cancelled.set()
            return SimpleNamespace(transcribe_offline=unexpected)

        processor._recognizer_factory = recognizer_factory
    else:

        def translator_factory(_settings):
            calls.append("factory")
            if stage == "translator_factory":
                cancelled.set()
                return SimpleNamespace(load=unexpected, translate=unexpected)

            def load():
                calls.append("load")
                cancelled.set()

            return SimpleNamespace(load=load, translate=unexpected)

        processor._translator_factory = translator_factory
    with pytest.raises(InterruptedError):
        processor.process(project.id, ProcessingOptions(), cancel=cancelled)
    assert store.get_project(project.id).status == "cancelled"
    assert not store.list_cues(project.id)
    if stage == "translator_load":
        assert calls == ["factory", "load"]


def test_cancel_after_final_progress_preserves_cues_and_allows_retry(tmp_path):
    processor, store, project = _controlled_processor(tmp_path, Settings(), None, count=1)
    store.replace_cues(project.id, [Cue(None, project.id, 0, 0, 1000, "Old", "手动修改")])
    previous = store.list_cues(project.id)
    cancelled = threading.Event()
    updates = []

    def progress(value, _message):
        updates.append(value)
        if value >= 0.97:
            cancelled.set()

    with pytest.raises(InterruptedError):
        processor.process(project.id, ProcessingOptions(), cancel=cancelled, on_progress=progress)
    assert store.get_project(project.id).status == "cancelled"
    assert store.list_cues(project.id) == previous
    assert 1.0 not in updates

    result = processor.process(project.id, ProcessingOptions(), cancel=threading.Event())
    assert result.status == "completed"
    assert result.error == ""
    assert store.list_cues(project.id)[0].source_text == "Cue 0."


def test_cancellation_during_decode_keeps_reusable_audio_without_starting_asr(
    tmp_path, monkeypatch
):
    from lingua_relay.offline import processor as module

    processor, store, project = _controlled_processor(tmp_path, Settings(), None)
    store.update_project(project.id, audio_path=None, source_path=tmp_path / "source.mp3")
    cancelled = threading.Event()
    monkeypatch.setattr(module, "probe_media", lambda _path: SimpleNamespace(duration_ms=1000))
    decoded = []

    def decode(_source, output):
        output.touch()
        decoded.append(output)
        cancelled.set()

    def unexpected(_settings):
        pytest.fail("ASR must not load after cancelled media preparation")

    monkeypatch.setattr(module, "decode_media_to_wav", decode)
    processor._recognizer_factory = unexpected
    with pytest.raises(InterruptedError):
        processor.process(project.id, ProcessingOptions(), cancel=cancelled)
    loaded = store.get_project(project.id)
    assert loaded.status == "cancelled"
    assert loaded.audio_path == decoded[0]
    assert loaded.audio_path.is_file()
    assert not store.list_cues(project.id)


def test_cancelled_native_error_is_reported_as_cancellation(tmp_path):
    processor, store, project = _controlled_processor(tmp_path, Settings(), None)
    cancelled = threading.Event()

    def load(_settings):
        cancelled.set()
        raise RuntimeError("Native call failed after cancellation")

    processor._recognizer_factory = load
    with pytest.raises(InterruptedError):
        processor.process(project.id, ProcessingOptions(), cancel=cancelled)
    assert store.get_project(project.id).status == "cancelled"


def test_cancel_after_successful_commit_does_not_retract_result(tmp_path):
    processor, store, project = _controlled_processor(tmp_path, Settings(), None, count=1)
    cancelled = threading.Event()

    def progress(value, _message):
        if value == 1.0:
            cancelled.set()

    result = processor.process(
        project.id, ProcessingOptions(), cancel=cancelled, on_progress=progress
    )
    assert result.status == store.get_project(project.id).status == "completed"
    assert len(store.list_cues(project.id)) == 1


def test_provider_cleanup_error_does_not_hide_cancellation(tmp_path):
    cancelled = threading.Event()
    defaults = Settings()
    settings = replace(
        defaults, correction=replace(defaults.correction, provider="local", model="test")
    )

    def revise(_request):
        cancelled.set()
        return SimpleNamespace(text="Late response")

    def close():
        raise RuntimeError("Cleanup error")

    processor, store, project = _controlled_processor(
        tmp_path, settings, SimpleNamespace(revise=revise, close=close)
    )
    with pytest.raises(InterruptedError):
        processor.process(project.id, ProcessingOptions(use_llm=True), cancel=cancelled)
    assert store.get_project(project.id).status == "cancelled"
    assert not store.list_cues(project.id)
