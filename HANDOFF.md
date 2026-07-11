# Session Handoff

## Current state

- The active branch is `milestone/c4-tts-qualification`; its implementation head before this handoff is `4cee05d`.
- Checkpoint C3 is approved after human review of chapter 2 extraction, normalization, and chunking.
- The private target source and generated reports remain only under ignored `work/c2-target-project/`.
- Milestone 4 implementation commits are `8f24bb2`, `4f9340d`, and `4cee05d`.
- Generated model caches, WAV files, qualification results, and ASR evidence remain under ignored `work/`.
- The branch is not pushed because the required complete Chatterbox corpus check failed.

## Completed work

- Added strict TTS contracts, shared validation, a dependency-free deterministic fake engine, and an explicit lazy factory.
- Added the reviewed 24-excerpt Italian qualification corpus and pinned Chatterbox, Kokoro, and ASR candidate configurations.
- Added independent qualification WAV generation, canonical result contracts, compact reports, macOS peak RSS recording, and per-sample failure continuation.
- Added deterministic blind-listening package generation with opaque WAV identifiers and a separate private mapping.
- Added lazy immutable Chatterbox V3 PyTorch MPS and Kokoro MLX adapters with opt-in hardware tests.
- Added minimal separate-process MLX-Whisper scoring with deterministic comparison normalization and weighted WER and CER evidence.
- Added `qualify-tts`, `prepare-tts-listening`, and `score-tts-asr` commands.
- Added exact isolated model dependencies and regenerated `pixi.lock`.

## Verification

- `.tools/bin/pixi run check` passes formatting, Ruff, strict mypy, all 205 tests, 3 expected hardware skips, and 91.84 percent coverage.
- Locked installation succeeds for the `chatterbox`, `kokoro`, and `asr` environments.
- The Chatterbox hardware smoke test passes in 242.10 seconds.
- The complete Chatterbox corpus is partial with 23 successes and one `long-01` MPS failure: `Output channels > 65536 not supported at the MPS device`.
- The Chatterbox run records 900.47 seconds generation time, 124.96 seconds valid audio, and 4.93 GB process peak RSS.
- The Kokoro hardware smoke test passes in 16.26 seconds.
- Kokoro completes all 24 excerpts in 25.15 seconds for 161.40 seconds of audio with 963.92 MB process peak RSS.
- The MLX-Whisper hardware smoke test passes in 69.18 seconds.
- MLX-Whisper scores all 24 Kokoro excerpts with weighted WER 0.161725 and CER 0.182331.

## Durable references

- Architecture and stable policy are owned by [`design.md`](design.md).
- Milestones and checkpoint criteria are owned by [`implementation.md`](implementation.md).
- The next-session C4 execution plan is [`milestone-4-plan.md`](milestone-4-plan.md).
- Repository working conventions are owned by [`AGENTS.md`](AGENTS.md).

## Next action

- Decide whether the reproducible Chatterbox MPS long-input failure disqualifies the candidate or warrants a separately reviewed backend or input-limit change.
- Do not shorten the fixed corpus or hide the failure without an explicit qualification decision.
- A complete second candidate is required before generating the blind-listening package.
- Checkpoint C4 remains open until both default and fallback complete the corpus, blind listening is approved, and the final selection is recorded in `design.md`.
