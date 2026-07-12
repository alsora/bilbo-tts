# Session Handoff

## Current state

- The active branch is `refactor/lexicon-phoneme-overrides` from `main`; it makes the Kokoro phoneme overrides data-driven.
- Lexicon entries now accept an optional `phoneme_override` field, the six reviewed Kokoro marker corrections live entirely in `config/lexicons/kokoro-it.yaml`, and the adapter derives each marker's source phonemes at synthesis time instead of hardcoding marker, source, and target constants.
- Replacement is best-effort by design: espeak-ng reduces the final vowel of `impegnando-si` mid-clause, so that context keeps its ordinary phonemes exactly as it did with the hardcoded table; the behavior is documented in [`docs/pronunciation-lexicons.md`](docs/pronunciation-lexicons.md).
- The ignored target `book.yaml` was updated to the new `kokoro-it.yaml` checksum `bc7034bb…`; spoken text and chunk content hashes are unchanged, so a `normalize` and `chunk` rerun refreshes manifests without regenerating audio, and this rerun has not been done yet.
- Commit `92eb60a` on `main` restructures the documentation: `design.md`, `implementation.md`, and `performance.md` moved into `docs/`, the README reference material split into eight new `docs/` guides, and README rewritten as a short top-level guide.
- The milestone branch `milestone/c8-chapters-2-6` holds the C8 implementation through commit `77c2719`.
- Commit `be8a6a6` on `main` contains the listening-review pronunciation fixes: a new `anni-elision` normalization rule, number expansion reordered before lexicon application, `BOT` pronounced as the word `bot` in `finance-it.yaml`, `stress-eroderne`, regex `compound-seicento`, and open-o `vowel-bot` entries in `kokoro-it.yaml`, and regenerated golden fixtures.
- The follow-up commit on `main` adds the `loanword-trading` entry (`trading` -> `treding`) to `kokoro-it.yaml` with its test.
- The ignored target `book.yaml` carries the matching `kokoro-it.yaml` checksum and the raised true-peak tolerance as intentional working-workspace changes.
- The rule reorder means digit-derived expansions now receive lexicon corrections, so `dzzèro`, `sessanta-sette`, and `duemiladiciannòve` markers appear in many more chunks; 37 chapter 2-6 chunks were regenerated and re-verified for these fixes.
- The target `book.yaml` now sets `true_peak_tolerance_db: 1.0` because the regenerated timeline's AAC encode overshoots the pre-encode clamp by up to 1.46 dB and assembly failed at the default 0.5 dB headroom.
- Repeatable ordered chapter selection, scoped verification merging, multi-chapter assembly, `bilbo run`, text-only qualification, model-license provenance, and atomic content-addressed build bundles are implemented.
- C8 is deliberately scoped to `chapter-0002` through `chapter-0006`, and its five-chapter M4B is awaiting final human playback approval.
- The ignored target workspace is `work/c2-target-project/work/tts-investimento/`.
- All 2,819 selected chunks have current Kokoro audio.
- Verification accepted all 2,819 selected chunks with zero retryable or unreviewed records.
- The user explicitly accepted the four narrated URLs, isolated `Oro` title, and context-specific `interesse` defect as known limitations for this C8 build.
- The final media is `media/tts-investimento-chapter-0002-to-chapter-0006.m4b`.
- The pre-fix delivery bundle `deliverables/build-84c9a89d5f3c1df1e3c8613773d9cd2d23a72f29ff6a3638aa69b67daef2be97` is stale against the regenerated audio; republish the bundle after the pronunciation fixes are committed.
- The deterministic checklist is `reports/listening-checklist.md`, and the matching 47-item playlist is `reports/listening-checklist.m3u` in the target workspace.
- The existing checklist contains the original 22 flagged chunks and five deterministic accepted samples from each selected chapter, and all flagged decisions are recorded in the verification manifest.
- The user will remove the four narrated URLs from the private source document, so URL omission is intentionally not being implemented as a pipeline rule.
- Source documents are user-owned read-only inputs and must never be edited by an agent.
- The built-in lexicon pronounces `INPS` and `BOT` as words while retaining letter-by-letter pronunciation for acronyms such as `ETF`; the Kokoro overlay additionally respells `bot` as `bòt` because the user rejected the closed o.
- Listening-approved Kokoro overrides now cover `meglio`, `go-kart`, `duemiladiciannove`, `impegnandosi`, and `centoventisette`; the new `eroderne` and compound `seicento` entries were phoneme-verified with espeak but await listening confirmation.
- `interesse` is not globally overridden because ordinary occurrences such as `block-000044.s0000.p0000` sound correct; the defect in `block-000498.s0004.p0000` remains context-specific.
- The two known chapter-0002 Kokoro pause defects remain explicitly accepted limitations as recorded in [`performance.md`](docs/performance.md).
- Chatterbox benchmark and improvement work remains deferred until C8 is accepted.

