from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from lingua_relay.audio.types import (
    AudioDevice,
    AudioSourceType,
    device_id_from_name,
    microphone_id_from_name,
)


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

    def list_microphones(self) -> tuple[AudioDevice, ...]:
        pyaudio = self._backend()
        with pyaudio.PyAudio() as audio:
            infos = tuple(audio.get_device_info_generator())
            default_index = self._default_input_index(audio)
            wasapi_index = self._wasapi_host_index(audio)
            devices = []
            for info in infos:
                if int(info.get("maxInputChannels", 0)) <= 0:
                    continue
                if str(info.get("name", "")).endswith(" [Loopback]"):
                    continue
                if (
                    wasapi_index is not None
                    and int(info.get("hostApi", wasapi_index)) != wasapi_index
                ):
                    continue
                name = str(info["name"])
                index = int(info["index"])
                devices.append(
                    AudioDevice(
                        device_id=microphone_id_from_name(name),
                        index=index,
                        name=name,
                        sample_rate=int(round(float(info["defaultSampleRate"]))),
                        channels=max(1, int(info["maxInputChannels"])),
                        is_default=index == default_index,
                        source_type=AudioSourceType.MICROPHONE,
                    )
                )
            return tuple(devices)

    def default_microphone(self) -> AudioDevice:
        devices = self.list_microphones()
        default = next((device for device in devices if device.is_default), None)
        if default is not None:
            return default
        if devices:
            return devices[0]
        raise AudioDeviceNotFoundError("default WASAPI microphone not found")

    def resolve_microphone(self, selector: str) -> AudioDevice:
        if selector.strip().casefold() == "default":
            return self.default_microphone()
        wanted = selector.strip().casefold()
        devices = self.list_microphones()
        for device in devices:
            if wanted in {
                device.device_id.casefold(),
                device.name.casefold(),
                f"index:{device.index}",
            }:
                return device
        available = ", ".join(device.device_id for device in devices) or "none"
        raise AudioDeviceNotFoundError(
            f"WASAPI microphone '{selector}' not found; available: {available}"
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
            source_type=AudioSourceType.SYSTEM,
        )

    @staticmethod
    def _wasapi_host_index(audio: Any) -> int | None:
        try:
            import pyaudiowpatch as pyaudio

            return int(audio.get_host_api_info_by_type(pyaudio.paWASAPI)["index"])
        except (AttributeError, ImportError, KeyError, OSError, TypeError, ValueError):
            return None

    @staticmethod
    def _default_input_index(audio: Any) -> int | None:
        try:
            return int(audio.get_default_input_device_info()["index"])
        except (AttributeError, KeyError, OSError, TypeError, ValueError):
            return None

    @staticmethod
    def _find_output_index(audio: Any, loopback_name: str) -> int | None:
        wanted_id = device_id_from_name(loopback_name).casefold()
        for candidate in audio.get_device_info_generator():
            if int(candidate.get("maxOutputChannels", 0)) <= 0:
                continue
            if device_id_from_name(str(candidate["name"])).casefold() == wanted_id:
                return int(candidate["index"])
        return None
