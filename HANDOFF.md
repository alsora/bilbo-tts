# Session Handoff

## Current state

- The active branch is `main` at `9a4857b`, three commits ahead of `origin/main`.
- Milestone 3 is merged, while checkpoint C3 still awaits the user's report approval.
- The private target source and generated reports remain only under ignored `work/c2-target-project/`.
- The compact normalization, extraction, chunking, and chapter-review report changes are committed.
- Typographic punctuation preservation is committed.
- Intentional uncommitted changes correct grouped decimal pronunciation.

## Uncommitted work

- Decimal fractional parts are read as grouped numbers, so `0,25%` becomes `zero virgola venticinque per cento`.
- Significant leading zero positions remain explicit, so `0,025%` becomes `zero virgola zero venticinque per cento`.
- README and design guidance and regression tests reflect the decimal policy.

## Verification

- `.tools/bin/pixi run check` passes formatting, Ruff linting, strict mypy, all 125 tests, and 93.55 percent coverage.
- All 21 focused normalization tests pass with `pytest --no-cov`.
- Fixture pipelines run `ingest → normalize → chunk`, match byte-exact artifacts, reports, and summaries, and remain byte-idempotent without model downloads.
- The target `normalize → chunk` pipeline and focused chunk review were regenerated successfully with preserved punctuation.
- Target extraction contains 16 chapters, 2,200 blocks, 108 warnings, and 3 exclusions.
- Target normalization contains 2,200 blocks, 1,890 transformations, 145 lexicon applications, and 140 full-book warnings.
- Target chunking contains 6,480 chunks, 335 forced intra-sentence splits, no invariant anomaly, and a maximum length of exactly 300 characters.
- Focused `chapter-0002` extraction and chunking reports contain 35 source blocks and 133 chunks.

## Durable references

- Architecture and stable policy are owned by [`design.md`](design.md).
- Milestones and checkpoint criteria are owned by [`implementation.md`](implementation.md).
- Repository working conventions are owned by [`AGENTS.md`](AGENTS.md).

## Next action

- Review `work/c2-target-project/work/tts-investimento/reports/review/chapter-0002-extraction.md`.
- Review `work/c2-target-project/work/tts-investimento/reports/normalization.md` changes for `block-000005` through `block-000039`.
- Review `work/c2-target-project/work/tts-investimento/reports/review/chapter-0002-chunking.md` and explicitly approve or reject checkpoint C3.
- Commit the grouped-decimal pronunciation fix after review.
- Resolve the remaining 140 full-book warnings before a full-book text qualification, although they do not occur in the C3 review chapter.
- Resume the milestone 4 implementation plan after C3 approval.
