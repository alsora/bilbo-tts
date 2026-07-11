"""Deterministic Italian spoken-text normalization."""

from bilbo_tts.normalization.engine import NormalizationError, normalize_document, normalize_text
from bilbo_tts.normalization.lexicon import (
    LexiconError,
    LoadedLexicons,
    load_lexicons,
)
from bilbo_tts.normalization.service import NormalizeSummary, normalize_book

__all__ = [
    "LexiconError",
    "LoadedLexicons",
    "NormalizationError",
    "NormalizeSummary",
    "load_lexicons",
    "normalize_book",
    "normalize_document",
    "normalize_text",
]
