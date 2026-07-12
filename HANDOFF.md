# Session Handoff

## Current state

- The active branch is `milestone/c6-calibrated-verification`.
- Milestone 6 implementation is committed as `4daacde`, its original handoff as `b51c68d`, and listening-driven corrections as `cc2097d`.
- The reusable pinned MLX-Whisper adapter, deterministic alignment and audio heuristics, process-isolated retry coordinator, generation-bound manual decisions, manifests, and readable reports are implemented.
- The public `bilbo verify` command runs ASR and TTS retries in non-overlapping Pixi child processes.
- The private target book under ignored `work/c2-target-project/` has an explicit calibrated `verification` section and generated verification evidence.
- Human listening can explicitly regenerate an automatically accepted chunk when ASR misses a pronunciation or acoustic defect.
- The reviewed Kokoro `zero` correction uses a unique lexicon marker and the accepted `dzˈɛro` phoneme sequence after G2P.
- Chatterbox remains the preferred long-term voice, but its benchmark and improvement work is explicitly deferred until checkpoint C8 is complete.

## Verification

- `.tools/bin/pixi run check` passes formatting, Ruff, strict mypy, 300 ordinary tests, 3 expected hardware skips, and 91.82 percent coverage.
- The opt-in MLX-Whisper hardware smoke test passes in the `asr` environment with unrestricted Metal access.
- The existing 24-excerpt Kokoro regression evidence calibrates WER at `0.70` and CER at `0.85` so correct spoken numbers rendered as digits do not become false positives.
- Deliberate truncation, repetition, silence, clipping, speed changes, retry exhaustion, process ordering, stale decisions, and no-op reruns are covered by committed tests.
- Listening review covered the ten highest-risk ASR and audio outliers.
- The `zero` candidate using contiguous `dz` phonemes was accepted; the final pipeline WAV differs from that listening candidate by at most one PCM quantization unit.
- Regenerating the uncertain tail on `block-000031.s0002.p0000` produced perceptually identical audio, confirming Kokoro is effectively deterministic for that request.
- The final calibrated `chapter-0002` pass classified all 156 listening-approved chunks as `accepted`, with 0 `retryable` and 0 `review`.
- The final verification manifest SHA-256 is `c88cca038060f8dc0bbcbdfaeb243ec9bcd81cfa7872ebc51f9bb11b390a4552` and report SHA-256 is `55cf76b84a90a260c2c3744653be221906006febd67b1b747861ffa395ec7373`.
- The first calibration pass exposed and corrected false positives from one-word heading speed and non-adjacent word frequency; the final repetition heuristic detects only adjacent repeated phrases.

## Durable references

- Architecture and stable policy are owned by [`design.md`](design.md).
- Performance evidence and measurement methodology are owned by [`performance.md`](performance.md).
- Milestones and checkpoint criteria are owned by [`implementation.md`](implementation.md).
- Repository working conventions are owned by [`AGENTS.md`](AGENTS.md).

## Next action

- Checkpoint C6 is accepted.
- Start Milestone 7 assembly from the 156 accepted Kokoro chunks.
- Keep Chatterbox benchmark and improvement work deferred until after checkpoint C8.
