# Session Handoff

## Current state

- Milestone 2 source ingestion is complete.
- Checkpoint C2 is approved.
- The active branch is `milestone/c2-source-ingestion`.
- The C2 implementation commits are `c925ca3`, `24f56a9`, `c46afe2`, and `b8c6d21`.
- The branch is published at `origin/milestone/c2-source-ingestion`.
- The private target source from `/Users/alsora/repos/alsora/tts-investimento` is staged only under ignored `work/c2-target-project/`.
- The representative chapter `Introduzione` was manually approved for reading order, structure, omissions, and warnings.
- Intentional uncommitted changes expand `README.md` with step-by-step book preparation, configuration, extraction, and review instructions.

## Completed work

- Added deterministic LaTeX ingestion through Pandoc AST and born-digital PDF ingestion through PyMuPDF4LLM.
- Added explicit handling for chapters, paragraphs, headings, lists, quotations, footnotes, tables, equations, captions, references, images, page furniture, blank pages, and scanned material.
- Added aggregate LaTeX source hashing, include-boundary validation, PDF page references, stable IDs, and actionable adapter failures.
- Added recursive `\input`, `\include`, and static `\import` expansion with part-aware chapter boundaries for the target book.
- Recorded and omitted inline citations, resolved numbered cross-references from source labels, excluded captionless images, and repaired currency macro word boundaries.
- Added `bilbo ingest`, canonical atomic document artifacts, deterministic JSON summaries, and readable atomic extraction reports.
- Added reviewed LaTeX, born-digital PDF, and scanned PDF fixtures with deterministic generators and byte-exact goldens.
- Added a reusable CLI integration harness and expanded unit, boundary, failure, and idempotency coverage.
- Updated the locked environment, architecture policy, fixture policy, and user-facing command documentation.

## Verification

- The C1 baseline `.tools/bin/pixi run check` passed before implementation.
- The focused C2 verification passed 46 unit and integration tests.
- `.tools/bin/pixi run check` passes formatting, Ruff linting, strict mypy, and all 79 tests.
- Test coverage is 91.81 percent.
- Real CLI integrations match byte-exact LaTeX and PDF golden artifacts and reports without model downloads.
- Repeated fixture generation and ingestion produce byte-identical outputs.
- Tests reject source and include escapes, malformed adapter output, scanned PDFs, missing tools, invalid summaries, and partial canonical writes.
- Target ingestion produced 16 chapters and 2,200 blocks with 108 warnings and three explicit exclusions.
- `Introduzione` contains ordered blocks `block-000005` through `block-000039`, including four list items and one footnote with no block-specific warnings.
- Target checks confirm `app:dati-rendimento` renders as `appendice A.5` and `chap:analizzare-prodotti` renders as `capitolo 10`.
- Labels on unnumbered subsections resolve to their numbered parent sections, and no target cross-reference remains unresolved.
- The user manually approved `Introduzione` after reviewing the source and corrected extraction report.

## Durable references

- Architecture and stable policy are owned by [`design.md`](design.md).
- Milestones and checkpoint criteria are owned by [`implementation.md`](implementation.md).
- Repository working conventions are owned by [`AGENTS.md`](AGENTS.md).

## Next action

- Review and commit the source-ingestion README update.
- Merge `milestone/c2-source-ingestion` before starting C3.
- Create `milestone/c3-normalization-chunking` from the updated `main`.
- Implement deterministic Italian normalization, pronunciation lexicons, stable chunking, reports, and the manual chapter review required by checkpoint C3.
