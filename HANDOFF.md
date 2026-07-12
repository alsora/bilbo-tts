# Session Handoff

## Current state

- The active branch is `milestone/c5-resumable-synthesis` at commit `4ee21b6` plus intentional uncommitted working-tree changes described below.
- Resumable synthesis, the Kokoro pronunciation lexicon, the Chatterbox speed experiments, and the performance investigation are committed on this branch.
- The interim production default is the Kokoro `kokoro-nicola-s120` candidate (voice `im_nicola`, speed 1.2) because Chatterbox renders near real-time factor 4 to 5; [`performance.md`](performance.md) owns the evidence.
- Chatterbox remains the preferred voice and long-term target while its performance investigation continues in parallel.
- The private target book under ignored `work/c2-target-project/` uses the shared `config/lexicons/kokoro-it.yaml` overlay and the interim Kokoro candidate.

## Uncommitted working-tree changes

- `book.yaml` now selects one candidate file through `synthesis.model_config_path` instead of duplicating engine, revision, voice, and settings; the candidate owns the complete pinned identity.
- `resolve_book_candidate` loads the configured repository-relative candidate path, and chunk cache identities take voice and settings from the candidate.
- `config/qualification/fake.yaml` is committed data mirroring the in-code fake candidate, with a test pinning their equivalence.
- Test fixtures, unit tests, README, and `design.md` are updated for the new synthesis layout and the interim Kokoro default decision.

## Verification

- `.tools/bin/pixi run check` passes formatting, Ruff, strict mypy, and all 258 tests with 3 expected hardware skips and 92.12 percent coverage.
- Chapter `chapter-0002` of the private book synthesized completely with Kokoro: 133 of 133 chunks, 0 failures, 21.6 minutes of audio in roughly 139 seconds of wall time.
- The earlier partial Chatterbox audio is preserved at `work/c2-target-project/work/tts-investimento/audio-chatterbox-incomplete/`.
- Human listening this session preferred `im_nicola` at speed 1.2 over `if_sara`, and ASR scoring of `kokoro-nicola-s120` measured weighted WER 0.183288 and CER 0.186090 with regressions limited to English loanwords.
- The five reviewed Kokoro pronunciation corrections in `config/lexicons/kokoro-it.yaml` apply 21 times across the private book.

## Durable references

- Architecture and stable policy are owned by [`design.md`](design.md).
- Performance evidence and measurement methodology are owned by [`performance.md`](performance.md).
- Milestones and checkpoint criteria are owned by [`implementation.md`](implementation.md).
- Repository working conventions are owned by [`AGENTS.md`](AGENTS.md).

## Next action

- Listen to the generated chapter `chapter-0002` audio and record acceptance or corrections.
- Commit the model-config-path slice and the interim-default documentation once reviewed.
- Continue Milestone 5 verification work (ASR verify stage) against the Kokoro-generated chunks.
