from __future__ import annotations

import wave
from dataclasses import replace
from types import SimpleNamespace

from lingua_relay.asr.types import AsrResult, AsrSegment, AsrWord
from lingua_relay.config import Settings
from lingua_relay.offline.processor import OfflineProcessor, ProcessingOptions
from lingua_relay.offline.project import OfflineProjectStore


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
