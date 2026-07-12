# Session Handoff

## Current state

- The active branch is `milestone/c5-resumable-synthesis` at commit `ded41ff`; the branch is not yet pushed.
- The working tree contains uncommitted A/B timing-tool and performance-methodology changes in `README.md`, `design.md`, `performance.md`, `scripts/ab_timing.py`, `src/bilbo_tts/benchmarking.py`, and `tests/test_ab_timing.py`.
- A separate uncommitted change exists in `config/lexicons/kokoro-it.yaml`; it was not made or reviewed during the timing-tool session.
- The timing tool now runs counterbalanced ABBA or BAAB sessions with one fresh subprocess per pass, persists versioned JSONL evidence and metadata, summarizes only complete paired thermal sessions, and offers a separate cProfile and MPS-signpost mode.
- The performance methodology now distinguishes benchmark evidence from perturbed profiling, uses same-text wall time as the primary result, treats RTF separately, alternates starting order across cool sessions, and records the limitations of the historical measurements.
- `book.yaml` selects one candidate file through `synthesis.model_config_path` instead of duplicating engine, revision, voice, and settings; the candidate owns the complete pinned identity.
- The interim production default is the Kokoro `kokoro-nicola-s120` candidate (voice `im_nicola`, speed 1.2) because Chatterbox throughput varies with excerpt length and thermal state but remains impractical for full-book iteration; [`performance.md`](performance.md) owns the evidence and its limitations.
- Chatterbox remains the preferred voice and long-term target while its performance investigation continues in parallel.
- The private target book under ignored `work/c2-target-project/` uses the shared `config/lexicons/kokoro-it.yaml` overlay and the interim Kokoro candidate.

## Verification

- `.tools/bin/pixi run check` passes formatting, Ruff, strict mypy, and all 262 ordinary tests with 3 expected hardware skips and 92.07 percent coverage.
- Focused benchmark-tool tests pass: 4 tests in `tests/test_ab_timing.py`.
- The public `compare`, `summarize`, and `profile` command help paths load successfully.
- No TTS model inference or audio generation was run while implementing or verifying the tooling.
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

- Review and commit the uncommitted timing-tool slice separately from the unrelated lexicon edit.
- When audio generation is authorized, collect one cool `ABBA` and one independent cool `BAAB` session into the same evidence file, then summarize the complete paired sessions.
- Listen to the generated chapter `chapter-0002` audio and record acceptance or corrections as the human portion of checkpoint C5.
- Push the reviewed branch and start Milestone 6, the round-trip ASR verification loop, against the Kokoro-generated chunks.
