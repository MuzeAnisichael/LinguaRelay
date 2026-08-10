import pytest

from lingua_relay.audio.capture import WasapiLoopbackCapture, _RestartCapture
from lingua_relay.audio.types import AudioDevice
from lingua_relay.config import AudioSettings


class ChangingDeviceManager:
    def __init__(self, current: AudioDevice) -> None:
        self.current = current

    def resolve(self, _selector: str) -> AudioDevice:
        return self.current


def make_device(index: int, name: str = "Speakers") -> AudioDevice:
    return AudioDevice(
        device_id=f"wasapi:{name}",
        index=index,
        name=f"{name} [Loopback]",
        sample_rate=48_000,
        channels=2,
        is_default=True,
    )


def test_device_identity_change_requests_stream_restart() -> None:
    original = make_device(1)
    manager = ChangingDeviceManager(make_device(2))
    capture = WasapiLoopbackCapture(AudioSettings(), device_manager=manager)  # type: ignore[arg-type]

    with pytest.raises(_RestartCapture, match="audio device changed"):
        capture._verify_device(original)


def test_unchanged_device_keeps_stream() -> None:
    original = make_device(1)
    manager = ChangingDeviceManager(original)
    capture = WasapiLoopbackCapture(AudioSettings(), device_manager=manager)  # type: ignore[arg-type]

    capture._verify_device(original)


class FailsOnceCapture(WasapiLoopbackCapture):
    def __init__(self) -> None:
        super().__init__(
            AudioSettings(
                reconnect_initial_seconds=0.001,
                reconnect_max_seconds=0.002,
            )
        )
        self.attempts = 0

    def _run_session(self) -> None:
        self.attempts += 1
        if self.attempts == 1:
            raise OSError("device disconnected")
        self._stop.set()


def test_supervisor_retries_after_capture_failure() -> None:
    capture = FailsOnceCapture()

    capture._supervise()

    snapshot = capture.snapshot()
    assert capture.attempts == 2
    assert snapshot.reconnects == 1
    assert snapshot.last_error == "OSError: device disconnected"
