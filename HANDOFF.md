# Session Handoff

## Current state

- The active branch is `milestone/c6-calibrated-verification`.
- Milestone 6 implementation is committed as `4daacde` (`feat: add calibrated round-trip verification`), with this handoff committed separately for the final branch push.
- The reusable pinned MLX-Whisper adapter, deterministic alignment and audio heuristics, process-isolated retry coordinator, generation-bound manual decisions, manifests, and readable reports are implemented.
- The public `bilbo verify` command runs ASR and TTS retries in non-overlapping Pixi child processes.
- The private target book under ignored `work/c2-target-project/` has an explicit calibrated `verification` section and generated verification evidence.
- The regenerated `chapter-0002` chunks were listening-checked and confirmed correct before C6 calibration.
- Chatterbox remains the preferred long-term voice, but its benchmark and improvement work is explicitly deferred until checkpoint C8 is complete.

## Verification

- `.tools/bin/pixi run check` passes formatting, Ruff, strict mypy, 297 ordinary tests, 3 expected hardware skips, and 91.84 percent coverage.
- The opt-in MLX-Whisper hardware smoke test passes in the `asr` environment with unrestricted Metal access.
- The existing 24-excerpt Kokoro regression evidence calibrates WER at `0.70` and CER at `0.85` so correct spoken numbers rendered as digits do not become false positives.
- Deliberate truncation, repetition, silence, clipping, speed changes, retry exhaustion, process ordering, stale decisions, and no-op reruns are covered by committed tests.
- The calibrated `chapter-0002` pass classified all 156 listening-approved chunks as `accepted`, with 0 `retryable` and 0 `review`.
- The public process-isolated rerun reused all 156 attempt records, performed 0 transcriptions, and reproduced manifest SHA-256 `dd70437cf9d530fc25a8dfe34c80da6e63b0eb6245d9a859fb32eadc9cd72e70` and report SHA-256 `460b8e20fecaae4f427fd81c9d6b2fa9d4800dd541b341de12077caba309bbb3`.
- The first calibration pass exposed and corrected false positives from one-word heading speed and non-adjacent word frequency; the final repetition heuristic detects only adjacent repeated phrases.

## Durable references

- Architecture and stable policy are owned by [`design.md`](design.md).
- Performance evidence and measurement methodology are owned by [`performance.md`](performance.md).
- Milestones and checkpoint criteria are owned by [`implementation.md`](implementation.md).
- Repository working conventions are owned by [`AGENTS.md`](AGENTS.md).

## Next action

- Review and explicitly accept the calibrated threshold behavior to close checkpoint C6.
- After C6 approval, start Milestone 7 assembly from the 156 accepted Kokoro chunks.
- Keep Chatterbox benchmark and improvement work deferred until after checkpoint C8.
