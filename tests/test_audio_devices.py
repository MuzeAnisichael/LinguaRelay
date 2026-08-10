from lingua_relay.audio.devices import WasapiDeviceManager


class FakePyAudio:
    infos = [
        {
            "index": 7,
            "name": "Speakers [Loopback]",
            "defaultSampleRate": 48_000.0,
            "maxInputChannels": 2,
            "maxOutputChannels": 0,
        },
        {
            "index": 8,
            "name": "Headphones [Loopback]",
            "defaultSampleRate": 44_100.0,
            "maxInputChannels": 2,
            "maxOutputChannels": 0,
        },
        {
            "index": 2,
            "name": "Speakers",
            "defaultSampleRate": 48_000.0,
            "maxInputChannels": 0,
            "maxOutputChannels": 2,
        },
        {
            "index": 3,
            "name": "Headphones",
            "defaultSampleRate": 44_100.0,
            "maxInputChannels": 0,
            "maxOutputChannels": 2,
        },
    ]

    def __enter__(self) -> "FakePyAudio":
        return self

    def __exit__(self, *_: object) -> None:
        pass

    def get_default_wasapi_loopback(self) -> dict[str, object]:
        return self.infos[1]

    def get_loopback_device_info_generator(self):  # noqa: ANN201
        yield from self.infos[:2]

    def get_device_info_generator(self):  # noqa: ANN201
        yield from self.infos


class FakeBackend:
    PyAudio = FakePyAudio


class FakeManager(WasapiDeviceManager):
    def _backend(self) -> FakeBackend:
        return FakeBackend()


def test_lists_default_loopback_and_stable_name_selector() -> None:
    manager = FakeManager()

    devices = manager.list_devices()

    assert [device.device_id for device in devices] == [
        "wasapi:Speakers",
        "wasapi:Headphones",
    ]
    assert devices[1].is_default
    assert devices[0].output_index == 2
    assert devices[1].output_index == 3
    assert manager.resolve("wasapi:Speakers").index == 7
    assert manager.resolve("index:8").device_id == "wasapi:Headphones"
