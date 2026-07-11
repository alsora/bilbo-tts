from __future__ import annotations

from pathlib import Path

import pytest

from bilbo_tts.ingest import pdf
from bilbo_tts.ingest.common import IngestionError
from bilbo_tts.models import BlockKind


def test_pdf_pages_preserve_page_locations_and_picture_exclusions(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(pdf, "_classify_empty_pages", lambda _path, _name: ((), ()))
    monkeypatch.setattr(
        pdf,
        "_to_markdown",
        lambda *_args, **_kwargs: [
            {
                "metadata": {"page_number": 1},
                "text": "# Capitolo PDF\n\nTesto estratto.\n",
                "page_boxes": [{"class": "picture"}],
            }
        ],
    )

    contents = pdf.extract_pdf(tmp_path / "book.pdf", "source/book.pdf")

    assert [block.kind for block in contents[0].blocks] == [
        BlockKind.HEADING,
        BlockKind.PARAGRAPH,
    ]
    assert contents[0].blocks[0].source.page == 1
    assert [item.reason_code for item in contents[0].exclusions] == [
        "pdf-header-footer",
        "non-narratable-image",
    ]
    assert "pdf-header-footer-excluded" in contents[0].warnings[0]


def test_scanned_pdf_is_rejected_before_partial_extraction(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(pdf, "_classify_empty_pages", lambda _path, _name: ((2, 3), ()))

    with pytest.raises(pdf.ScannedPdfError, match="2, 3") as raised:
        pdf.extract_pdf(tmp_path / "book.pdf", "source/book.pdf")

    assert raised.value.pages == (2, 3)


def test_blank_pdf_page_is_recorded(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(pdf, "_classify_empty_pages", lambda _path, _name: ((), (1,)))
    monkeypatch.setattr(
        pdf,
        "_to_markdown",
        lambda *_args, **_kwargs: [
            {"metadata": {"page_number": 1}, "text": "", "page_boxes": []},
            {
                "metadata": {"page_number": 2},
                "text": "# Capitolo\n\nTesto.\n",
                "page_boxes": [],
            },
        ],
    )

    contents = pdf.extract_pdf(tmp_path / "book.pdf", "source/book.pdf")

    assert contents[0].exclusions[-1].reason_code == "blank-page"
    assert contents[1].blocks[0].source.page == 2


@pytest.mark.parametrize(
    "chunks, message",
    [
        ("markdown", "invalid page chunks"),
        ([None], "invalid PDF page chunk"),
        ([{"text": "test"}], "no metadata"),
        ([{"metadata": {"page_number": 0}, "text": "test"}], "invalid page number"),
    ],
)
def test_invalid_pdf_adapter_output_is_rejected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    chunks: object,
    message: str,
) -> None:
    monkeypatch.setattr(pdf, "_classify_empty_pages", lambda _path, _name: ((), ()))
    monkeypatch.setattr(pdf, "_to_markdown", lambda *_args, **_kwargs: chunks)

    with pytest.raises(IngestionError, match=message):
        pdf.extract_pdf(tmp_path / "book.pdf", "source/book.pdf")
