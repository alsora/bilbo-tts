"""Shared Pandoc AST mapping and canonical document assembly."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from bilbo_tts.models import (
    BlockKind,
    BookDocument,
    ChapterDocument,
    DocumentBlock,
    ExclusionRecord,
    SourceFormat,
    SourceLocation,
)


class IngestionError(RuntimeError):
    """A source cannot be converted into a trustworthy document."""


@dataclass(frozen=True)
class MappedBlock:
    """One structural block before stable IDs and chapters are assigned."""

    kind: BlockKind
    text: str
    source: SourceLocation
    warnings: tuple[str, ...] = ()
    heading_level: int | None = None


@dataclass(frozen=True)
class MappedContent:
    """Pandoc blocks plus all explicitly reported omissions."""

    blocks: tuple[MappedBlock, ...]
    exclusions: tuple[ExclusionRecord, ...] = ()
    warnings: tuple[str, ...] = ()
    chapter_heading_level: int = 1


def map_pandoc_ast(ast: dict[str, Any], source: SourceLocation) -> MappedContent:
    """Convert a validated Pandoc JSON document into ordered source blocks."""

    raw_blocks = ast.get("blocks")
    if not isinstance(raw_blocks, list):
        raise IngestionError("Pandoc JSON does not contain a blocks list")
    blocks, exclusions = _map_blocks(raw_blocks, source)
    return MappedContent(blocks=tuple(blocks), exclusions=tuple(exclusions))


def assemble_document(
    *,
    book_id: str,
    source_format: SourceFormat,
    source_sha256: str,
    fallback_title: str,
    contents: tuple[MappedContent, ...],
    warnings: tuple[str, ...] = (),
) -> BookDocument:
    """Assign deterministic IDs and chapter boundaries to mapped content."""

    mapped_blocks = [block for content in contents for block in content.blocks]
    exclusions = [item for content in contents for item in content.exclusions]
    document_warnings = [
        *warnings,
        *(warning for content in contents for warning in content.warnings),
    ]
    chapter_levels = {content.chapter_heading_level for content in contents}
    if len(chapter_levels) != 1:
        raise IngestionError("source adapters disagree about the chapter heading level")
    chapter_heading_level = chapter_levels.pop()
    if chapter_heading_level < 1:
        raise IngestionError("chapter heading level must be positive")
    if not mapped_blocks:
        raise IngestionError("source extraction produced no narratable text")

    chapters: list[ChapterDocument] = []
    current_title = fallback_title
    current_blocks: list[DocumentBlock] = []
    pending_headings: list[MappedBlock] = []
    block_number = 0
    excluding_references = False
    saw_chapter_heading = False

    def finish_chapter(title: str) -> None:
        if not current_blocks:
            return
        chapters.append(
            ChapterDocument(
                chapter_id=f"chapter-{len(chapters) + 1:04d}",
                order=len(chapters),
                title=title,
                blocks=tuple(current_blocks),
            )
        )
        current_blocks.clear()

    def append_block(mapped: MappedBlock) -> None:
        nonlocal block_number
        block_number += 1
        current_blocks.append(
            DocumentBlock(
                block_id=f"block-{block_number:06d}",
                kind=mapped.kind,
                display_text=mapped.text,
                source=mapped.source,
                warnings=mapped.warnings,
            )
        )

    for mapped in mapped_blocks:
        is_higher_heading = (
            mapped.kind is BlockKind.HEADING
            and mapped.heading_level is not None
            and mapped.heading_level < chapter_heading_level
        )
        if is_higher_heading:
            finish_chapter("Front matter" if not saw_chapter_heading else current_title)
            pending_headings.append(mapped)
            excluding_references = False
            continue

        is_chapter_heading = (
            mapped.kind is BlockKind.HEADING and mapped.heading_level == chapter_heading_level
        )
        if is_chapter_heading:
            if _is_references_heading(mapped.text):
                finish_chapter("Front matter" if not saw_chapter_heading else current_title)
                pending_headings.clear()
                exclusions.append(
                    ExclusionRecord(
                        reason_code="reference-section",
                        description=f"Reference section excluded from narration: {mapped.text}",
                        source=mapped.source,
                    )
                )
                excluding_references = True
                continue
            if current_blocks:
                finish_chapter("Front matter" if not saw_chapter_heading else current_title)
            current_title = mapped.text
            saw_chapter_heading = True
            excluding_references = False
            for pending in pending_headings:
                append_block(pending)
            pending_headings.clear()

        if excluding_references:
            continue

        append_block(mapped)

    for pending in pending_headings:
        append_block(pending)
    if pending_headings and not saw_chapter_heading:
        current_title = pending_headings[-1].text
    finish_chapter(current_title)
    if not chapters:
        raise IngestionError("source extraction produced no chapters")

    return BookDocument(
        book_id=book_id,
        source_format=source_format,
        source_sha256=source_sha256,
        chapters=tuple(chapters),
        exclusions=tuple(exclusions),
        warnings=_unique((*document_warnings,)),
    )


def _map_blocks(
    raw_blocks: list[Any],
    source: SourceLocation,
) -> tuple[list[MappedBlock], list[ExclusionRecord]]:
    blocks: list[MappedBlock] = []
    exclusions: list[ExclusionRecord] = []
    for raw in raw_blocks:
        if not isinstance(raw, dict) or not isinstance(raw.get("t"), str):
            raise IngestionError("Pandoc block entries must be tagged objects")
        tag = raw["t"]
        content = raw.get("c")

        if tag == "Header":
            if (
                not isinstance(content, list)
                or len(content) != 3
                or not isinstance(content[0], int)
            ):
                raise IngestionError("invalid Pandoc Header block")
            text = _clean_text(_plain_text(content[2]))
            if text:
                blocks.append(
                    MappedBlock(
                        kind=BlockKind.HEADING,
                        text=text,
                        source=source,
                        heading_level=content[0],
                    )
                )
            continue

        if tag in {"Para", "Plain"}:
            paragraph_blocks, paragraph_exclusions = _map_paragraph(content, source)
            blocks.extend(paragraph_blocks)
            exclusions.extend(paragraph_exclusions)
            continue

        if tag in {"BulletList", "OrderedList"}:
            items = content if tag == "BulletList" else _ordered_items(content)
            if not isinstance(items, list):
                raise IngestionError(f"invalid Pandoc {tag} block")
            for item in items:
                if not isinstance(item, list):
                    raise IngestionError(f"invalid Pandoc {tag} item")
                nested, omitted = _map_blocks(item, source)
                exclusions.extend(omitted)
                for mapped in nested:
                    if mapped.kind is BlockKind.PARAGRAPH:
                        mapped = MappedBlock(
                            kind=BlockKind.LIST_ITEM,
                            text=mapped.text,
                            source=mapped.source,
                            warnings=mapped.warnings,
                        )
                    blocks.append(mapped)
            continue

        if tag == "BlockQuote":
            if not isinstance(content, list):
                raise IngestionError("invalid Pandoc BlockQuote block")
            nested, omitted = _map_blocks(content, source)
            exclusions.extend(omitted)
            quotation_text = _clean_text(
                " ".join(block.text for block in nested if block.kind is not BlockKind.FOOTNOTE)
            )
            if quotation_text:
                blocks.append(
                    MappedBlock(kind=BlockKind.QUOTATION, text=quotation_text, source=source)
                )
            blocks.extend(block for block in nested if block.kind is BlockKind.FOOTNOTE)
            continue

        if tag == "Table":
            text = _clean_text(" ".join(_text_segments(content)))
            if text:
                blocks.append(
                    MappedBlock(
                        kind=BlockKind.TABLE,
                        text=text,
                        source=source,
                        warnings=("table-linearized: verify row and column reading order",),
                    )
                )
            else:
                exclusions.append(_exclusion("empty-table", "Empty table excluded", source))
            continue

        if tag == "Figure":
            text = _clean_text(_plain_text(content))
            if text:
                blocks.append(MappedBlock(kind=BlockKind.CAPTION, text=text, source=source))
            else:
                exclusions.append(
                    _exclusion("non-narratable-image", "Figure without a caption excluded", source)
                )
            continue

        if tag == "Div":
            nested_raw = content[1] if isinstance(content, list) and len(content) == 2 else None
            if not isinstance(nested_raw, list):
                raise IngestionError("invalid Pandoc Div block")
            nested, omitted = _map_blocks(nested_raw, source)
            blocks.extend(nested)
            exclusions.extend(omitted)
            continue

        if tag in {"RawBlock", "CodeBlock", "HorizontalRule"}:
            exclusions.append(
                _exclusion(
                    "unsupported-pandoc-block",
                    f"Unsupported Pandoc block excluded: {tag}",
                    source,
                )
            )
            continue

        text = _clean_text(_plain_text(content))
        if text:
            blocks.append(
                MappedBlock(
                    kind=BlockKind.PARAGRAPH,
                    text=text,
                    source=source,
                    warnings=(f"unsupported-pandoc-block: review {tag}",),
                )
            )
        else:
            exclusions.append(
                _exclusion(
                    "unsupported-pandoc-block",
                    f"Unsupported empty Pandoc block excluded: {tag}",
                    source,
                )
            )
    return blocks, exclusions


def _map_paragraph(
    content: Any,
    source: SourceLocation,
) -> tuple[list[MappedBlock], list[ExclusionRecord]]:
    if not isinstance(content, list):
        raise IngestionError("invalid Pandoc paragraph")
    if len(content) == 1 and _tag(content[0]) == "Math" and _math_kind(content[0]) == "DisplayMath":
        text = _clean_text(_plain_text(content[0]))
        if not text:
            return [], [_exclusion("empty-equation", "Empty display equation excluded", source)]
        return [
            MappedBlock(
                kind=BlockKind.EQUATION,
                text=text,
                source=source,
                warnings=("equation-requires-review: mathematical speech is not normalized yet",),
            )
        ], []

    text_parts: list[str] = []
    footnotes: list[MappedBlock] = []
    warnings: list[str] = []
    image_only = _contains_only_image(content)
    for inline in content:
        if _tag(inline) == "Note":
            note_content = inline.get("c") if isinstance(inline, dict) else None
            if not isinstance(note_content, list):
                raise IngestionError("invalid Pandoc footnote")
            note_text = _clean_text(_plain_text(note_content))
            if note_text:
                footnotes.append(
                    MappedBlock(kind=BlockKind.FOOTNOTE, text=note_text, source=source)
                )
            continue
        if _tag(inline) == "Math":
            warnings.append("inline-equation-requires-review")
        text_parts.append(_plain_text(inline))

    text = _clean_text("".join(text_parts))
    blocks: list[MappedBlock] = []
    exclusions: list[ExclusionRecord] = []
    if image_only and (not text or text.casefold() in {"image", "figura"}):
        exclusions.append(
            _exclusion("non-narratable-image", "Image without a caption excluded", source)
        )
    elif text:
        blocks.append(
            MappedBlock(
                kind=BlockKind.CAPTION if image_only else BlockKind.PARAGRAPH,
                text=text,
                source=source,
                warnings=_unique(tuple(warnings)),
            )
        )
    blocks.extend(footnotes)
    return blocks, exclusions


def _plain_text(value: Any) -> str:
    return "".join(_text_parts(value, preserve_spacing=True))


def _text_segments(value: Any) -> list[str]:
    return _text_parts(value, preserve_spacing=False)


def _text_parts(value: Any, *, preserve_spacing: bool) -> list[str]:
    if isinstance(value, list):
        return [
            part for item in value for part in _text_parts(item, preserve_spacing=preserve_spacing)
        ]
    if not isinstance(value, dict):
        return []
    tag = value.get("t")
    content = value.get("c")
    if tag == "Str" and isinstance(content, str):
        return [content]
    if tag in {"Space", "SoftBreak", "LineBreak"}:
        return [" "] if preserve_spacing else []
    if tag in {"Code", "Math"} and isinstance(content, list) and len(content) == 2:
        return [str(content[1])]
    if tag == "RawInline" and isinstance(content, list) and len(content) == 2:
        return [str(content[1])] if preserve_spacing else []
    if tag == "Quoted" and isinstance(content, list) and len(content) == 2:
        quoted = _text_parts(content[1], preserve_spacing=preserve_spacing)
        return ['"', *quoted, '"'] if preserve_spacing else quoted
    if tag in {"Link", "Image"} and isinstance(content, list) and len(content) >= 2:
        return _text_parts(content[1], preserve_spacing=preserve_spacing)
    if tag == "Note":
        return []
    return _text_parts(content, preserve_spacing=preserve_spacing)


def _ordered_items(content: Any) -> Any:
    if isinstance(content, list) and len(content) == 2:
        return content[1]
    return None


def _tag(value: Any) -> str | None:
    return value.get("t") if isinstance(value, dict) and isinstance(value.get("t"), str) else None


def _math_kind(value: Any) -> str | None:
    if not isinstance(value, dict):
        return None
    content = value.get("c")
    if not isinstance(content, list) or not content or not isinstance(content[0], dict):
        return None
    kind = content[0].get("t")
    return kind if isinstance(kind, str) else None


def _clean_text(text: str) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    return re.sub(r"(?<=[€$£])(?=[^\W\d_])", " ", text)


def _is_references_heading(text: str) -> bool:
    normalized = re.sub(r"[^a-zà-ÿ]+", " ", text.casefold()).strip()
    return normalized in {"bibliografia", "bibliography", "references", "riferimenti"}


def _contains_only_image(value: Any) -> bool:
    if isinstance(value, list):
        return len(value) == 1 and _contains_only_image(value[0])
    if not isinstance(value, dict):
        return False
    tag = value.get("t")
    content = value.get("c")
    if tag == "Image":
        return True
    if tag == "Span" and isinstance(content, list) and len(content) == 2:
        return _contains_only_image(content[1])
    if tag in {"Emph", "Strong"}:
        return _contains_only_image(content)
    return False


def _exclusion(reason_code: str, description: str, source: SourceLocation) -> ExclusionRecord:
    return ExclusionRecord(reason_code=reason_code, description=description, source=source)


def _unique(values: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(values))
