"""Document-level normalization with immutable source text."""

from __future__ import annotations

from bilbo_tts.models import (
    AppliedTransformation,
    BlockKind,
    BookDocument,
    NormalizedBlock,
    NormalizedDocument,
)
from bilbo_tts.normalization.lexicon import LoadedLexicons
from bilbo_tts.normalization.rules import apply_rules
from bilbo_tts.serialization import canonical_sha256


class NormalizationError(ValueError):
    """Source text cannot be normalized without violating a contract."""


def normalize_text(
    text: str,
    lexicons: LoadedLexicons,
    *,
    equation: bool = False,
) -> tuple[str, tuple[AppliedTransformation, ...], tuple[str, ...]]:
    """Normalize one string; primarily exposed for golden rule tests."""

    spoken, transformations, warnings = apply_rules(text, lexicons, equation=equation)
    if not spoken:
        raise NormalizationError("normalization produced empty spoken text")
    return spoken, transformations, warnings


def normalize_document(
    document: BookDocument,
    *,
    normalization_version: str,
    lexicons: LoadedLexicons,
) -> NormalizedDocument:
    """Normalize every source block in canonical document order."""

    blocks: list[NormalizedBlock] = []
    for chapter in document.chapters:
        for block in chapter.blocks:
            equation = block.kind is BlockKind.EQUATION
            spoken, transformations, warnings = apply_rules(
                block.display_text,
                lexicons,
                equation=equation,
            )
            if not spoken:
                raise NormalizationError(
                    f"normalization produced empty spoken text for {block.block_id}"
                )
            source_warnings = tuple(
                warning
                for warning in block.warnings
                if not (equation and warning.startswith("equation-requires-review:"))
            )
            blocks.append(
                NormalizedBlock(
                    block_id=block.block_id,
                    display_text=block.display_text,
                    spoken_text=spoken,
                    transformations=transformations,
                    warnings=source_warnings + warnings,
                )
            )
    return NormalizedDocument(
        book_id=document.book_id,
        book_document_sha256=canonical_sha256(document),
        normalization_version=normalization_version,
        lexicon_sha256=lexicons.sha256,
        blocks=tuple(blocks),
    )
