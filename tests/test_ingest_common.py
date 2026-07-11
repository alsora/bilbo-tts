from __future__ import annotations

import pytest

from bilbo_tts.ingest.common import IngestionError, assemble_document, map_pandoc_ast
from bilbo_tts.models import BlockKind, SourceFormat, SourceLocation

HASH = "a" * 64
SOURCE = SourceLocation(source_path="source/book.tex")


def _inlines(text: str) -> list[dict[str, object]]:
    nodes: list[dict[str, object]] = []
    for index, word in enumerate(text.split()):
        if index:
            nodes.append({"t": "Space"})
        nodes.append({"t": "Str", "c": word})
    return nodes


def test_pandoc_ast_maps_supported_structures_and_explicit_omissions() -> None:
    ast = {
        "blocks": [
            {"t": "Header", "c": [1, ["uno", [], []], _inlines("Capitolo uno")]},
            {
                "t": "Para",
                "c": [
                    *_inlines("Testo con nota"),
                    {"t": "Note", "c": [{"t": "Para", "c": _inlines("Nota parlata")}]},
                    {"t": "Str", "c": "."},
                ],
            },
            {"t": "BulletList", "c": [[{"t": "Para", "c": _inlines("Voce elenco")}]]},
            {"t": "BlockQuote", "c": [{"t": "Para", "c": _inlines("Una citazione")}]},
            {
                "t": "Table",
                "c": [{"t": "Para", "c": _inlines("Anno rendimento cinque")}],
            },
            {
                "t": "Para",
                "c": [{"t": "Math", "c": [{"t": "DisplayMath"}, "x^2"]}],
            },
            {"t": "Figure", "c": [{"t": "Para", "c": _inlines("Una didascalia")}]},
            {"t": "RawBlock", "c": ["latex", "\\unknown"]},
        ]
    }

    mapped = map_pandoc_ast(ast, SOURCE)

    assert [block.kind for block in mapped.blocks] == [
        BlockKind.HEADING,
        BlockKind.PARAGRAPH,
        BlockKind.FOOTNOTE,
        BlockKind.LIST_ITEM,
        BlockKind.QUOTATION,
        BlockKind.TABLE,
        BlockKind.EQUATION,
        BlockKind.CAPTION,
    ]
    assert mapped.blocks[1].text == "Testo con nota."
    assert mapped.blocks[5].warnings == ("table-linearized: verify row and column reading order",)
    assert mapped.exclusions[0].reason_code == "unsupported-pandoc-block"


def test_document_assembly_preserves_front_matter_chapters_and_excludes_references() -> None:
    mapped = map_pandoc_ast(
        {
            "blocks": [
                {"t": "Para", "c": _inlines("Testo iniziale")},
                {"t": "Header", "c": [1, ["uno", [], []], _inlines("Capitolo uno")]},
                {"t": "Para", "c": _inlines("Primo testo")},
                {"t": "Header", "c": [1, ["refs", [], []], _inlines("Bibliografia")]},
                {"t": "Para", "c": _inlines("Fonte esclusa")},
                {"t": "Header", "c": [1, ["due", [], []], _inlines("Capitolo due")]},
                {"t": "Para", "c": _inlines("Secondo testo")},
            ]
        },
        SOURCE,
    )

    document = assemble_document(
        book_id="test-book",
        source_format=SourceFormat.LATEX,
        source_sha256=HASH,
        fallback_title="Titolo",
        contents=(mapped,),
    )

    assert [chapter.title for chapter in document.chapters] == [
        "Front matter",
        "Capitolo uno",
        "Capitolo due",
    ]
    assert [chapter.order for chapter in document.chapters] == [0, 1, 2]
    assert [block.block_id for chapter in document.chapters for block in chapter.blocks] == [
        "block-000001",
        "block-000002",
        "block-000003",
        "block-000004",
        "block-000005",
    ]
    assert document.exclusions[-1].reason_code == "reference-section"
    assert all(
        block.display_text != "Fonte esclusa"
        for chapter in document.chapters
        for block in chapter.blocks
    )


def test_document_without_chapter_heading_uses_configured_title() -> None:
    mapped = map_pandoc_ast({"blocks": [{"t": "Para", "c": _inlines("Solo testo")}]}, SOURCE)

    document = assemble_document(
        book_id="test-book",
        source_format=SourceFormat.LATEX,
        source_sha256=HASH,
        fallback_title="Titolo configurato",
        contents=(mapped,),
    )

    assert document.chapters[0].title == "Titolo configurato"


@pytest.mark.parametrize(
    "ast, message",
    [
        ({}, "blocks list"),
        ({"blocks": ["bad"]}, "tagged objects"),
        ({"blocks": [{"t": "Header", "c": []}]}, "Header"),
    ],
)
def test_invalid_pandoc_ast_is_rejected(ast: dict[str, object], message: str) -> None:
    with pytest.raises(IngestionError, match=message):
        map_pandoc_ast(ast, SOURCE)


def test_empty_extraction_is_rejected() -> None:
    with pytest.raises(IngestionError, match="no narratable text"):
        assemble_document(
            book_id="test-book",
            source_format=SourceFormat.PDF,
            source_sha256=HASH,
            fallback_title="Titolo",
            contents=(map_pandoc_ast({"blocks": []}, SOURCE),),
        )
