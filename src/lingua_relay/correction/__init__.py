from lingua_relay.correction.batch import BatchRevisionReport, revise_history
from lingua_relay.correction.engine import AsynchronousRevisionEngine
from lingua_relay.correction.glossary import glossary_for_route, load_glossary
from lingua_relay.correction.provider import CorrectionProviderError, OpenAICompatibleProvider
from lingua_relay.correction.types import (
    CorrectionProvider,
    CorrectionRequest,
    CorrectionSnapshot,
    GlossaryEntry,
    RevisionResult,
)

__all__ = [
    "AsynchronousRevisionEngine",
    "BatchRevisionReport",
    "CorrectionProvider",
    "CorrectionProviderError",
    "CorrectionRequest",
    "CorrectionSnapshot",
    "GlossaryEntry",
    "OpenAICompatibleProvider",
    "RevisionResult",
    "glossary_for_route",
    "load_glossary",
    "revise_history",
]
