# Session Handoff

## Current state

- The active branch is `milestone/c7-m4b-assembly`.
- Milestone 7 assembly is committed as `7c5f369`, with the listening-driven clause-pause and AAC peak-headroom correction as `95a82b6`.
- `bilbo assemble` now validates accepted current generations, streams sample-accurate PCM and configured pauses, creates chapter metadata, runs two-pass FFmpeg loudness normalization with one AAC encode, and validates the result with FFprobe.
- The assembly manifest records exact inputs, commands and tool versions, loudness evidence, chapter ranges, probed metadata, overrides, and the final checksum.
- Full-book and chapter-scoped outputs are idempotent, optional cover art is supported, and missing, failed, corrupt, wrong-format, mixed-rate, stale, or unaccepted inputs block by default.
- The private target book under ignored `work/c2-target-project/` has a validated chapter-0002 M4B, and checkpoint C7 is accepted.
- Nine additional Kokoro pronunciation corrections are present as intentional uncommitted changes in `config/lexicons/kokoro-it.yaml`, with regression coverage in `tests/test_normalization.py`; the ignored target-book configuration pins the new lexicon checksum.
- Normalization and chunking have been refreshed, the 20 affected chapter-0002 WAV chunks have been regenerated, and the Wall Street and azienda chunks have received a second listening-driven regeneration; the previous verification and M4B artifacts are now stale.
- Chatterbox remains the preferred long-term voice, but its benchmark and improvement work remains deferred until checkpoint C8 is complete.

## Verification

- `.tools/bin/pixi run check` passes formatting, Ruff, strict mypy, 317 ordinary tests, 3 expected hardware skips, and 91.48 percent coverage.
- Direct espeak-ng probes produce the intended phonemes for all nine new respellings.
- Chapter-scoped synthesis generated 20 corrected WAVs, reused 136 unchanged WAVs, reported no failures, and an immediate rerun reused all 156 chunks.
- The second pronunciation pass generated only the two revised Wall Street and azienda chunks and reused the other 154 chapter chunks without failures.
- Model-free integration tests encode and probe both covered and coverless M4B fixtures and prove unchanged reruns are no-ops.
- The private chapter build includes all 156 accepted chunks with no override and reuses its validated output on rerun.
- The first listening pass found the explicit 250 ms colon pauses slightly too long; colon boundaries now use a distinct 150 ms clause pause without regenerating speech audio.
- Final listening found stable unnatural internal Kokoro pauses in `block-000020.s0009.p0000` and `block-000021.s0007.p0000`; retry seed 1 changed both waveforms but sounded nearly identical.
- Those two known model defects are explicitly accepted for C7 and their resolution is deferred as recorded in [`performance.md`](performance.md).
- The accepted chapter M4B is mono AAC at 24 kHz and 64 kbps with one chapter marker and a probed duration of 1351.600 seconds.
- Post-encode loudness is -18.05 LUFS with -2.08 dBTP true peak, within the configured -18.0 ± 0.5 LU and -2.0 + 0.5 dB tolerances.
- The accepted chapter output SHA-256 is `dcf3a1d1146c4388338fdf8edee8d0f29d5407532e0a3ce028b442819358c53c`.
- The accepted assembly manifest SHA-256 is `78a79f99d3eb2aaa27ffc08b9ac7aa3e2131afe9032856813d0579147115cf55`, and the report SHA-256 is `ecc6032ef0ac07e781f4bcf6db23ab10f95ad1ae2129ae3fca5792b11011a636`.
- The final verification manifest SHA-256 after both retries is `6f2fcb1a9f7ee3193db4d9df923e3421e366bd900ab30e00376f792ab8f906d6`.

## Durable references

- Architecture and stable policy are owned by [`design.md`](design.md).
- Performance evidence and measurement methodology are owned by [`performance.md`](performance.md).
- Milestones and checkpoint criteria are owned by [`implementation.md`](implementation.md).
- Repository working conventions are owned by [`AGENTS.md`](AGENTS.md).

## Next action

- Checkpoint C7 is accepted.
- Listen to the second-pass Wall Street and azienda WAVs identified in the current session, then rerun chapter-0002 verification and assembly if the pronunciations are accepted.
- Start Milestone 8 full-book qualification while retaining the two deferred Kokoro pause defects as explicit known limitations.
- Keep Chatterbox benchmark and improvement work deferred until after checkpoint C8.
