"""Shared setup for artifact-consuming CLI stages."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from bilbo_tts.artifacts import BookWorkspace
from bilbo_tts.config import BookConfig, load_book_config


class StageError(ValueError):
    """A content stage cannot resolve or validate its configured inputs."""


@dataclass(frozen=True)
class StageContext:
    """Resolved configuration and owned workspace for one book."""

    project_root: Path
    config_path: Path
    book_dir: Path
    config: BookConfig
    workspace: BookWorkspace


def load_stage_context(config_path: Path, project_root: Path) -> StageContext:
    """Resolve a strict books/<book-id>/book.yaml stage context."""

    root = project_root.expanduser().resolve()
    candidate = config_path.expanduser()
    if not candidate.is_absolute():
        candidate = root / candidate
    try:
        resolved = candidate.resolve(strict=True)
    except OSError as error:
        raise StageError(f"cannot resolve book configuration {candidate}: {error}") from error
    books_root = (root / "books").resolve()
    if not resolved.is_relative_to(books_root):
        raise StageError(f"book configuration must remain within {books_root}: {resolved}")
    if not resolved.is_file():
        raise StageError(f"book configuration is not a file: {resolved}")
    config = load_book_config(resolved)
    book_dir = resolved.parent
    if book_dir.name != config.book_id:
        raise StageError(
            f"book_id {config.book_id!r} must match configuration directory {book_dir.name!r}"
        )
    return StageContext(
        project_root=root,
        config_path=resolved,
        book_dir=book_dir,
        config=config,
        workspace=BookWorkspace(root, config.book_id),
    )
