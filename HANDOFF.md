# Session Handoff

## Current state

- Commit `92eb60a` on `main` restructures the documentation: `design.md`, `implementation.md`, and `performance.md` moved into `docs/`, the README reference material split into eight new `docs/` guides, and README rewritten as a short top-level guide.

- The active branch is `milestone/c8-chapters-2-6`.
- Milestone 8 code and documentation are implemented through commit `77c2719`.
- Repeatable ordered chapter selection, scoped verification merging, multi-chapter assembly, `bilbo run`, text-only qualification, model-license provenance, and atomic content-addressed build bundles are implemented.
- C8 is deliberately scoped to `chapter-0002` through `chapter-0006`, and its automatically validated five-chapter M4B is awaiting final human playback approval.
- The ignored target workspace is `work/c2-target-project/work/tts-investimento/`.
- All 2,819 selected chunks have current Kokoro audio.
- Verification accepted all 2,819 selected chunks with zero retryable or unreviewed records.
- The user explicitly accepted the four narrated URLs, isolated `Oro` title, and context-specific `interesse` defect as known limitations for this C8 build.
- The final media is `media/tts-investimento-chapter-0002-to-chapter-0006.m4b`.
- The reproducible delivery bundle is `deliverables/build-84c9a89d5f3c1df1e3c8613773d9cd2d23a72f29ff6a3638aa69b67daef2be97`.
- The deterministic checklist is `reports/listening-checklist.md`, and the matching 47-item playlist is `reports/listening-checklist.m3u` in the target workspace.
- The existing checklist contains the original 22 flagged chunks and five deterministic accepted samples from each selected chapter, and all flagged decisions are recorded in the verification manifest.
- The user will remove the four narrated URLs from the private source document, so URL omission is intentionally not being implemented as a pipeline rule.
- Source documents are user-owned read-only inputs and must never be edited by an agent.
- The built-in lexicon now pronounces `INPS` as one word while retaining letter-by-letter pronunciation for acronyms such as `ETF`.
- Listening-approved Kokoro overrides now cover `meglio`, `go-kart`, `duemiladiciannove`, `impegnandosi`, and `centoventisette`.
- `interesse` is not globally overridden because ordinary occurrences such as `block-000044.s0000.p0000` sound correct; the defect in `block-000498.s0004.p0000` remains context-specific.
- The two known chapter-0002 Kokoro pause defects remain explicitly accepted limitations as recorded in [`performance.md`](docs/performance.md).
- Chatterbox benchmark and improvement work remains deferred until C8 is accepted.

## Verification

- `.tools/bin/pixi run check` passes formatting, Ruff, strict mypy, 375 ordinary tests, 3 expected hardware skips, and 90.87 percent coverage.
- Opt-in Kokoro and Whisper hardware smoke tests pass with `BILBO_HARDWARE_TESTS=1` and `--no-cov`.
- Text-only qualification reports 752 blocks, 52,111 words, 2,819 chunks, 35 forced splits, 67 length outliers, and an estimated duration of 6:02:36.
- Selected normalization has zero unresolved tokens.
- The 17 normalization warnings are explicit inline-equation and table-order review markers whose spoken text contains no raw LaTeX or unresolved currency and percentage symbols.
- The first model run was interrupted after persisting roughly half the selected WAVs.
- Rerunning the identical command reused valid sidecars, completed synthesis, and continued through all selected ASR checks, demonstrating interruption recovery.
- Three chapter-0003 chunks containing `INPS` were selectively regenerated, and ASR accepted the reviewed target chunk with no reason codes.
- The new target audio is `audio/block-000110.s0000.p0000/87f1513de6c0628a864e3d673b43f26742dacb569075a593284532782002e9a2.wav`.
- The five accepted Kokoro fixes were regenerated selectively; the two still-flagged number and year chunks now carry explicit human accept decisions.
- The 13 listened chunks omitted from the user's problem list now carry explicit human accept decisions.
- The final M4B contains five ordered chapter markers, 2,819 chunks, mono AAC at 24 kHz, and a duration of 21,849.100 seconds.
- Post-encode loudness is -18.04 LUFS with -1.84 dBTP true peak.
- The final M4B SHA-256 is `72831ae0ba835ba2fc0ab361b0722f91124573d106465c1d86238856f12527a1`.
- The build bundle SHA-256 is `84c9a89d5f3c1df1e3c8613773d9cd2d23a72f29ff6a3638aa69b67daef2be97`.
- An exact rerun generated no audio, reused all 2,819 verification records, reused the assembly, and reused the bundle.

## Durable references

- Architecture and stable policy are owned by [`design.md`](docs/design.md).
- Performance evidence and measurement methodology are owned by [`performance.md`](docs/performance.md).
- Milestones and checkpoint criteria are owned by [`implementation.md`](docs/implementation.md).
- Repository working conventions are owned by [`AGENTS.md`](AGENTS.md).

## Next action

- Play the final M4B in an audiobook-capable player.
- Check its beginning and end, all five chapter transitions, chapter seeking and titles, metadata, and representative joins.
- Confirm the six explicitly accepted source or context-specific limitations remain acceptable in the assembled timeline.
- Record final human approval before marking C8 complete.

## TODO

- Optionally remove the narrated URLs represented by `block-000082.s0000.p0000`, `block-000118.s0001.p0000`, `block-000201.s0001.p0000`, and `block-000210.s0000.p0000` in a later user-owned source revision.
- Resolve the accepted final-vowel defect in the isolated `Oro` heading at `block-000301.s0000.p0000` without editing the source document.
- Resolve the accepted context-specific `interesse` defect in `block-000498.s0004.p0000` without adding a global override.
- After user-owned source changes, rerun the selected text pipeline before regenerating or accepting any affected chunks.
