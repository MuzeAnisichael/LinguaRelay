from __future__ import annotations

from dataclasses import dataclass, field

from lingua_relay.languages import normalize_language


@dataclass(frozen=True, slots=True)
class StabilizedText:
    text: str
    stable_text: str
    unstable_text: str
    newly_stable_text: str


@dataclass(slots=True)
class StablePrefix:
    """Find words shared by consecutive ASR hypotheses.

    Chinese and Japanese use character-level stability; English and Korean use
    whitespace-delimited words. A model tokenizer can replace this in M2.
    """

    language: str = "en"
    _previous: tuple[str, ...] = field(default_factory=tuple)
    _committed: tuple[str, ...] = field(default_factory=tuple)

    def update(self, hypothesis: str) -> str:
        return self.update_state(hypothesis).newly_stable_text

    def update_state(self, hypothesis: str) -> StabilizedText:
        current = self._tokenize(hypothesis)
        committed_count = len(self._committed)
        if current[:committed_count] != self._committed:
            self._previous = current
            stable_text = self._join(self._committed)
            return StabilizedText(
                text=stable_text,
                stable_text=stable_text,
                unstable_text="",
                newly_stable_text="",
            )

        shared_count = 0
        for old, new in zip(self._previous, current, strict=False):
            if old != new:
                break
            shared_count += 1

        stable_count = max(committed_count, shared_count)
        newly_stable = current[committed_count:stable_count]
        self._committed = current[:stable_count]
        self._previous = current
        return StabilizedText(
            text=self._join(current),
            stable_text=self._join(self._committed),
            unstable_text=self._join(current[stable_count:]),
            newly_stable_text=self._join(newly_stable),
        )

    def finalize(self, hypothesis: str) -> str:
        current = self._tokenize(hypothesis)
        remainder = (
            current[len(self._committed) :]
            if current[: len(self._committed)] == self._committed
            else current
        )
        self.reset()
        return self._join(remainder)

    def finalize_state(self, hypothesis: str) -> StabilizedText:
        current = self._tokenize(hypothesis)
        newly_stable = (
            current[len(self._committed) :]
            if current[: len(self._committed)] == self._committed
            else current
        )
        text = self._join(current)
        result = StabilizedText(
            text=text,
            stable_text=text,
            unstable_text="",
            newly_stable_text=self._join(newly_stable),
        )
        self.reset()
        return result

    def reset(self) -> None:
        self._previous = ()
        self._committed = ()

    def _tokenize(self, text: str) -> tuple[str, ...]:
        stripped = text.strip()
        if normalize_language(self.language) in {"zh", "ja"}:
            return tuple(stripped)
        return tuple(stripped.split())

    def _join(self, tokens: tuple[str, ...]) -> str:
        if normalize_language(self.language) in {"zh", "ja"}:
            return "".join(tokens)
        return " ".join(tokens)
