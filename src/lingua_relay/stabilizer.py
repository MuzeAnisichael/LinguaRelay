from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class StablePrefix:
    """Find words shared by consecutive ASR hypotheses.

    The MVP source language is English, so whitespace tokenization is an
    intentional first step. Language-specific tokenizers can replace it later.
    """

    _previous: tuple[str, ...] = field(default_factory=tuple)
    _committed_count: int = 0

    def update(self, hypothesis: str) -> str:
        current = tuple(hypothesis.strip().split())
        shared_count = 0
        for old, new in zip(self._previous, current, strict=False):
            if old != new:
                break
            shared_count += 1

        newly_stable = current[self._committed_count : shared_count]
        self._committed_count = max(self._committed_count, shared_count)
        self._previous = current
        return " ".join(newly_stable)

    def finalize(self, hypothesis: str) -> str:
        current = tuple(hypothesis.strip().split())
        remainder = current[self._committed_count :]
        self.reset()
        return " ".join(remainder)

    def reset(self) -> None:
        self._previous = ()
        self._committed_count = 0
