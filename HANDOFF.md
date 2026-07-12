# Session Handoff

## Current state

- The active branch is `milestone/c7-m4b-assembly`.
- Milestone 7 assembly is committed as `7c5f369`, with the listening-driven clause-pause and AAC peak-headroom correction as `95a82b6`.
- `bilbo assemble` now validates accepted current generations, streams sample-accurate PCM and configured pauses, creates chapter metadata, runs two-pass FFmpeg loudness normalization with one AAC encode, and validates the result with FFprobe.
- The assembly manifest records exact inputs, commands and tool versions, loudness evidence, chapter ranges, probed metadata, overrides, and the final checksum.
- Full-book and chapter-scoped outputs are idempotent, optional cover art is supported, and missing, failed, corrupt, wrong-format, mixed-rate, stale, or unaccepted inputs block by default.
- The private target book under ignored `work/c2-target-project/` has a validated chapter-0002 M4B ready for the checkpoint listening review.
- Chatterbox remains the preferred long-term voice, but its benchmark and improvement work remains deferred until checkpoint C8 is complete.

## Verification

- `.tools/bin/pixi run check` passes formatting, Ruff, strict mypy, 316 ordinary tests, 3 expected hardware skips, and 91.47 percent coverage.
- Model-free integration tests encode and probe both covered and coverless M4B fixtures and prove unchanged reruns are no-ops.
- The private chapter build includes all 156 accepted chunks with no override and reuses its validated output on rerun.
- The first listening pass found the explicit 250 ms colon pauses slightly too long; colon boundaries now use a distinct 150 ms clause pause without regenerating speech audio.
- The revised chapter M4B is mono AAC at 24 kHz and 64 kbps with one chapter marker and a probed duration of 1351.600 seconds.
- Post-encode loudness is -18.05 LUFS with -2.08 dBTP true peak, within the configured -18.0 ± 0.5 LU and -2.0 + 0.5 dB tolerances.
- The revised chapter output SHA-256 is `037e6a87c8f88bcd114f9e489ed5ccf074b78109ac64883ee5bef0bf71ec39ed`.
- The revised assembly manifest SHA-256 is `f759de19030f76a5168e0cbb450bb9f0696a53a037ce1432b241299ac5473bab`, and the report SHA-256 is `27242f744335c0fdd725e65aa3d2021a63cebd4dafa53ba12344af14bd259115`.
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
