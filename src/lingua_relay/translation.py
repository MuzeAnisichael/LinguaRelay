from __future__ import annotations

from dataclasses import dataclass

from lingua_relay.languages import SUPPORTED_LANGUAGES, normalize_language, translation_routes
from lingua_relay.ports import Translator


class TranslationRouteNotFoundError(LookupError):
    pass


@dataclass(frozen=True, slots=True)
class TranslationRoute:
    source: str
    target: str
    provider_name: str
    translator: Translator


class TranslationRouteRegistry:
    """Resolve a translation provider by an explicit ordered language pair."""

    def __init__(self) -> None:
        self._routes: dict[tuple[str, str], TranslationRoute] = {}

    def register(
        self,
        source: str,
        target: str,
        provider_name: str,
        translator: Translator,
    ) -> None:
        source_code = normalize_language(source)
        target_code = normalize_language(target)
        self._validate_pair(source_code, target_code)
        if not provider_name.strip():
            raise ValueError("provider_name must not be empty")
        self._routes[(source_code, target_code)] = TranslationRoute(
            source=source_code,
            target=target_code,
            provider_name=provider_name,
            translator=translator,
        )

    def resolve(self, source: str, target: str) -> TranslationRoute:
        pair = (normalize_language(source), normalize_language(target))
        self._validate_pair(*pair)
        try:
            return self._routes[pair]
        except KeyError as error:
            message = f"translation route {pair[0]}->{pair[1]} is not configured"
            raise TranslationRouteNotFoundError(message) from error

    def missing_required_routes(self) -> tuple[tuple[str, str], ...]:
        return tuple(route for route in translation_routes() if route not in self._routes)

    @property
    def routes(self) -> tuple[TranslationRoute, ...]:
        return tuple(self._routes.values())

    @staticmethod
    def _validate_pair(source: str, target: str) -> None:
        if source not in SUPPORTED_LANGUAGES or target not in SUPPORTED_LANGUAGES:
            raise ValueError(f"unsupported translation route: {source}->{target}")
        if source == target:
            raise ValueError("translation source and target must be different")