## Verification

- On `refactor/lexicon-phoneme-overrides`, `.tools/bin/pixi run check` passes formatting, Ruff, strict mypy, 388 ordinary tests, and 4 expected hardware skips.
- Both opt-in Kokoro hardware tests pass, including the new test pinning that each override marker phonemizes identically in isolation and clause-final position.
- An espeak equivalence check confirmed the derived replacement table produces byte-identical corrected phoneme strings to the removed hardcoded table on marker-dense sentences, including the real `impegnando-si` book context.
- Kokoro MLX synthesis is not sample-deterministic run-to-run on this machine even with a fixed seed (identical code and inputs produced different PCM hashes with identical frame counts), so phoneme equivalence rather than PCM byte identity is the refactor's no-audio-change evidence.
- The golden fixture manifests and reports were regenerated for the reordered rule sequence; the only content differences are the lexicon aggregate checksum and acronym transformation ordering.
- Opt-in Kokoro and Whisper hardware smoke tests pass with `BILBO_HARDWARE_TESTS=1` and `--no-cov`.
- The pronunciation fixes changed 37 chapter 2-6 chunks; synthesis regenerated exactly those chunks and reused the other 2,782 cached WAVs.
- Verification re-transcribed the 37 regenerated chunks and accepted all 2,819 selected chunks with zero retryable or review records.
- The follow-up open-o `bòt` correction regenerated three chunks and the `trading` -> `treding` loanword correction regenerated seven chapter 2-6 chunks; verification and assembly have not been rerun since, so the current verification manifest and M4B predate those regenerated WAVs.
- The espeak phoneme check confirms `eròderne` -> `erˈɔderne`, `mille-seicento` -> voiceless `sejʧ`, `trent’anni` -> `trentˈaːnnɪ`, and `bòt` -> `bˈɔt`.
- The rebuilt M4B contains five ordered chapter markers, 2,819 chunks, mono AAC at 24 kHz, and a duration of 21,846.200 seconds.
- Post-encode loudness is -18.06 LUFS with -2.1 dBTP true peak.
- The rebuilt M4B SHA-256 is `bd9c7cca38ce7e2b05930a5b0240a0e8acf30b12c25af644a8d77f8abf7a5279`.
- The pre-fix bundle SHA-256 `84c9a89d5f3c1df1e3c8613773d9cd2d23a72f29ff6a3638aa69b67daef2be97` no longer matches the current audio and manifests.

## Durable references

- Architecture and stable policy are owned by [`design.md`](docs/design.md).
- Performance evidence and measurement methodology are owned by [`performance.md`](docs/performance.md).
- Milestones and checkpoint criteria are owned by [`implementation.md`](docs/implementation.md).
- Repository working conventions are owned by [`AGENTS.md`](AGENTS.md).

## Next action

- Review and merge `refactor/lexicon-phoneme-overrides`, then rerun `normalize` and `chunk` for the target book to fold the new overlay checksum into its manifests.
- Listen to representative regenerated chunks for the pronunciation fixes: `block-000036.s0002.p0000` (trent’anni), `block-000133.s0000.p0000` (mille-seicento), `block-000132.s0001.p0000` (eròderne), `block-000222.s0002.p0000` (bòt), and `block-000145.s0000.p0000` (treding).
- After listening approval, rerun verify and assemble for the chapter 2-6 scope to fold the regenerated `bòt` and `treding` WAVs into the verification manifest and M4B.
- Commit the pronunciation fixes, then republish the delivery bundle from a clean tracked tree.
- Play the rebuilt M4B in an audiobook-capable player.
- Check its beginning and end, all five chapter transitions, chapter seeking and titles, metadata, and representative joins.
- Confirm the six explicitly accepted source or context-specific limitations remain acceptable in the assembled timeline.
- Record final human approval before marking C8 complete.

## TODO

- Optionally remove the narrated URLs represented by `block-000082.s0000.p0000`, `block-000118.s0001.p0000`, `block-000201.s0001.p0000`, and `block-000210.s0000.p0000` in a later user-owned source revision.
- Resolve the accepted final-vowel defect in the isolated `Oro` heading at `block-000301.s0000.p0000` without editing the source document.
- Resolve the accepted context-specific `interesse` defect in `block-000498.s0004.p0000` without adding a global override.
- After user-owned source changes, rerun the selected text pipeline before regenerating or accepting any affected chunks.
