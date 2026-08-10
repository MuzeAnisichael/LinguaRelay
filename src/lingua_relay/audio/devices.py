from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from lingua_relay.audio.types import AudioDevice, device_id_from_name


class AudioBackendUnavailableError(RuntimeError):
    pass


class AudioDeviceNotFoundError(RuntimeError):
    pass


class WasapiDeviceManager:
    def _backend(self) -> Any:
        try:
            import pyaudiowpatch as pyaudio
        except ImportError as error:
            raise AudioBackendUnavailableError(
                "PyAudioWPatch is required; install the 'runtime' extra"
            ) from error
        return pyaudio

    def list_devices(self) -> tuple[AudioDevice, ...]:
        pyaudio = self._backend()
        with pyaudio.PyAudio() as audio:
            try:
                default_info = audio.get_default_wasapi_loopback()
                default_id = device_id_from_name(str(default_info["name"]))
                infos: Iterable[dict[str, Any]] = audio.get_loopback_device_info_generator()
                return tuple(self._from_info(audio, info, default_id) for info in infos)
            except OSError as error:
                raise AudioBackendUnavailableError("WASAPI loopback is unavailable") from error

    def default_device(self) -> AudioDevice:
        pyaudio = self._backend()
        with pyaudio.PyAudio() as audio:
            try:
                info = audio.get_default_wasapi_loopback()
            except OSError as error:
                raise AudioDeviceNotFoundError(
                    "default WASAPI loopback device not found"
                ) from error
            return self._from_info(audio, info, device_id_from_name(str(info["name"])))

    def resolve(self, selector: str) -> AudioDevice:
        if selector.strip().casefold() == "default":
            return self.default_device()
        wanted = selector.strip().casefold()
        devices = self.list_devices()
        for device in devices:
            selectors = {
                device.device_id.casefold(),
                device.name.casefold(),
                f"index:{device.index}",
            }
            if wanted in selectors:
                return device
        available = ", ".join(device.device_id for device in devices) or "none"
        raise AudioDeviceNotFoundError(
            f"WASAPI loopback device '{selector}' not found; available: {available}"
        )

    @classmethod
    def _from_info(cls, audio: Any, info: dict[str, Any], default_id: str) -> AudioDevice:
        name = str(info["name"])
        device_id = device_id_from_name(name)
        return AudioDevice(
            device_id=device_id,
            index=int(info["index"]),
            name=name,
            sample_rate=int(round(float(info["defaultSampleRate"]))),
            channels=max(1, int(info["maxInputChannels"])),
            output_index=cls._find_output_index(audio, name),
            is_default=device_id == default_id,
        )

    @staticmethod
    def _find_output_index(audio: Any, loopback_name: str) -> int | None:
        wanted_id = device_id_from_name(loopback_name).casefold()
        for candidate in audio.get_device_info_generator():
            if int(candidate.get("maxOutputChannels", 0)) <= 0:
                continue
            if device_id_from_name(str(candidate["name"])).casefold() == wanted_id:
                return int(candidate["index"])
        return None
