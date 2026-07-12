# Session Handoff

## Current state

- The active branch is `milestone/c8-chapters-2-6`.
- Milestone 8 code and documentation are implemented through commit `e8a831b`.
- Repeatable ordered chapter selection, scoped verification merging, multi-chapter assembly, `bilbo run`, text-only qualification, model-license provenance, and atomic content-addressed build bundles are implemented.
- C8 is deliberately scoped to `chapter-0002` through `chapter-0006` and will produce one five-chapter M4B after listening review clears the verification gate.
- The ignored target workspace is `work/c2-target-project/work/tts-investimento/`.
- All 2,819 selected chunks have current Kokoro audio.
- Verification accepted 2,798 selected chunks, queued none for automatic retry, and left 21 chunks requiring human listening review.
- Assembly and bundle publication have not run because unreviewed chunks correctly block them.
- The deterministic checklist is `reports/listening-checklist.md`, and the matching 47-item playlist is `reports/listening-checklist.m3u` in the target workspace.
- The existing checklist contains the original 22 flagged chunks and five deterministic accepted samples from each selected chapter; refresh it after all pronunciation fixes are regenerated.
- The user will remove the four narrated URLs from the private source document, so URL omission is intentionally not being implemented as a pipeline rule.
- The built-in lexicon now pronounces `INPS` as one word while retaining letter-by-letter pronunciation for acronyms such as `ETF`.
- The two known chapter-0002 Kokoro pause defects remain explicitly accepted limitations as recorded in [`performance.md`](performance.md).
- Chatterbox benchmark and improvement work remains deferred until C8 is accepted.

## Verification

- `.tools/bin/pixi run check` passes formatting, Ruff, strict mypy, 372 ordinary tests, 3 expected hardware skips, and 90.86 percent coverage.
- Opt-in Kokoro and Whisper hardware smoke tests pass with `BILBO_HARDWARE_TESTS=1` and `--no-cov`.
- Text-only qualification reports 752 blocks, 52,110 words, 2,819 chunks, 35 forced splits, 67 length outliers, and an estimated duration of 6:02:36.
- Selected normalization has zero unresolved tokens.
- The remaining 17 normalization warnings are explicit inline-equation and table-order review markers whose spoken text no longer contains raw LaTeX or unresolved currency and percentage symbols.
- The first model run was interrupted after persisting roughly half the selected WAVs.
- Rerunning the identical command reused valid sidecars, completed synthesis, and continued through all selected ASR checks, demonstrating interruption recovery.
- Three chapter-0003 chunks containing `INPS` were selectively regenerated, and ASR accepted the reviewed target chunk with no reason codes.
- The new target audio is `audio/block-000110.s0000.p0000/87f1513de6c0628a864e3d673b43f26742dacb569075a593284532782002e9a2.wav`.
- The remaining 21 review records are dominated by ASR notation, URL, proper-name, and short-heading mismatches, but they must not be accepted without listening.

## Durable references

- Architecture and stable policy are owned by [`design.md`](design.md).
- Performance evidence and measurement methodology are owned by [`performance.md`](performance.md).
- Milestones and checkpoint criteria are owned by [`implementation.md`](implementation.md).
- Repository working conventions are owned by [`AGENTS.md`](AGENTS.md).

## Next action

- Open the target `reports/listening-checklist.m3u` or follow the `afplay` commands in `reports/listening-checklist.md`.
- Listen to the regenerated `INPS` target chunk and confirm the word pronunciation before accepting it as the replacement.
- Remove the reviewed URL passages from the private source before the final selected-scope rebuild.
- Record an explicit `review-verification` accept or regenerate decision for every flagged chunk.
- Rerun the exact five-chapter `bilbo run` command after review.
- Validate the resulting M4B and build bundle, rerun the command once more to prove no-op reuse, and keep C8 pending until the full listening checklist is approved.
