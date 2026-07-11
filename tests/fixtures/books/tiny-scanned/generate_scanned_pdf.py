"""Generate an image-only PDF that proves C2 rejects deferred OCR."""

# mypy: disable-error-code="no-any-return,no-untyped-call"

from __future__ import annotations

from pathlib import Path

import pymupdf


def main() -> None:
    output = Path(__file__).parent / "source" / "book.pdf"
    output.parent.mkdir(parents=True, exist_ok=True)
    document = pymupdf.open()
    page = document.new_page(width=300, height=400)
    pixmap = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 100, 100), False)
    pixmap.clear_with(0xE5E5E5)
    page.insert_image(
        pymupdf.Rect(20, 20, 280, 380),
        stream=pixmap.tobytes("png"),
    )
    document.save(output, garbage=4, deflate=True, no_new_id=True)
    document.close()


if __name__ == "__main__":
    main()
