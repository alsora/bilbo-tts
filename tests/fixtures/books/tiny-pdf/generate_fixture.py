"""Generate the reviewed born-digital PDF used by C2 integration tests."""

# mypy: disable-error-code="no-any-return,no-untyped-call"

from __future__ import annotations

from pathlib import Path

import pymupdf


def main() -> None:
    output = Path(__file__).parent / "source" / "book.pdf"
    output.parent.mkdir(parents=True, exist_ok=True)
    document = pymupdf.open()
    document.set_metadata(
        {
            "title": "Piccolo libro PDF",
            "author": "Ada Autrice",
            "creationDate": "D:20260101000000Z",
            "modDate": "D:20260101000000Z",
        }
    )

    first = document.new_page(width=595, height=842)
    _frame(first, 1)
    first.insert_text((54, 82), "1 Fondamenti PDF", fontsize=20)
    first.insert_textbox(
        pymupdf.Rect(54, 105, 282, 170),
        "Il primo paragrafo occupa la colonna sinistra e conserva l'ordine di lettura.",
        fontsize=11,
    )
    first.insert_textbox(
        pymupdf.Rect(320, 105, 545, 170),
        "La seconda colonna segue la prima senza mescolare le frasi.",
        fontsize=11,
    )
    first.insert_text((62, 205), "• Primo elemento", fontsize=11)
    first.insert_text((62, 224), "• Secondo elemento", fontsize=11)
    first.insert_textbox(
        pymupdf.Rect(70, 250, 525, 292),
        "Una citazione PDF mantiene una posizione riconoscibile.",
        fontsize=11,
        fontname="Times-Italic",
    )
    _table(first)

    second = document.new_page(width=595, height=842)
    _frame(second, 2)
    second.insert_text((54, 82), "2 Applicazioni PDF", fontsize=20)
    second.insert_textbox(
        pymupdf.Rect(54, 108, 540, 160),
        "Il secondo capitolo verifica il cambio pagina e le sorgenti numerate.",
        fontsize=11,
    )
    second.insert_image(pymupdf.Rect(70, 200, 190, 290), stream=_picture_png())
    second.insert_text((70, 310), "Figura 1: andamento del capitale.", fontsize=10)

    document.save(output, garbage=4, deflate=True, no_new_id=True)
    document.close()


def _frame(page: pymupdf.Page, number: int) -> None:
    page.insert_text((48, 28), "PICCOLO PDF — TEST DI ESTRAZIONE", fontsize=8)
    page.insert_text((285, 820), str(number), fontsize=8)


def _table(page: pymupdf.Page) -> None:
    left, top, right, bottom = 54, 330, 350, 405
    page.draw_rect(pymupdf.Rect(left, top, right, bottom))
    page.draw_line((left, 355), (right, 355))
    page.draw_line((left, 380), (right, 380))
    page.draw_line((180, top), (180, bottom))
    page.insert_text((62, 348), "Anno", fontsize=10)
    page.insert_text((190, 348), "Rendimento", fontsize=10)
    page.insert_text((62, 373), "2024", fontsize=10)
    page.insert_text((190, 373), "4 per cento", fontsize=10)
    page.insert_text((62, 398), "2025", fontsize=10)
    page.insert_text((190, 398), "5 per cento", fontsize=10)


def _picture_png() -> bytes:
    pixmap = pymupdf.Pixmap(
        pymupdf.csRGB,
        pymupdf.IRect(0, 0, 4, 4),
        False,
    )
    pixmap.clear_with(0xA9C5DA)
    return pixmap.tobytes("png")


if __name__ == "__main__":
    main()
