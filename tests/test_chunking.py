from __future__ import annotations

import pytest

from bilbo_tts.chunking import (
    ChunkingError,
    build_chunk_manifest,
    split_sentences,
    split_to_limit,
)
from bilbo_tts.config import PauseConfig
from bilbo_tts.models import (
    BlockKind,
    BookDocument,
    BreakKind,
    ChapterDocument,
    DocumentBlock,
    NormalizedBlock,
    NormalizedDocument,
    SourceFormat,
    SourceLocation,
)

BOOK_REFERENCE_SHA256 = "c" * 64
NORMALIZED_REFERENCE_SHA256 = "d" * 64


def _documents() -> tuple[BookDocument, NormalizedDocument]:
    chapters = (
        ChapterDocument(
            chapter_id="chapter-1",
            order=0,
            title="Uno",
            blocks=(
                DocumentBlock(
                    block_id="block-1",
                    kind=BlockKind.PARAGRAPH,
                    display_text="Prima frase. Seconda frase molto lunga.",
                    source=SourceLocation(source_path="source/main.tex"),
                ),
                DocumentBlock(
                    block_id="block-2",
                    kind=BlockKind.PARAGRAPH,
                    display_text="Terzo.",
                    source=SourceLocation(source_path="source/main.tex"),
                ),
            ),
        ),
        ChapterDocument(
            chapter_id="chapter-2",
            order=1,
            title="Due",
            blocks=(
                DocumentBlock(
                    block_id="block-3",
                    kind=BlockKind.PARAGRAPH,
                    display_text="Quarto.",
                    source=SourceLocation(source_path="source/main.tex"),
                ),
            ),
        ),
    )
    document = BookDocument(
        book_id="book",
        source_format=SourceFormat.LATEX,
        source_sha256="a" * 64,
        chapters=chapters,
    )
    normalized = NormalizedDocument(
        book_id="book",
        book_document_sha256=BOOK_REFERENCE_SHA256,
        normalization_version="it-v1",
        lexicon_sha256="b" * 64,
        blocks=tuple(
            NormalizedBlock(
                block_id=block.block_id,
                display_text=block.display_text,
                spoken_text=block.display_text,
            )
            for chapter in chapters
            for block in chapter.blocks
        ),
    )
    return document, normalized


def test_sentence_splitting_protects_italian_abbreviations_and_initials() -> None:
    assert split_sentences("Il dott. A. Rossi parla. Poi tace! Fine?") == (
        "Il dott. A. Rossi parla.",
        "Poi tace!",
        "Fine?",
    )


def test_limit_split_honors_exact_boundary_and_rejects_overlong_word() -> None:
    assert split_to_limit("12345", 5) == ("12345",)
    assert split_to_limit("12345 6789", 5) == ("12345", "6789")
    assert split_to_limit("prima, seconda", 7) == ("prima,", "seconda")
    with pytest.raises(ChunkingError, match="cannot split"):
        split_to_limit("lunghissima", 5)


def test_limit_split_prefers_stronger_punctuation_without_adding_chunks() -> None:
    sentence = (
        "Per ora non serve sapere quale prodotto comprare, né calcolare rendimenti "
        "complessi: serve capire perché alcune decisioni molto comuni, come lasciare "
        "tutti i risparmi sul conto corrente o sottoscrivere il primo prodotto proposto "
        "in banca, hanno conseguenze che nel corso di una vita si misurano in decine di "
        "migliaia di euro."
    )

    assert split_to_limit(sentence, 300) == (
        "Per ora non serve sapere quale prodotto comprare, né calcolare rendimenti complessi:",
        "serve capire perché alcune decisioni molto comuni, come lasciare tutti i risparmi "
        "sul conto corrente o sottoscrivere il primo prodotto proposto in banca, hanno "
        "conseguenze che nel corso di una vita si misurano in decine di migliaia di euro.",
    )
    assert split_to_limit(
        "Introduzione: parole parole parole, continuazione breve.",
        40,
    ) == (
        "Introduzione: parole parole parole,",
        "continuazione breve.",
    )


def test_chunk_manifest_preserves_text_order_ids_and_pause_semantics() -> None:
    document, normalized = _documents()

    manifest = build_chunk_manifest(
        document,
        normalized,
        book_document_sha256=BOOK_REFERENCE_SHA256,
        normalized_document_sha256=NORMALIZED_REFERENCE_SHA256,
        max_characters=20,
        pauses=PauseConfig(sentence_ms=250, paragraph_ms=600, chapter_ms=1500),
    )

    assert [chunk.sequence for chunk in manifest.chunks] == list(range(len(manifest.chunks)))
    assert [chunk.chunk_id for chunk in manifest.chunks] == [
        "block-1.s0000.p0000",
        "block-1.s0001.p0000",
        "block-1.s0001.p0001",
        "block-2.s0000.p0000",
        "block-3.s0000.p0000",
    ]
    assert [chunk.pause.break_before for chunk in manifest.chunks] == [
        BreakKind.CHAPTER,
        BreakKind.SENTENCE,
        BreakKind.NONE,
        BreakKind.PARAGRAPH,
        BreakKind.CHAPTER,
    ]
    assert all(len(chunk.spoken_text) <= 20 for chunk in manifest.chunks)
    for block in normalized.blocks:
        reconstructed = " ".join(
            chunk.spoken_text for chunk in manifest.chunks if chunk.paragraph_id == block.block_id
        )
        assert " ".join(reconstructed.split()) == " ".join(block.spoken_text.split())


