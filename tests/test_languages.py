import pytest

from lingua_relay.config import Settings
from lingua_relay.languages import SUPPORTED_LANGUAGES, normalize_language, translation_routes


def test_supports_twelve_routes_across_four_languages() -> None:
    assert set(SUPPORTED_LANGUAGES) == {"zh", "ja", "en", "ko"}
    assert len(translation_routes()) == 12
    assert all(source != target for source, target in translation_routes())


@pytest.mark.parametrize(
    ("alias", "expected"),
    [("zh-CN", "zh"), ("zh_Hans", "zh"), ("jp", "ja"), ("kr", "ko")],
)
def test_normalizes_language_aliases(alias: str, expected: str) -> None:
    assert normalize_language(alias) == expected


def test_rejects_language_outside_supported_set() -> None:
    settings = Settings.from_mapping({"app": {"source_language": "fr", "target_language": "en"}})

    with pytest.raises(ValueError, match="unsupported source_language"):
        settings.validate()
