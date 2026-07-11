"""LaTeX ingestion through the pinned Pandoc JSON AST."""

from __future__ import annotations

from pathlib import Path

from bilbo_tts.ingest.common import MappedContent, map_pandoc_ast
from bilbo_tts.ingest.pandoc import read_pandoc_ast
from bilbo_tts.models import SourceLocation


def extract_latex(
    source_path: Path,
    source_name: str,
    *,
    pandoc_executable: str = "pandoc",
) -> MappedContent:
    """Parse a LaTeX entry point and map its Pandoc AST."""

    raw_ast, diagnostics = read_pandoc_ast(
        from_format="latex",
        label=source_name,
        cwd=source_path.parent,
        input_name=source_path.name,
        pandoc_executable=pandoc_executable,
    )
    mapped = map_pandoc_ast(raw_ast, SourceLocation(source_path=source_name))
    return MappedContent(
        blocks=mapped.blocks,
        exclusions=mapped.exclusions,
        warnings=(
            "latex-source-lines-unavailable: Pandoc preserves the source path but not line ranges",
            *diagnostics,
        ),
    )
