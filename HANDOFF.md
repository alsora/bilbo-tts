# Session Handoff

## Current state

- Milestone 2 source ingestion is automatically verified.
- Checkpoint C2 is awaiting the required manual review of one representative target-book chapter.
- The active branch is `milestone/c2-source-ingestion`.
- The C2 implementation commits are `c925ca3`, `24f56a9`, and `c46afe2`.
- The private target source from `/Users/alsora/repos/alsora/tts-investimento` is staged only under ignored `work/c2-target-project/`.
- The representative chapter is `Introduzione` in `work/c2-target-project/work/tts-investimento/reports/extraction.md`.

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
- Test coverage is 91.76 percent.
- Real CLI integrations match byte-exact LaTeX and PDF golden artifacts and reports without model downloads.
- Repeated fixture generation and ingestion produce byte-identical outputs.
- Tests reject source and include escapes, malformed adapter output, scanned PDFs, missing tools, invalid summaries, and partial canonical writes.
- Target ingestion produced 16 chapters and 2,200 blocks with 109 warnings and three explicit exclusions.
- `Introduzione` contains ordered blocks `block-000005` through `block-000039`, including four list items and one footnote with no block-specific warnings.
- Target checks confirm `app:dati-rendimento` renders as `appendice A.5` and `chap:analizzare-prodotti` renders as `capitolo 10`.
- Seven commands reference three labels absent from the source and remain explicit `riferimento non risolto` warnings.

## Durable references

- Architecture and stable policy are owned by [`design.md`](design.md).
- Milestones and checkpoint criteria are owned by [`implementation.md`](implementation.md).
- Repository working conventions are owned by [`AGENTS.md`](AGENTS.md).

## Next action

- Obtain manual approval of `Introduzione` for reading order, paragraph/list/footnote structure, omitted inline citations, numbered cross-references, and the absence of silent omissions.
- After approval, record checkpoint C2 as complete in this handoff and push the final documentation commit.
