"""Regenerate committed C2 ingestion goldens from reviewed fixture books."""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

from bilbo_tts.ingest.service import DOCUMENT_PATH, REPORT_PATH, ingest_book


def main() -> None:
    fixture_root = Path(__file__).parent
    for name in ("tiny-latex", "tiny-pdf"):
        with tempfile.TemporaryDirectory(prefix=f"bilbo-{name}-") as temporary:
            project_root = Path(temporary)
            shutil.copytree(
                fixture_root / "books" / name,
                project_root / "books" / name,
            )
            summary = ingest_book(Path("books") / name / "book.yaml", project_root)
            if summary.status != "completed":
                raise RuntimeError(summary.error)
            golden_root = fixture_root / "golden" / name
            golden_root.mkdir(parents=True, exist_ok=True)
            workspace = project_root / "work" / name
            (golden_root / "book-document.json").write_bytes(
                (workspace / DOCUMENT_PATH).read_bytes()
            )
            (golden_root / "extraction.md").write_bytes((workspace / REPORT_PATH).read_bytes())


if __name__ == "__main__":
    main()
