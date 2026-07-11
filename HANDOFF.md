# Session Handoff

## Current state

- Milestone 3 implementation is on `milestone/c3-normalization-chunking`.
- Branch commits are `8a9644a`, `c0d758a`, `3f25fcc`, and `776d616`.
- Automated C3 verification is complete, while checkpoint C3 awaits the user's report approval.
- The private target source and generated reports remain only under ignored `work/c2-target-project/`.
- Intentional uncommitted changes apply the accepted ponytail simplifications.

## Completed work

- Added deterministic Italian normalization, the reviewed built-in finance lexicon, checksum-pinned overlays, bounded equation speech, and transformation audit trails.
- Added paragraph-first Italian sentence splitting, explicit character limits, stable source-derived chunk identifiers, and pause metadata.
- Added `bilbo normalize` and `bilbo chunk` with atomic dependent artifacts, deterministic summaries, readable reports, and stale-input rejection.
- Added reviewed byte-exact normalization and chunking goldens for both committed fixture books.

## Verification

- `.tools/bin/pixi run check` passes formatting, Ruff linting, strict mypy, all 113 tests, and 93.60 percent coverage.
- Fixture pipelines run `ingest → normalize → chunk`, match byte-exact artifacts, reports, and summaries, and remain byte-idempotent without model downloads.
- Target normalization processed 2,200 blocks with 3,276 transformations, 145 lexicon applications, and 140 full-book warnings.
- Target chunking produced 6,480 chunks with no limit outlier and a maximum length of exactly 300 characters.
- The prepared `Introduzione` review covers blocks `block-000005` through `block-000039` and has no warning.
- The prepared chapter demonstrates Unicode cleanup, whitespace cleanup, currencies, percentages, structural references, paragraph mapping, continuation splits, and all pause categories.

## Durable references

- Architecture and stable policy are owned by [`design.md`](design.md).
- Milestones and checkpoint criteria are owned by [`implementation.md`](implementation.md).
- Repository working conventions are owned by [`AGENTS.md`](AGENTS.md).

## Next action

- Review, commit, and push the intentional ponytail simplifications.
- Review `work/c2-target-project/work/tts-investimento/reports/normalization.md` for `block-000005` through `block-000039`.
- Review the same block range in `work/c2-target-project/work/tts-investimento/reports/chunking.md` and explicitly approve or reject checkpoint C3.
- Resolve the remaining 140 full-book warnings before a full-book text qualification, although they do not occur in the C3 review chapter.
- Merge `milestone/c3-normalization-chunking` only after the desired review and branch checks.
