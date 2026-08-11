"""Fast, explicit-language machine translation for M3."""

from lingua_relay.mt.m2m100 import M2M100Translator, prepare_m2m100_model
from lingua_relay.mt.streaming import StreamingTranslationEngine
from lingua_relay.mt.types import TranslationResult, TranslationSnapshot

__all__ = [
    "M2M100Translator",
    "StreamingTranslationEngine",
    "TranslationResult",
    "TranslationSnapshot",
    "prepare_m2m100_model",
]
