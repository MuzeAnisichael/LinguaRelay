from pathlib import Path

import pytest

from lingua_relay.config import Settings


def test_loads_complete_local_correction_settings() -> None:
    settings = Settings.from_mapping(
        {
            "correction": {
                "mode": "asynchronous",
                "provider": "local",
                "endpoint": "http://[::1]:8080/v1",
                "model": "local-model",
                "glossary_path": "terms.json",
            }
        }
    )

    settings.validate()
    assert settings.correction.glossary_path == Path("terms.json")


@pytest.mark.parametrize(
    ("provider", "endpoint", "message"),
    (
        ("local", "http://192.168.1.8:8080/v1", "loopback"),
        ("local", "https://models.example/v1", "loopback"),
        ("openai_compatible", "http://api.example/v1", "HTTPS"),
        ("local", "http://127.0.0.1:99999/v1", "port"),
    ),
)
def test_rejects_unsafe_correction_endpoints(provider: str, endpoint: str, message: str) -> None:
    settings = Settings.from_mapping(
        {
            "correction": {
                "provider": provider,
                "endpoint": endpoint,
                "model": "model",
            }
        }
    )

    with pytest.raises(ValueError, match=message):
        settings.validate()


def test_enabled_mode_requires_provider() -> None:
    settings = Settings.from_mapping({"correction": {"mode": "live"}})

    with pytest.raises(ValueError, match="requires"):
        settings.validate()


def test_cloud_endpoint_cannot_embed_credentials() -> None:
    settings = Settings.from_mapping(
        {
            "correction": {
                "provider": "openai_compatible",
                "endpoint": "https://secret@example.test/v1",
                "model": "model",
            }
        }
    )

    with pytest.raises(ValueError, match="credentials"):
        settings.validate()
