from __future__ import annotations

import re
import unicodedata

from lingua_relay.languages import normalize_language


def error_rate(reference: str, hypothesis: str, language: str) -> tuple[int, int, float, str]:
    normalized = normalize_language(language)
    unit = "cer" if normalized in {"zh", "ja"} else "wer"
    reference_units = _units(reference, unit)
    hypothesis_units = _units(hypothesis, unit)
    errors = edit_distance(reference_units, hypothesis_units)
    denominator = max(1, len(reference_units))
    return errors, len(reference_units), errors / denominator, unit


def edit_distance(reference: tuple[str, ...], hypothesis: tuple[str, ...]) -> int:
    previous = list(range(len(hypothesis) + 1))
    for reference_index, reference_item in enumerate(reference, start=1):
        current = [reference_index]
        for hypothesis_index, hypothesis_item in enumerate(hypothesis, start=1):
            substitution = previous[hypothesis_index - 1] + (reference_item != hypothesis_item)
            current.append(
                min(
                    previous[hypothesis_index] + 1,
                    current[hypothesis_index - 1] + 1,
                    substitution,
                )
            )
        previous = current
    return previous[-1]


def normalize_text(text: str) -> str:
    normalized = unicodedata.normalize("NFKC", text).casefold()
    normalized = "".join(
        " " if unicodedata.category(character).startswith(("P", "S")) else character
        for character in normalized
    )
    return re.sub(r"\s+", " ", normalized).strip()


def _units(text: str, unit: str) -> tuple[str, ...]:
    normalized = normalize_text(text)
    if unit == "cer":
        return tuple(normalized.replace(" ", ""))
    return tuple(normalized.split())
