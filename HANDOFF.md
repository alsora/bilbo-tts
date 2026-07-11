# Session Handoff

## Current state

- The active branch is `main` at `6ad4372`, one commit ahead of `origin/main`.
- Milestone 3 is merged, while checkpoint C3 still awaits the user's report approval.
- The private target source and generated reports remain only under ignored `work/c2-target-project/`.
- The compact normalization report change is committed.
- Intentional uncommitted changes compact extraction and chunking reports and add chapter-scoped review commands.

## Uncommitted work

- The full-book extraction report now contains a chapter outline, grouped warnings and exclusions, and exceptional structural blocks instead of every paragraph.
- The full-book chunking report now contains chapter metrics, forced intra-sentence split contexts, and invariant anomalies instead of complete chunk text.
- `bilbo review-extraction` and `bilbo review-chunking` write complete reports for one selected chapter.
- The complete book and chunk contents remain in the canonical JSON manifests.
- README and design guidance, focused tests, reviewed goldens, and summary checksums reflect the new workflow.

## Verification

- `.tools/bin/pixi run check` passes formatting, Ruff linting, strict mypy, all 121 tests, and 93.54 percent coverage.
- Focused report, review-service, and CLI tests pass with `pytest --no-cov`.
- Fixture pipelines run `ingest → normalize → chunk`, match byte-exact artifacts, reports, and summaries, and remain byte-idempotent without model downloads.
- The target `ingest → normalize → chunk` pipeline was rerun successfully with the compact report renderers.
- Target extraction contains 16 chapters, 2,200 blocks, 108 warnings, and 3 exclusions.
- Target normalization still contains 2,200 blocks, 3,276 transformations, 145 lexicon applications, and 140 full-book warnings.
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
- Commit the compact extraction, chunking, and focused-review changes after review.
- Resolve the remaining 140 full-book warnings before a full-book text qualification, although they do not occur in the C3 review chapter.
- Resume the milestone 4 implementation plan after C3 approval.
