from __future__ import annotations

from pathlib import Path

from bilbo_tts.ingest.common import assemble_document
from bilbo_tts.ingest.latex import extract_latex
from bilbo_tts.models import BlockKind, SourceFormat


def test_static_import_directives_are_extracted_in_source_order(tmp_path: Path) -> None:
    chapters = tmp_path / "chapters"
    chapters.mkdir()
    (chapters / "imported.tex").write_text(
        "\\chapter{Capitolo importato}\n\nTesto importato.\n",
        encoding="utf-8",
    )
    source = tmp_path / "main.tex"
    source.write_text(
        "\\chapter{Capitolo diretto}\n\nTesto diretto.\n\\import{chapters/}{imported}\n",
        encoding="utf-8",
    )

    mapped = extract_latex(source, "source/main.tex")

    assert [block.text for block in mapped.blocks if block.kind is BlockKind.HEADING] == [
        "Capitolo diretto",
        "Capitolo importato",
    ]
    assert [block.text for block in mapped.blocks if block.kind is BlockKind.PARAGRAPH] == [
        "Testo diretto.",
        "Testo importato.",
    ]


def test_parts_are_preserved_without_replacing_chapter_boundaries(tmp_path: Path) -> None:
    source = tmp_path / "main.tex"
    source.write_text(
        "\\chapter{Introduzione}\n\nTesto iniziale.\n"
        "\\part{Fondamenti}\n"
        "\\chapter{Primo capitolo}\n\nTesto del capitolo.\n",
        encoding="utf-8",
    )

    mapped = extract_latex(source, "source/main.tex")
    document = assemble_document(
        book_id="book",
        source_format=SourceFormat.LATEX,
        source_sha256="a" * 64,
        fallback_title="Titolo",
        contents=(mapped,),
    )

    assert mapped.chapter_heading_level == 2
    assert [chapter.title for chapter in document.chapters] == [
        "Introduzione",
        "Primo capitolo",
    ]
    assert [block.display_text for block in document.chapters[1].blocks[:2]] == [
        "Fondamenti",
        "Primo capitolo",
    ]


def test_citations_are_excluded_and_appendix_references_remain_readable(
    tmp_path: Path,
) -> None:
    source = tmp_path / "main.tex"
    source.write_text(
        "\\chapter{Capitolo}\n\n"
        "Una fonte \\cite{book:source} e un dato al 5\\% nell'\\appref{app:data}.\n",
        encoding="utf-8",
    )

    mapped = extract_latex(source, "source/main.tex")

    paragraph = next(block for block in mapped.blocks if block.kind is BlockKind.PARAGRAPH)
    assert paragraph.text == "Una fonte e un dato al 5% nell’appendice."
    assert mapped.exclusions[0].reason_code == "inline-citations"
    assert "1 citation commands excluded" in mapped.warnings[1]
    assert "1 appendix references rendered without numbers" in mapped.warnings[2]
