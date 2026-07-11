"""Born-digital PDF ingestion through PyMuPDF4LLM."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pymupdf
import pymupdf4llm  # type: ignore[import-untyped]

from bilbo_tts.ingest.common import IngestionError, MappedContent, map_pandoc_ast
from bilbo_tts.ingest.pandoc import read_pandoc_ast
from bilbo_tts.models import ExclusionRecord, SourceLocation


class ScannedPdfError(IngestionError):
    """A PDF contains image-only pages that require deferred OCR."""

    def __init__(self, pages: tuple[int, ...]) -> None:
        self.pages = pages
        rendered = ", ".join(str(page) for page in pages)
        super().__init__(f"PDF contains scanned or image-only pages requiring OCR: {rendered}")


def extract_pdf(
    source_path: Path,
    source_name: str,
) -> tuple[MappedContent, ...]:
    """Extract page-scoped Markdown and map it through Pandoc."""

    scanned_pages, blank_pages = _classify_empty_pages(source_path, source_name)
    if scanned_pages:
        raise ScannedPdfError(scanned_pages)
    try:
        raw_chunks = _to_markdown(
            str(source_path),
        )
    except Exception as error:
        raise IngestionError(f"cannot extract PDF {source_name}: {error}") from error
    if not isinstance(raw_chunks, list):
        raise IngestionError(f"PyMuPDF4LLM returned invalid page chunks for {source_name}")

    contents: list[MappedContent] = []
    for index, chunk in enumerate(raw_chunks):
        if not isinstance(chunk, dict):
            raise IngestionError(f"invalid PDF page chunk at index {index}")
        page = _page_number(chunk, index)
        source = SourceLocation(source_path=source_name, page=page)
        markdown = chunk.get("text")
        if not isinstance(markdown, str):
            raise IngestionError(f"PDF page {page} has no Markdown text field")

        exclusions = _picture_exclusions(chunk, source)
        page_warnings: list[str] = []
        if page in blank_pages or not markdown.strip():
            exclusions.append(
                ExclusionRecord(
                    reason_code="blank-page",
                    description="Blank PDF page excluded",
                    source=source,
                )
            )
            contents.append(MappedContent(blocks=(), exclusions=tuple(exclusions)))
            continue

        ast, diagnostics = read_pandoc_ast(
            from_format="gfm",
            label=f"{source_name} page {page}",
            cwd=source_path.parent,
            input_text=markdown,
        )
        mapped = map_pandoc_ast(ast, source)
        page_warnings.extend(diagnostics)
        contents.append(
            MappedContent(
                blocks=mapped.blocks,
                exclusions=(*mapped.exclusions, *exclusions),
                warnings=tuple(page_warnings),
            )
        )

    if not contents:
        raise IngestionError(f"PDF contains no pages: {source_name}")
    first = contents[0]
    header_footer = ExclusionRecord(
        reason_code="pdf-header-footer",
        description="Page header and footer regions excluded throughout the PDF by policy",
        source=SourceLocation(source_path=source_name, page=1),
    )
    contents[0] = MappedContent(
        blocks=first.blocks,
        exclusions=(header_footer, *first.exclusions),
        warnings=(
            "pdf-header-footer-excluded: verify that no narratable content occupied those regions",
            *first.warnings,
        ),
    )
    return tuple(contents)


def _classify_empty_pages(
    source_path: Path,
    source_name: str,
) -> tuple[tuple[int, ...], tuple[int, ...]]:
    scanned: list[int] = []
    blank: list[int] = []
    try:
        with pymupdf.open(source_path) as document:  # type: ignore[no-untyped-call]
            if document.page_count == 0:
                raise IngestionError(f"PDF contains no pages: {source_name}")
            for index, page in enumerate(document):
                if page.get_text("text").strip():
                    continue
                has_images = bool(page.get_images(full=True))
                has_dense_graphics = len(page.get_drawings()) >= 20
                if has_images or has_dense_graphics:
                    scanned.append(index + 1)
                else:
                    blank.append(index + 1)
    except IngestionError:
        raise
    except Exception as error:
        raise IngestionError(f"cannot read PDF {source_name}: {error}") from error
    return tuple(scanned), tuple(blank)


def _to_markdown(source_path: str) -> Any:
    return pymupdf4llm.to_markdown(
        source_path,
        page_chunks=True,
        use_ocr=False,
        force_ocr=False,
        header=False,
        footer=False,
        write_images=False,
        embed_images=False,
        show_progress=False,
    )


def _page_number(chunk: dict[str, Any], index: int) -> int:
    metadata = chunk.get("metadata")
    if not isinstance(metadata, dict):
        raise IngestionError(f"PDF page chunk {index} has no metadata")
    page = metadata.get("page_number")
    if not isinstance(page, int) or page < 1:
        raise IngestionError(f"PDF page chunk {index} has an invalid page number")
    return page


def _picture_exclusions(
    chunk: dict[str, Any],
    source: SourceLocation,
) -> list[ExclusionRecord]:
    boxes = chunk.get("page_boxes", [])
    if not isinstance(boxes, list):
        raise IngestionError(f"PDF page {source.page} has invalid layout boxes")
    exclusions: list[ExclusionRecord] = []
    for box in boxes:
        if not isinstance(box, dict):
            raise IngestionError(f"PDF page {source.page} has an invalid layout box")
        box_class = box.get("class")
        if isinstance(box_class, str) and box_class.casefold() in {"image", "picture"}:
            exclusions.append(
                ExclusionRecord(
                    reason_code="non-narratable-image",
                    description="PDF image region without separate narratable text excluded",
                    source=source,
                )
            )
    return exclusions
