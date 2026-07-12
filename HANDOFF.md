# Session Handoff

## Current state

- The active branch is `main`.
- Milestone 7 assembly is committed as `7c5f369`, with the listening-driven clause-pause and AAC peak-headroom correction as `95a82b6`.
- `bilbo assemble` now validates accepted current generations, streams sample-accurate PCM and configured pauses, creates chapter metadata, runs two-pass FFmpeg loudness normalization with one AAC encode, and validates the result with FFprobe.
- The assembly manifest records exact inputs, commands and tool versions, loudness evidence, chapter ranges, probed metadata, overrides, and the final checksum.
- Full-book and chapter-scoped outputs are idempotent, optional cover art is supported, and missing, failed, corrupt, wrong-format, mixed-rate, stale, or unaccepted inputs block by default.
- The private target book under ignored `work/c2-target-project/` has a newly rebuilt and automatically validated chapter-0002 M4B containing the reviewed pronunciation corrections.
- The shared lexicon corrections, including `aziende`, are committed as `2b68363`; the matching plural Kokoro phoneme override, tests, and design update are intentional uncommitted changes.
- Normalization and chunking have been refreshed, and six chapter-0002 chunks containing `aziende` were regenerated while the other 150 WAVs were reused.
- Chatterbox remains the preferred long-term voice, but its benchmark and improvement work remains deferred until checkpoint C8 is complete.

## Verification

- `.tools/bin/pixi run check` passes formatting, Ruff, strict mypy, 318 ordinary tests, 3 expected hardware skips, and 91.49 percent coverage.
- The plural `aziende` marker is converted to the reviewed voiced `adzjˈɛnde` phoneme sequence.
- Chapter-scoped verification transcribed 26 changed chunks, reused 130 existing results, and accepted all 156 chunks with no retry or review queue.
- Model-free integration tests encode and probe both covered and coverless M4B fixtures and prove unchanged reruns are no-ops.
- The private chapter build includes all 156 accepted chunks with no override and reuses its validated output on rerun.
- The first listening pass found the explicit 250 ms colon pauses slightly too long; colon boundaries now use a distinct 150 ms clause pause without regenerating speech audio.
- Final listening found stable unnatural internal Kokoro pauses in `block-000020.s0009.p0000` and `block-000021.s0007.p0000`; retry seed 1 changed both waveforms but sounded nearly identical.
- Those two known model defects are explicitly accepted for C7 and their resolution is deferred as recorded in [`performance.md`](performance.md).
- The rebuilt chapter M4B is mono AAC at 24 kHz and 64 kbps with one chapter marker and a probed duration of 1351.600 seconds.
- Post-encode loudness is -18.06 LUFS with -2.02 dBTP true peak, within the configured tolerances.
- The rebuilt chapter output SHA-256 is `4b960f5d087a09af7d05050838ccbeb9d4557b2e5a182eebd1f36612991ae0f6`.
- The assembly manifest SHA-256 is `428544b4801a98fffd6bdd2b7569a9f35773eeeac1be39565b02d1a232239e97`, and the verification manifest SHA-256 is `cf6db9852844b1d23009c84e0dd9b1c798eeb77445e8eef87ad6b2a1b2211f89`.

## Durable references

- Architecture and stable policy are owned by [`design.md`](design.md).
- Performance evidence and measurement methodology are owned by [`performance.md`](performance.md).
- Milestones and checkpoint criteria are owned by [`implementation.md`](implementation.md).
- Repository working conventions are owned by [`AGENTS.md`](AGENTS.md).

## Next action

- Checkpoint C7 is accepted; spot-check the rebuilt M4B's plural `aziende` pronunciation before treating this revised media artifact as human-approved.
- Start Milestone 8 full-book qualification while retaining the two deferred Kokoro pause defects as explicit known limitations.
- Keep Chatterbox benchmark and improvement work deferred until after checkpoint C8.
