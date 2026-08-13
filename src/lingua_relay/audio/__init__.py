"""Windows loopback capture and audio preprocessing."""

from lingua_relay.audio.capture import (
    ProcessLoopbackCapture,
    WasapiLoopbackCapture,
    WasapiMicrophoneCapture,
    create_audio_capture,
)
from lingua_relay.audio.devices import WasapiDeviceManager
from lingua_relay.audio.processes import AudioProcessManager
from lingua_relay.audio.types import (
    AudioChunk,
    AudioDevice,
    AudioLevel,
    AudioProcess,
    AudioSourceType,
    CaptureSnapshot,
)

__all__ = [
    "AudioChunk",
    "AudioDevice",
    "AudioLevel",
    "AudioProcess",
    "AudioProcessManager",
    "AudioSourceType",
    "CaptureSnapshot",
    "ProcessLoopbackCapture",
    "WasapiDeviceManager",
    "WasapiLoopbackCapture",
    "WasapiMicrophoneCapture",
    "create_audio_capture",
]
