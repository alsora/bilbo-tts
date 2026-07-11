# Milestone 4 Execution Plan

This file is the session-to-session execution plan for Milestone 4 and checkpoint C4.
[`implementation.md`](implementation.md) remains the source of truth for milestone scope and acceptance criteria.
[`design.md`](design.md) remains the source of truth for architecture, contracts, model strategy, and runtime policy.

## Starting state

- Start from synchronized `main` after committing the current handoff and this plan.
- Checkpoint C3 is approved for target chapter 2.
- The existing synthesis contracts in [`src/bilbo_tts/models.py`](src/bilbo_tts/models.py) and [`src/bilbo_tts/config.py`](src/bilbo_tts/config.py) are the integration boundary.
- The `chatterbox`, `kokoro`, and `asr` Pixi environments exist but still contain only the base feature.
- No TTS adapter, qualification corpus, model dependency, real-model test, or qualification runner exists yet.
- The target platform is a 16 GB Apple Silicon Mac.
- Create `milestone/c4-tts-qualification` from `main` before implementation.

## Decisions already made

- Implement and evaluate both Chatterbox Multilingual V3 and Kokoro-82M through MLX.
- Keep each inference backend in its own Pixi environment with lazy imports.
- Add a minimal MLX-Whisper qualification scorer during C4 and run it in a separate process after TTS exits.
- Defer the reusable ASR adapter, retry classification, review queue, and verification integration to C6.
- Treat ASR metrics as supporting evidence rather than the model-selection oracle.
- Keep resumable synthesis, generation sidecars, content-addressed WAV storage, and the production `synthesize` stage in C5.
- Preserve permissive licensing and use only a voice the user owns or has permission to reproduce.
- Keep fallback selection as a documented manual contingency in C4 rather than implementing automatic runtime fallback.

## Exit criteria

C4 is complete only when all of the following are true:

- The default engine, model revision, voice, sample rate, seed, inference parameters, and fallback are recorded in [`design.md`](design.md).
- Both candidate adapters pass the shared contract tests through a fake backend.
- Each available real engine passes its opt-in hardware smoke test.
- Each viable candidate generates the complete fixed Italian regression corpus.
- Qualification reports record generation time, audio duration, real-time factor, audio format, exact model configuration, failures, and observable memory pressure.
- MLX-Whisper scores the generated corpus in a separate process.
- Randomized blind listening covers intelligibility, pronunciation, prosody, voice consistency, artifacts, and overall preference.
- The selected default completes the corpus without crashes, system termination, invalid audio, or unacceptable memory pressure on the target Mac.
- The fallback completes the corpus with valid audio and acceptable intelligibility.
- `pixi run check` passes without downloading models.
- Required model-environment and hardware checks pass before the branch is pushed.
- Human listening approval remains explicit and is not inferred from ASR scores.

## Slice 1: dependency and model research

- Confirm the current supported Apple Silicon packages and APIs for Chatterbox Multilingual V3, Kokoro-82M MLX, and MLX-Whisper.
- Record package licenses, model-weight licenses, model identifiers, immutable revisions where available, supported Italian voices, native sample rates, seed controls, and text limits.
- Confirm whether each backend returns mono audio, its sample representation, and any required resampling.
- Confirm how to measure process peak memory and swap pressure on the target macOS version.
- Choose the permitted Chatterbox reference voice and checksum or explicitly document that the candidate will run without cloning.
- Choose the Kokoro Italian voice only after confirming it is available in the pinned model revision.
- Add the verified dependencies to dedicated `chatterbox`, `kokoro`, and `asr` Pixi features in [`pyproject.toml`](pyproject.toml).
- Regenerate and commit [`pixi.lock`](pixi.lock).
- Keep model caches under the existing ignored `work/cache/` paths.
- Verify locked installation of every model environment before writing adapters.

## Slice 2: narrow TTS contract and fake backend

