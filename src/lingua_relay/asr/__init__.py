"""Streaming multilingual speech recognition for M2."""

from lingua_relay.asr.faster_whisper import (
    FasterWhisperRecognizer,
    prepare_cuda_dlls,
    resolve_runtime,
)
from lingua_relay.asr.streaming import StreamingAsrEngine, StreamingSegmenter
from lingua_relay.asr.types import (
    AsrEvent,
    AsrResult,
    AsrRuntime,
    AsrSnapshot,
    InferenceRequest,
)

__all__ = [
    "AsrEvent",
    "AsrResult",
    "AsrRuntime",
    "AsrSnapshot",
    "FasterWhisperRecognizer",
    "InferenceRequest",
    "StreamingAsrEngine",
    "StreamingSegmenter",
    "prepare_cuda_dlls",
    "resolve_runtime",
]
