# Session Handoff

## Current state

- The active branch is `milestone/c5-resumable-synthesis` with a clean working tree; the branch is not yet pushed.
- The listening-review fixes are committed: the reviewed `desidèri` and `tròvano` lexicon entries and the opt-in `chunking.split_at_colons` feature.
- Colon splitting exists because Kokoro renders a colon pause near 80 ms regardless of punctuation choice, so the following clause now receives the explicit assembly sentence pause.
- Stale superseded audio pairs were purged from the private workspace, leaving exactly one WAV and sidecar per chunk directory.
- The timing tool now runs counterbalanced ABBA or BAAB sessions with one fresh subprocess per pass, persists versioned JSONL evidence and metadata, summarizes only complete paired thermal sessions, and offers a separate cProfile and MPS-signpost mode.
- The performance methodology now distinguishes benchmark evidence from perturbed profiling, uses same-text wall time as the primary result, treats RTF separately, alternates starting order across cool sessions, and records the limitations of the historical measurements.
- `book.yaml` selects one candidate file through `synthesis.model_config_path` instead of duplicating engine, revision, voice, and settings; the candidate owns the complete pinned identity.
- The interim production default is the Kokoro `kokoro-nicola-s120` candidate (voice `im_nicola`, speed 1.2) because Chatterbox throughput varies with excerpt length and thermal state but remains impractical for full-book iteration; [`performance.md`](performance.md) owns the evidence and its limitations.
- Chatterbox remains the preferred voice and long-term target while its performance investigation continues in parallel.
- The private target book under ignored `work/c2-target-project/` uses the shared `config/lexicons/kokoro-it.yaml` overlay and the interim Kokoro candidate.

## Verification

- `.tools/bin/pixi run check` passes formatting, Ruff, strict mypy, and all 264 ordinary tests with 3 expected hardware skips and above 92 percent coverage.
- Chapter `chapter-0002` regenerated after the listening fixes: 156 chunks after colon splitting, 79 unchanged chunks reused from cache, 77 generated, 0 failures.
- A rerun after the stale-audio purge remains a no-op: 0 generated, 156 skipped, byte-identical generation manifest.
- Interruption recovery, corrupt-output detection, and lexicon-scoped regeneration are covered by committed tests.
- The earlier partial Chatterbox audio is preserved at `work/c2-target-project/work/tts-investimento/audio-chatterbox-incomplete/`.
- Human listening accepted the chapter overall and flagged `desideri`, `trovano`, and short colon pauses; the seven reviewed Kokoro corrections now apply 48 times across the private book.
- ASR scoring of `kokoro-nicola-s120` measured weighted WER 0.183288 and CER 0.186090 with regressions limited to English loanwords.

## Durable references

- Architecture and stable policy are owned by [`design.md`](design.md).
- Performance evidence and measurement methodology are owned by [`performance.md`](performance.md).
- Milestones and checkpoint criteria are owned by [`implementation.md`](implementation.md).
- Repository working conventions are owned by [`AGENTS.md`](AGENTS.md).

## Next action

- Spot-check the regenerated chapter `chapter-0002` chunks for the corrected words, remembering that colon pauses become audible only in assembled audio.
- When audio generation is authorized for benchmarking, collect one cool `ABBA` and one independent cool `BAAB` session into the same evidence file, then summarize the complete paired sessions.
- Push the reviewed branch and start Milestone 6, the round-trip ASR verification loop, against the Kokoro-generated chunks.