- Add [`src/bilbo_tts/tts/`](src/bilbo_tts/tts/) with a protocol and small validated request, capability, health, and result types.
- Reuse `ModelIdentity`, `VoiceConfig`, and `SynthesisSettings` instead of duplicating synthesis identity fields.
- Require adapters to expose exact engine and model identity, native sample rate, supported voice modes, seed support, text limits where known, and a non-generating health check.
- Make synthesis accept spoken text, validated voice configuration, and synthesis settings.
- Normalize adapter output to mono signed 16-bit PCM bytes plus sample rate and duration metadata so the base environment does not require NumPy.
- Reject empty text, unsupported sample rates or settings, invalid voice configuration, empty audio, and mismatched output metadata with actionable errors.
- Add a deterministic fake engine that produces valid PCM from the request seed and spoken-text hash without downloading a model.
- Avoid a general plugin system or speculative registry unless the qualification command requires a minimal explicit factory.
- Add shared backend contract tests that run against the fake engine in the default environment.
- Cover deterministic seeding, identity propagation, health reporting, capability rejection, sample format, duration, and failure messages.

## Slice 3: fixed Italian qualification corpus

- Add a committed versioned corpus under `config/qualification/`.
- Use 24 excerpts so the corpus remains inside the required 20–30 range.
- Give every excerpt a stable identifier, category, reviewed spoken text, and short review note.
- Cover ordinary prose, dialogue, long sentences, percentages, ratios, currencies, abbreviations, dates, section references, acronyms, English finance terms, and difficult finance vocabulary.
- Include typographic apostrophes and quotation marks.
- Include `0,25%`, `0,025%`, and other leading-zero decimals.
- Include a sentence that exercises a forced colon or semicolon chunk boundary.
- Validate unique identifiers, non-empty Italian text, required category coverage, and deterministic loading.
- Keep generated WAV files, transcripts, and run reports under ignored `work/tts-qualification/`.

## Slice 4: qualification runner and reports

- Add a `bilbo qualify-tts` command that runs one candidate in its own environment against the committed corpus.
- Keep the runner independent of the C5 book synthesis artifact pipeline.
- Write one PCM WAV per excerpt using the standard library where practical.
- Validate every WAV for non-zero duration, mono channel count, sample rate, sample width, and readable frame data.
- Record wall-clock generation time, audio duration, real-time factor, exact request settings, model identity, voice identity, seed, output checksum, and failure details.
- Record peak resident memory and other macOS memory observations when they are available without adding a fragile dependency.
- Write a canonical JSON result and a compact Markdown summary with exceptions rather than repeating all successful samples.
- Make reruns deterministic in layout and metadata while allowing measured timings to vary.
- Add a deterministic listening-package command that assigns blinded sample identifiers and randomizes engine order from a recorded seed.
- Keep the unblinded mapping separate from the rating sheet until listening is complete.
- Add unit tests for corpus validation, PCM WAV writing, metrics, report rendering, blinded ordering, and partial engine failure.

## Slice 5: Chatterbox adapter

- Add the Chatterbox adapter behind lazy imports so `pixi run check` does not import or download model dependencies.
- Map the committed candidate configuration to the exact model revision, permitted voice reference, native sample rate, seed, and supported inference parameters.
- Convert backend audio to the shared PCM result without silently changing requested settings.
- Surface unsupported parameters and memory failures as structured actionable errors.
- Add an opt-in hardware smoke test using one short Italian excerpt.
- Ensure the smoke test is skipped unless explicitly enabled and is excluded from ordinary CI model downloads.
- Run the full corpus only after the smoke test succeeds.
- Record instability or unacceptable memory pressure as qualification evidence rather than patching around it.

## Slice 6: Kokoro adapter

- Add the Kokoro MLX adapter behind lazy imports.
- Pin the exact Kokoro model and Italian voice used by the qualification configuration.
- Map speed and other supported settings explicitly and reject unsupported settings.
- Convert native output to the shared PCM result and preserve the engine sample rate.
- Add an opt-in hardware smoke test using the same short Italian excerpt as Chatterbox.
- Run the full Italian corpus and pay particular attention to G2P, English-like prosody, finance terms, and voice consistency.

