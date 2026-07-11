# Session Handoff

## Current state

- The active branch is `main` at `68e3fb7`, four commits ahead of `origin/main`.
- Milestone 3 is merged, while checkpoint C3 still awaits the user's report approval.
- The private target source and generated reports remain only under ignored `work/c2-target-project/`.
- The compact normalization, extraction, chunking, and chapter-review report changes are committed.
- Typographic punctuation preservation is committed.
- Grouped decimal pronunciation is committed.
- Intentional uncommitted changes improve forced intra-sentence split selection.

## Uncommitted work

- A sentence that fits in two chunks prefers semicolons and colons over commas while avoiding fragments shorter than one quarter of the configured limit.
- Longer sentences retain the latest-punctuation behavior to avoid increasing the chunk count.
- `block-000016.s0001` now splits at the colon into 84- and 240-character chunks instead of splitting before `hanno`.
- README and design guidance and a target-sentence regression test reflect the chunking policy.

## Verification

- `.tools/bin/pixi run check` passes formatting, Ruff linting, strict mypy, all 126 tests, and 93.53 percent coverage.
- All 5 focused chunking tests pass with `pytest --no-cov`.
- Fixture pipelines run `ingest → normalize → chunk`, match byte-exact artifacts, reports, and summaries, and remain byte-idempotent without model downloads.
- Target chunking and focused chapter 2 and chapter 3 reviews were regenerated successfully.
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
- Commit the stronger-punctuation chunking fix after review.
- Resolve the remaining 140 full-book warnings before a full-book text qualification, although they do not occur in the C3 review chapter.
- Resume the milestone 4 implementation plan after C3 approval.
