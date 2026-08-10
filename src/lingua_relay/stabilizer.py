from __future__ import annotations

from dataclasses import dataclass, field

from lingua_relay.languages import normalize_language


@dataclass(slots=True)
class StablePrefix:
    """Find words shared by consecutive ASR hypotheses.

    Chinese and Japanese use character-level stability; English and Korean use
    whitespace-delimited words. A model tokenizer can replace this in M2.
    """

    language: str = "en"
    _previous: tuple[str, ...] = field(default_factory=tuple)
    _committed_count: int = 0

    def update(self, hypothesis: str) -> str:
        current = self._tokenize(hypothesis)
        shared_count = 0
        for old, new in zip(self._previous, current, strict=False):
            if old != new:
                break
            shared_count += 1

        newly_stable = current[self._committed_count : shared_count]
        self._committed_count = max(self._committed_count, shared_count)
        self._previous = current
        return self._join(newly_stable)

    def finalize(self, hypothesis: str) -> str:
        current = self._tokenize(hypothesis)
        remainder = current[self._committed_count :]
        self.reset()
        return self._join(remainder)

    def reset(self) -> None:
        self._previous = ()
        self._committed_count = 0

    def _tokenize(self, text: str) -> tuple[str, ...]:
        stripped = text.strip()
        if normalize_language(self.language) in {"zh", "ja"}:
            return tuple(stripped)
        return tuple(stripped.split())

    def _join(self, tokens: tuple[str, ...]) -> str:
        if normalize_language(self.language) in {"zh", "ja"}:
            return "".join(tokens)
        return " ".join(tokens)