def test_packing_merges_adjacent_sentences_and_keeps_first_pause() -> None:
    document, normalized = _documents()

    manifest = build_chunk_manifest(
        document,
        normalized,
        book_document_sha256=BOOK_REFERENCE_SHA256,
        normalized_document_sha256=NORMALIZED_REFERENCE_SHA256,
        max_characters=40,
        pauses=PauseConfig(sentence_ms=250, paragraph_ms=600, chapter_ms=1500),
        pack_sentences=True,
    )

    # "Prima frase." (12) + space + "Seconda frase molto lunga." (26) fits in 40.
    assert [chunk.chunk_id for chunk in manifest.chunks] == [
        "block-1.s0000-s0001.p0000",
        "block-2.s0000.p0000",
        "block-3.s0000.p0000",
    ]
    assert manifest.chunks[0].spoken_text == "Prima frase. Seconda frase molto lunga."
    assert manifest.chunks[0].display_text == "Prima frase. Seconda frase molto lunga."
    assert [chunk.pause.break_before for chunk in manifest.chunks] == [
        BreakKind.CHAPTER,
        BreakKind.PARAGRAPH,
        BreakKind.CHAPTER,
    ]
    assert all(len(chunk.spoken_text) <= 40 for chunk in manifest.chunks)
    for block in normalized.blocks:
        reconstructed = " ".join(
            chunk.spoken_text for chunk in manifest.chunks if chunk.paragraph_id == block.block_id
        )
        assert " ".join(reconstructed.split()) == " ".join(block.spoken_text.split())


def test_packing_respects_limit_and_still_splits_overlong_sentences() -> None:
    document, normalized = _documents()

    manifest = build_chunk_manifest(
        document,
        normalized,
        book_document_sha256=BOOK_REFERENCE_SHA256,
        normalized_document_sha256=NORMALIZED_REFERENCE_SHA256,
        max_characters=20,
        pauses=PauseConfig(sentence_ms=250, paragraph_ms=600, chapter_ms=1500),
        pack_sentences=True,
    )

    # Nothing fits together at 20 characters, and the second sentence still
    # splits into continuation parts exactly like the unpacked layout.
    assert [chunk.chunk_id for chunk in manifest.chunks] == [
        "block-1.s0000.p0000",
        "block-1.s0001.p0000",
        "block-1.s0001.p0001",
        "block-2.s0000.p0000",
        "block-3.s0000.p0000",
    ]
    assert [chunk.pause.break_before for chunk in manifest.chunks] == [
        BreakKind.CHAPTER,
        BreakKind.SENTENCE,
        BreakKind.NONE,
        BreakKind.PARAGRAPH,
        BreakKind.CHAPTER,
    ]


def test_packing_disabled_is_the_default_and_unchanged() -> None:
    document, normalized = _documents()
    pauses = PauseConfig(sentence_ms=250, paragraph_ms=600, chapter_ms=1500)

    default = build_chunk_manifest(
        document,
        normalized,
        book_document_sha256=BOOK_REFERENCE_SHA256,
        normalized_document_sha256=NORMALIZED_REFERENCE_SHA256,
        max_characters=40,
        pauses=pauses,
    )
    explicit = build_chunk_manifest(
        document,
        normalized,
        book_document_sha256=BOOK_REFERENCE_SHA256,
        normalized_document_sha256=NORMALIZED_REFERENCE_SHA256,
        max_characters=40,
        pauses=pauses,
        pack_sentences=False,
    )

    assert default == explicit
    assert [chunk.chunk_id for chunk in default.chunks] == [
        "block-1.s0000.p0000",
        "block-1.s0001.p0000",
        "block-2.s0000.p0000",
        "block-3.s0000.p0000",
    ]


def test_chunking_rejects_stale_or_mismatched_normalized_documents() -> None:
    document, normalized = _documents()
    stale = normalized.model_copy(update={"book_document_sha256": "e" * 64})
    missing = normalized.model_copy(update={"blocks": normalized.blocks[:-1]})

    with pytest.raises(ChunkingError, match="current canonical"):
        build_chunk_manifest(
            document,
            stale,
            book_document_sha256=BOOK_REFERENCE_SHA256,
            normalized_document_sha256=NORMALIZED_REFERENCE_SHA256,
            max_characters=100,
            pauses=PauseConfig(),
        )
    with pytest.raises(ChunkingError, match="block IDs"):
        build_chunk_manifest(
            document,
            missing,
            book_document_sha256=BOOK_REFERENCE_SHA256,
            normalized_document_sha256=NORMALIZED_REFERENCE_SHA256,
            max_characters=100,
            pauses=PauseConfig(),
        )
