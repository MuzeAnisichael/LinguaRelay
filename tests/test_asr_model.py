from types import SimpleNamespace

import numpy as np
import pytest

from lingua_relay.asr.faster_whisper import FasterWhisperRecognizer
from lingua_relay.config import AsrSettings


class FakeModel:
    def __init__(self, model: str, **kwargs: object) -> None:
        self.model = model
        self.init_kwargs = kwargs
        self.calls: list[dict[str, object]] = []

    def transcribe(self, samples: np.ndarray, **kwargs: object):
        self.calls.append(kwargs)
        segments = iter(
            [
                SimpleNamespace(
                    start=0.0,
                    end=len(samples) / 16_000,
                    text=" テスト ",
                    avg_logprob=-0.1,
                    no_speech_prob=0.01,
                )
            ]
        )
        return segments, SimpleNamespace(duration=len(samples) / 16_000)


def test_recognizer_passes_explicit_language_and_silero_vad() -> None:
    created: list[FakeModel] = []

    def factory(model: str, **kwargs: object) -> FakeModel:
        instance = FakeModel(model, **kwargs)
        created.append(instance)
        return instance

    recognizer = FasterWhisperRecognizer(
        AsrSettings(model="tiny", device="cpu", compute_type="int8"),
        model_factory=factory,
    )
    result = recognizer.transcribe(np.zeros(16_000, dtype=np.float32), language="jp")

    assert result.text == "テスト"
    assert result.language == "ja"
    assert created[0].calls[0]["language"] == "ja"
    assert created[0].calls[0]["task"] == "transcribe"
    assert created[0].calls[0]["vad_filter"] is True
    assert created[0].calls[0]["condition_on_previous_text"] is False

    recognizer.transcribe(np.zeros(16_000, dtype=np.float32), language="ja", vad_filter=False)
    assert created[0].calls[1]["vad_filter"] is False


def test_recognizer_rejects_unsupported_or_missing_language() -> None:
    recognizer = FasterWhisperRecognizer(
        AsrSettings(model="tiny", device="cpu", compute_type="int8"),
        model_factory=FakeModel,
    )

    with pytest.raises(ValueError, match="unsupported ASR language"):
        recognizer.transcribe(np.zeros(10, dtype=np.float32), language="auto")


def test_recognizer_rejects_english_only_model() -> None:
    with pytest.raises(ValueError, match="multilingual"):
        FasterWhisperRecognizer(
            AsrSettings(model="tiny.en", device="cpu", compute_type="int8"),
            model_factory=FakeModel,
        )


class TraditionalChineseModel(FakeModel):
    def transcribe(self, samples: np.ndarray, **kwargs: object):
        self.calls.append(kwargs)
        segments = iter(
            [
                SimpleNamespace(
                    start=0.0,
                    end=len(samples) / 16_000,
                    text=" 這是測試 ",
                    avg_logprob=-0.1,
                    no_speech_prob=0.01,
                )
            ]
        )
        return segments, SimpleNamespace(duration=len(samples) / 16_000)


def test_chinese_result_and_segments_are_normalized_to_simplified() -> None:
    recognizer = FasterWhisperRecognizer(
        AsrSettings(model="tiny", device="cpu", compute_type="int8"),
        model_factory=TraditionalChineseModel,
    )

    result = recognizer.transcribe(np.zeros(16_000, dtype=np.float32), language="zh")

    assert result.text == "这是测试"
    assert result.segments[0].text.strip() == "这是测试"
