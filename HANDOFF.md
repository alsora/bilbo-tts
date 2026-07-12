# Session Handoff

## Current state

- The active branch is `milestone/c5-resumable-synthesis` at commit `3919ba0` with a clean working tree; the branch is not yet pushed.
- Resumable synthesis, the Kokoro pronunciation lexicon, the Chatterbox speed experiments, the performance investigation, and the model-config-path book layout are committed on this branch.
- `book.yaml` selects one candidate file through `synthesis.model_config_path` instead of duplicating engine, revision, voice, and settings; the candidate owns the complete pinned identity.
- The interim production default is the Kokoro `kokoro-nicola-s120` candidate (voice `im_nicola`, speed 1.2) because Chatterbox renders near real-time factor 4 to 5; [`performance.md`](performance.md) owns the evidence.
- Chatterbox remains the preferred voice and long-term target while its performance investigation continues in parallel.
- The private target book under ignored `work/c2-target-project/` uses the shared `config/lexicons/kokoro-it.yaml` overlay and the interim Kokoro candidate.

## Verification

- `.tools/bin/pixi run check` passes formatting, Ruff, strict mypy, and all 258 tests with 3 expected hardware skips and 92.12 percent coverage.
- Chapter `chapter-0002` of the private book synthesized completely with Kokoro: 133 of 133 chunks, 0 failures, 21.6 minutes of audio in roughly 139 seconds of wall time.
- An immediate rerun of the same chapter command was a no-op: 0 generated, 133 skipped, byte-identical generation manifest, no model load.
- Interruption recovery, corrupt-output detection, and lexicon-scoped regeneration are covered by the committed unit and integration tests.
- The earlier partial Chatterbox audio is preserved at `work/c2-target-project/work/tts-investimento/audio-chatterbox-incomplete/`.
- Human listening this session preferred `im_nicola` at speed 1.2 over `if_sara`, and ASR scoring of `kokoro-nicola-s120` measured weighted WER 0.183288 and CER 0.186090 with regressions limited to English loanwords.
- The five reviewed Kokoro pronunciation corrections in `config/lexicons/kokoro-it.yaml` apply 21 times across the private book.

## Durable references

- Architecture and stable policy are owned by [`design.md`](design.md).
- Performance evidence and measurement methodology are owned by [`performance.md`](performance.md).
- Milestones and checkpoint criteria are owned by [`implementation.md`](implementation.md).
- Repository working conventions are owned by [`AGENTS.md`](AGENTS.md).

## Next action

- Listen to the generated chapter `chapter-0002` audio and record acceptance or corrections as the human portion of checkpoint C5.
- Push the reviewed branch and start Milestone 6, the round-trip ASR verification loop, against the Kokoro-generated chunks.
