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
    citation_pattern = re.compile(
        r"\\(?:cite|citep|citet|autocite|parencite|textcite)\*?"
        r"(?:\[[^\]]*\]){0,2}\{[^{}]+\}"
    )
    citation_count = len(citation_pattern.findall(text))
    text = citation_pattern.sub("", text)
    appendix_pattern = re.compile(r"\\appref\s*\{[^{}]+\}")
    appendix_count = len(appendix_pattern.findall(text))
    text = appendix_pattern.sub("appendice", text)

    warnings: list[str] = []
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
    if appendix_count:
        warnings.append(
            "latex-appendix-references-generalized: "
            f"{appendix_count} appendix references rendered without numbers"
        )
    return PreparedLatex(
        text=text,
        warnings=tuple(warnings),
        exclusions=tuple(exclusions),
    )


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