## Slice 7: minimal ASR qualification scorer

- Add only the MLX-Whisper functionality needed to transcribe qualification WAV files.
- Use `large-v3-turbo` by default while keeping the exact model identifier and revision configurable.
- Run the scorer from the separate `asr` Pixi environment after the TTS process has exited.
- Never keep TTS and ASR models resident in unified memory simultaneously.
- Compare transcripts with corpus `spoken_text` using a small documented comparison normalization for casing, punctuation, apostrophe variants, and accent variants.
- Record transcript, WER, and CER for each sample and aggregate results by engine and category.
- Keep thresholds, retry classification, and review-state decisions out of C4.
- Add deterministic unit tests for comparison normalization and metrics without loading Whisper.
- Add one opt-in MLX-Whisper smoke test.

## Slice 8: hardware bake-off and human checkpoint

- Install each locked model environment on the target Mac.
- Run engine health checks and one-excerpt smoke tests before full-corpus generation.
- Generate all 24 excerpts with Chatterbox in one process, then exit.
- Generate all 24 excerpts with Kokoro in a separate process, then exit.
- Run MLX-Whisper scoring only after both TTS processes have exited.
- Preserve all command lines, model revisions, voice identifiers, settings, seeds, failures, timing data, and memory observations.
- Reject invalid, empty, truncated, unreadable, wrong-rate, or wrong-channel audio before listening.
- Produce the deterministic blinded listening package.
- Have the user score intelligibility, pronunciation, prosody, consistency, artifacts, and overall preference.
- Reveal engine identities only after ratings are recorded.
- Select the default from listening quality, stability, memory pressure, and speed together.
- Use ASR only to identify suspicious samples and support the decision.
- Select and document a fallback even if the preferred engine is clearly better.

## Documentation and handoff

- Update [`design.md`](design.md) with the chosen default engine, exact model revision, voice provenance, sample rate, seed, parameters, text-limit behavior, and fallback.
- Document first-run model downloads, cache locations, qualification commands, hardware-test opt-in flags, and failure recovery in [`README.md`](README.md).
- Keep milestone sequencing and checkpoint wording in [`implementation.md`](implementation.md) unchanged unless execution reveals a genuine acceptance-criterion conflict.
- Update fixture or example synthesis configuration only where it represents production guidance.
- Keep tiny integration books on a deterministic fake engine if real models would make ordinary tests download weights.
- Update [`HANDOFF.md`](HANDOFF.md) after every coherent implementation session and before each push.

## Verification commands

- Run focused unit tests after each implementation slice.
- Run `pixi run check` before every commit.
- Run locked installation checks for `chatterbox`, `kokoro`, and `asr`.
- Run each opt-in hardware smoke test in its corresponding environment.
- Run the complete corpus and report generation for both candidates.
- Run the separate ASR scorer against both completed audio sets.
- Review the complete branch diff against `main` before pushing.
- Push the normal milestone branch only after automated checks pass.
- If blind listening is still pending, report the branch as automatically verified but leave checkpoint C4 explicitly awaiting human approval.

## Explicitly deferred

- Production `bilbo synthesize` orchestration.
- Per-book or per-chunk resumability.
- Content-addressed WAV placement and `GenerationRecord` sidecars.
- Retries and selective regeneration.
- Full ASR adapter abstraction and verification queue.
- Acceptance, retry, and manual-review classification.
- Model-specific phoneme limits unless qualification supplies a verified counting rule needed by C5.
- Automatic runtime fallback.

## Expected commit sequence

1. `feat: add TTS qualification contracts and corpus`
2. `feat: qualify Chatterbox on Apple Silicon`
3. `feat: qualify Kokoro on Apple Silicon`
4. `feat: add separate-process ASR qualification scoring`
5. `docs: record the qualified TTS default and fallback`

Each commit must include its tests, configuration, documentation, and lock-file changes.
Do not create the final selection commit until blind listening and the C4 decision are complete.
