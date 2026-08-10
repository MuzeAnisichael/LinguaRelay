import pytest

from lingua_relay.languages import translation_routes
from lingua_relay.translation import (
    TranslationRouteNotFoundError,
    TranslationRouteRegistry,
)


class IdentityTranslator:
    def translate(self, text: str, *, source: str, target: str) -> str:
        return f"{source}->{target}:{text}"


def test_registry_can_cover_all_twelve_ordered_routes() -> None:
    registry = TranslationRouteRegistry()
    translator = IdentityTranslator()
    for source, target in translation_routes():
        registry.register(source, target, "test", translator)

    assert registry.missing_required_routes() == ()
    assert len(registry.routes) == 12
    route = registry.resolve("zh-CN", "jp")
    assert route.source == "zh"
    assert route.target == "ja"


def test_missing_route_fails_explicitly() -> None:
    registry = TranslationRouteRegistry()

    with pytest.raises(TranslationRouteNotFoundError, match="en->ko"):
        registry.resolve("en", "ko")


def test_same_language_route_is_rejected() -> None:
    registry = TranslationRouteRegistry()

    with pytest.raises(ValueError, match="must be different"):
        registry.register("ja", "ja", "test", IdentityTranslator())
