"""LaTeX ingestion through the pinned Pandoc JSON AST."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from bilbo_tts.ingest.common import IngestionError, MappedContent, map_pandoc_ast
from bilbo_tts.ingest.pandoc import read_pandoc_ast
from bilbo_tts.models import ExclusionRecord, SourceLocation


@dataclass(frozen=True)
class PreparedLatex:
    """Self-contained source text plus preprocessing review signals."""

    text: str
    warnings: tuple[str, ...] = ()
    exclusions: tuple[ExclusionRecord, ...] = ()


@dataclass(frozen=True)
class ReferenceTarget:
    """One source label rendered as an Italian structural reference."""

    kind: str
    number: str


def extract_latex(
    source_path: Path,
    source_name: str,
    *,
    pandoc_executable: str = "pandoc",
) -> MappedContent:
    """Parse a LaTeX entry point and map its Pandoc AST."""

    prepared = _prepare_latex(source_path, source_name)
    raw_ast, diagnostics = read_pandoc_ast(
        from_format="latex",
        label=source_name,
        cwd=source_path.parent,
        pandoc_executable=pandoc_executable,
        input_text=prepared.text,
    )
    mapped = map_pandoc_ast(raw_ast, SourceLocation(source_path=source_name))
    return MappedContent(
        blocks=mapped.blocks,
        exclusions=(*mapped.exclusions, *prepared.exclusions),
        warnings=(
            "latex-source-lines-unavailable: Pandoc preserves the source path but not line ranges",
            *diagnostics,
            *prepared.warnings,
        ),
        chapter_heading_level=_chapter_heading_level(prepared.text),
    )


def _prepare_latex(source_path: Path, source_name: str) -> PreparedLatex:
    source_root = source_path.parent.resolve()
    text = _inline_source(source_path, source_root, ())
    text, reference_warnings = _resolve_references(text)
    citation_pattern = re.compile(
        r"\\(?:cite|citep|citet|autocite|parencite|textcite)\*?"
        r"(?:\[[^\]]*\]){0,2}\{[^{}]+\}"
    )
    citation_count = len(citation_pattern.findall(text))
    text = citation_pattern.sub("", text)

    warnings = list(reference_warnings)
    exclusions: list[ExclusionRecord] = []
    source = SourceLocation(source_path=source_name)
    if citation_count:
        warnings.append(
            f"latex-inline-citations-omitted: {citation_count} citation commands excluded"
        )
        exclusions.append(
            ExclusionRecord(
                reason_code="inline-citations",
                description=f"{citation_count} inline citation commands excluded from narration",
                source=source,
            )
        )
    return PreparedLatex(
        text=text,
        warnings=tuple(warnings),
        exclusions=tuple(exclusions),
    )


def _resolve_references(source: str) -> tuple[str, tuple[str, ...]]:
    references = _reference_index(source)
    unresolved: list[str] = []

    def autoref(match: re.Match[str]) -> str:
        label = match.group(1)
        target = references.get(label)
        if target is None:
            unresolved.append(label)
            return "riferimento non risolto"
        return f"{target.kind} {target.number}"

    def appref(match: re.Match[str]) -> str:
        label = match.group(1)
        target = references.get(label)
        if target is None:
            unresolved.append(label)
            return "appendice non risolta"
        return f"appendice {target.number}"

    def plain_ref(match: re.Match[str]) -> str:
        label = match.group(1)
        target = references.get(label)
        if target is None:
            unresolved.append(label)
            return "riferimento non risolto"
        return target.number

    source = re.sub(r"\\autoref\s*\{([^{}]+)\}", autoref, source)
    source = re.sub(r"\\appref\s*\{([^{}]+)\}", appref, source)
    source = re.sub(r"\\ref\s*\{([^{}]+)\}", plain_ref, source)
    warnings: tuple[str, ...] = ()
    if unresolved:
        unique = tuple(dict.fromkeys(unresolved))
        warnings = (
            "latex-cross-references-unresolved: "
            f"{len(unresolved)} commands reference missing labels {', '.join(unique)}",
        )
    return source, warnings


def _reference_index(source: str) -> dict[str, ReferenceTarget]:
    source = "".join(_split_comment(line)[0] for line in source.splitlines(keepends=True))
    token_pattern = re.compile(
        r"\\begin\s*\{(?P<begin>appendices|figure|table|equation)\}"
        r"|\\end\s*\{(?P<end>appendices)\}"
        r"|\\(?P<heading>chapter|section|subsection)(?P<star>\*)?\s*"
        r"(?:\[[^\]]*\])?\{[^{}]*\}"
        r"|\\label\s*\{(?P<label>[^{}]+)\}"
    )
    references: dict[str, ReferenceTarget] = {}
    chapter = 0
    appendix_chapter = 0
    section = 0
    subsection = 0
    figure = 0
    table = 0
    equation = 0
    appendix_mode = False
    chapter_number = ""
    current: ReferenceTarget | None = None

    for match in token_pattern.finditer(source):
        begin = match.group("begin")
        heading = match.group("heading")
        label = match.group("label")
        if begin == "appendices":
            appendix_mode = True
            appendix_chapter = 0
            continue
        if match.group("end") == "appendices":
            appendix_mode = False
            continue
        if begin in {"figure", "table", "equation"}:
            if begin == "figure":
                figure += 1
                current = ReferenceTarget("figura", _number_with_chapter(chapter_number, figure))
            elif begin == "table":
                table += 1
                current = ReferenceTarget("tabella", _number_with_chapter(chapter_number, table))
            else:
                equation += 1
                current = ReferenceTarget(
                    "equazione",
                    _number_with_chapter(chapter_number, equation),
                )
            continue
        if heading is not None:
            if match.group("star"):
                current = None
                continue
            if heading == "chapter":
                if appendix_mode:
                    appendix_chapter += 1
                    chapter_number = _alphabetic(appendix_chapter)
                    current = ReferenceTarget("appendice", chapter_number)
                else:
                    chapter += 1
                    chapter_number = str(chapter)
                    current = ReferenceTarget("capitolo", chapter_number)
                section = 0
                subsection = 0
                figure = 0
                table = 0
                equation = 0
            elif heading == "section":
                section += 1
                subsection = 0
                current = ReferenceTarget(
                    "sezione",
                    _number_with_chapter(chapter_number, section),
                )
            else:
                subsection += 1
                current = ReferenceTarget(
                    "sottosezione",
                    ".".join(
                        part for part in (chapter_number, str(section), str(subsection)) if part
                    ),
                )
            continue
        if label is not None and current is not None:
            references[label] = current
    return references


def _number_with_chapter(chapter: str, value: int) -> str:
    return f"{chapter}.{value}" if chapter else str(value)


def _alphabetic(value: int) -> str:
    letters = ""
    while value:
        value, remainder = divmod(value - 1, 26)
        letters = chr(ord("A") + remainder) + letters
    return letters


def _inline_source(path: Path, source_root: Path, stack: tuple[Path, ...]) -> str:
    resolved = path.resolve()
    if not resolved.is_relative_to(source_root):
        raise IngestionError(f"LaTeX include escapes the source directory: {path}")
    if resolved in stack:
        cycle = " -> ".join(item.name for item in (*stack, resolved))
        raise IngestionError(f"cyclic LaTeX include detected: {cycle}")
    try:
        source = resolved.read_text(encoding="utf-8")
    except OSError as error:
        raise IngestionError(f"cannot read LaTeX source {resolved}: {error}") from error

    def include(match: re.Match[str]) -> str:
        return _inline_source(
            _include_path(resolved.parent, match.group(1)),
            source_root,
            (*stack, resolved),
        )

    def imported(match: re.Match[str]) -> str:
        relative = str(Path(match.group(1)) / match.group(2))
        return _inline_source(
            _include_path(resolved.parent, relative),
            source_root,
            (*stack, resolved),
        )

    lines: list[str] = []
    for line in source.splitlines(keepends=True):
        code, comment = _split_comment(line)
        code = re.sub(r"\\(?:input|include)\s*\{([^{}]+)\}", include, code)
        code = re.sub(r"\\import\s*\{([^{}]+)\}\s*\{([^{}]+)\}", imported, code)
        lines.append(code + comment)
    return "".join(lines)


def _include_path(parent: Path, name: str) -> Path:
    path = parent / name.strip()
    return path if path.suffix else path.with_suffix(".tex")


def _split_comment(line: str) -> tuple[str, str]:
    for index, character in enumerate(line):
        if character != "%":
            continue
        backslashes = 0
        cursor = index - 1
        while cursor >= 0 and line[cursor] == "\\":
            backslashes += 1
            cursor -= 1
        if backslashes % 2 == 0:
            return line[:index], line[index:]
    return line, ""


def _chapter_heading_level(source: str) -> int:
    uncommented = re.sub(r"(?<!\\)%.*", "", source)
    return 2 if re.search(r"\\part\*?\s*\{", uncommented) else 1
