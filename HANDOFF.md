# Session Handoff

## Current state

- The active branch is `milestone/c4-tts-qualification` at user commit `5e225c3` before the current follow-up.
- Checkpoint C3 is approved after human review of chapter 2 extraction, normalization, and chunking.
- The private target source and generated reports remain only under ignored `work/c2-target-project/`.
- Milestone 4 commits are `8f24bb2`, `4f9340d`, `4cee05d`, and `027e68b`.
- Generated model caches, WAV files, qualification results, and ASR evidence remain under ignored `work/`.
- The user upgraded the target Mac from macOS 14.5 to Tahoe 26.5.2.
- Both candidates now complete the fixed corpus, and the deterministic blind-listening package is ready.

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
- On macOS 14.5, `long-01` reproducibly failed because its MPS framework rejected output channels above 65,536.
- On Tahoe 26.5.2, Chatterbox completes all 24 excerpts in 873.13 seconds for 139.00 seconds of audio with 4.14 GB process peak RSS.
- The Kokoro hardware smoke test passes in 16.26 seconds.
- Kokoro completes all 24 excerpts in 25.15 seconds for 161.40 seconds of audio with 963.92 MB process peak RSS.
- The MLX-Whisper hardware smoke test passes in 69.18 seconds.
- MLX-Whisper scores all 24 Chatterbox excerpts with weighted WER 0.167116 and CER 0.182331.
- MLX-Whisper scores all 24 Kokoro excerpts with weighted WER 0.161725 and CER 0.182331.
- The listening package contains 48 opaque clips under `work/tts-qualification/listening/` with seed `20260711`.
- The user reports that unblinded listening strongly favors Chatterbox, while formal blind ratings remain pending.

## Durable references

- Architecture and stable policy are owned by [`design.md`](design.md).
- Milestones and checkpoint criteria are owned by [`implementation.md`](implementation.md).
- The next-session C4 execution plan is [`milestone-4-plan.md`](milestone-4-plan.md).
- Repository working conventions are owned by [`AGENTS.md`](AGENTS.md).

## Next action

- Complete `work/tts-qualification/listening/rating-sheet.md` without opening `mapping.json`.
- Reveal the mapping only after all ratings are recorded.
- Select the default and fallback from listening quality, stability, memory, and speed, then record the final decision in `design.md`.
- Checkpoint C4 remains open only for the human blind-listening decision and final selection documentation.
