# Session Handoff

## Current state

- The active branch is `milestone/c7-m4b-assembly`.
- Milestone 7 assembly is committed as `7c5f369`.
- `bilbo assemble` now validates accepted current generations, streams sample-accurate PCM and configured pauses, creates chapter metadata, runs two-pass FFmpeg loudness normalization with one AAC encode, and validates the result with FFprobe.
- The assembly manifest records exact inputs, commands and tool versions, loudness evidence, chapter ranges, probed metadata, overrides, and the final checksum.
- Full-book and chapter-scoped outputs are idempotent, optional cover art is supported, and missing, failed, corrupt, wrong-format, mixed-rate, stale, or unaccepted inputs block by default.
- The private target book under ignored `work/c2-target-project/` has a validated chapter-0002 M4B ready for the checkpoint listening review.
- Chatterbox remains the preferred long-term voice, but its benchmark and improvement work remains deferred until checkpoint C8 is complete.

## Verification

- `.tools/bin/pixi run check` passes formatting, Ruff, strict mypy, 316 ordinary tests, 3 expected hardware skips, and 91.46 percent coverage.
- Model-free integration tests encode and probe both covered and coverless M4B fixtures and prove unchanged reruns are no-ops.
- The private chapter build includes all 156 accepted chunks with no override and reuses its validated output on rerun.
- The chapter M4B is mono AAC at 24 kHz and 64 kbps with one chapter marker and a probed duration of 1354.200 seconds.
- Post-encode loudness is -18.05 LUFS with -1.59 dBTP true peak, within the configured -18.0 ± 0.5 LU and -2.0 + 0.5 dB tolerances.
- The chapter output SHA-256 is `424ae2fabcef759b2add7e4035adaa7faaaf90a2ea494b50e355e84501679404`.
- The assembly manifest SHA-256 is `e23a17289af33e8212e5724928c02ae5b855b459235309ad45c9729e0e6182a0`, and the report SHA-256 is `99af44e4a5fdab6494f4313bb98f1e301e4778a2fc8441a12345546e182663cf`.
- The C7 listening checkpoint is still pending and must not be described as accepted.

## Durable references

- Architecture and stable policy are owned by [`design.md`](design.md).
- Performance evidence and measurement methodology are owned by [`performance.md`](performance.md).
- Milestones and checkpoint criteria are owned by [`implementation.md`](implementation.md).
- Repository working conventions are owned by [`AGENTS.md`](AGENTS.md).

## Next action

- Open `work/c2-target-project/work/tts-investimento/media/tts-investimento-chapter-0002.m4b` in an audiobook-capable player.
- Listen through the start, end, every structural transition, and representative joins, and confirm metadata and seeking.
- Record the human result; only then mark checkpoint C7 accepted and proceed to Milestone 8.
