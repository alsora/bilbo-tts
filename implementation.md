# Italian Audiobook Pipeline Implementation Milestones

This document defines delivery order, verification activities, and checkpoint exit criteria. [`design.md`](design.md) is the source of truth for system architecture, stable contracts, dependency isolation, model strategy, and normalization policy. This document links to those decisions rather than repeating them.

If an architectural decision changes, update `design.md` first and adjust only the affected milestone or acceptance criterion here.

## Verification levels

Every milestone uses the smallest relevant set of these verification levels:

- **Fast checks:** formatting, linting, static typing, schemas, unit tests, and deterministic golden fixtures, exposed through `pixi run check`.
- **Integration checks:** run CLI stages against tiny fixture books without downloading large models.
- **Hardware checks:** opt-in local MLX/MPS tests for TTS and ASR; these are not part of ordinary CI.
- **Quality checks:** fixed Italian regression excerpts, objective metrics, and explicit listening review.
- **End-to-end checks:** one representative chapter before full-book generation.

Every stage must validate upstream hashes, write outputs atomically, and emit a machine-readable summary. Missing, invalid, or stale artifacts block downstream work.

```mermaid
flowchart LR
    gate0["C0 Reproducible environment"] --> gate1["C1 Stable artifact contracts"]
    gate1 --> gate2["C2 Trusted source extraction"]
    gate2 --> gate3["C3 Verified spoken text"]
    gate3 --> gate4["C4 Qualified TTS engine"]
    gate4 --> gate5["C5 Resumable synthesis"]
    gate5 --> gate6["C6 Calibrated verification"]
    gate6 --> gate7["C7 Valid chaptered M4B"]
    gate7 --> gate8["C8 Full-book qualification"]
```

## Milestone 0 — Reproducible environment

Build:

- Add `pyproject.toml`, `pixi.lock`, package scaffolding, and the initial CLI.
- Implement the Pixi environments and tasks specified in [`design.md`](design.md#environment-and-dependency-isolation).
- Add a `bilbo doctor` command that reports architecture, executable paths, cache paths, and MLX/MPS availability without downloading models.
- Ignore generated environments, caches, and `work/` while committing dependency manifests and locks.

Verify:

- Create the environment from the lock file.
- Run formatting, linting, static typing, tests, and a CLI smoke test.
- Confirm Python, Pandoc, FFmpeg, and native libraries resolve from the Pixi environment rather than system locations.

Checkpoint C0:

- A clean checkout completes `pixi install --locked` and `pixi run check` without project dependencies installed system-wide.

## Milestone 1 — Contracts, configuration, and artifact store

Build:

- Implement the data contracts defined in [`design.md`](design.md#stable-contracts) as validated Pydantic models.
- Validate per-book configuration, rejecting unknown or incompatible fields.
- Implement canonical serialization, schema versions, SHA-256 cache keys, checksums, atomic replacement, and workspace path ownership.
- Refuse stale or incompatible upstream artifacts.

Verify:

- Test valid and invalid manifests, deterministic serialization, unknown fields, corruption, and interrupted writes.
- Prove that spoken text, lexicon, voice, model revision, or synthesis-setting changes affect the appropriate cache key.
- Prove that unrelated presentation metadata does not invalidate generated audio.

Checkpoint C1:

- A synthetic book round-trips through every manifest schema with stable hashes, and stale artifacts are detected before use.

## Milestone 2 — Source ingestion

Build:

- Implement LaTeX ingestion through Pandoc AST and born-digital PDF ingestion through the adapters chosen in [`design.md`](design.md#components-and-proposed-layout).
- Preserve chapter order, paragraphs, relevant source locations, and extraction warnings.
- Define explicit handling for footnotes, lists, quotations, tables, equations, captions, references, headers, and footers.
- Record exclusions instead of silently dropping content.
- Emit a canonical document artifact and readable extraction report.

Verify:

- Create reviewed LaTeX and PDF fixtures containing structural and formatting edge cases.
- Compare extraction against golden manifests.
- Check chapter order, paragraph counts, non-empty text, source references, and warnings for unsupported or scanned material.

Checkpoint C2:

- Manually inspect one representative chapter from the target book and approve its reading order, structure, omissions, and warnings.

## Milestone 3 — Italian normalization and chunking

Build:

- Implement the ordered, deterministic rules and lexicon behavior specified in [`design.md`](design.md#normalization-and-verification-policy).
- Preserve original display text, spoken text, and an audit trail of every applied transformation.
- Validate the finance pronunciation lexicon and keep model-specific overrides separate.
- Implement paragraph-first sentence splitting with configurable model limits, stable identifiers, and pause metadata.
- Emit reports for unresolved symbols, applied lexicon entries, chunk-size distribution, and source-to-chunk mapping.

Verify:

- Add golden cases for ratios, percentages, decimals, currencies, dates, years, ranges, section references, negative values, acronyms, English loanwords, and difficult finance terms.
- Assert normalization is idempotent and never mutates display text.
- Reconstruct normalized paragraphs from chunks and prove no words were lost, duplicated, or reordered after canonical whitespace normalization.
- Exercise exact chunk limits and common Italian abbreviations.

Checkpoint C3:

- Review a full chapter's normalization and chunk reports, resolving or explicitly accepting every warning and sampling every rule category.

## Milestone 4 — TTS adapters and model qualification

Build:

- Define a narrow TTS interface covering model identity, capabilities, sample rate, voice configuration, seeded generation, and health checks.
- Implement the candidate engines listed in [`design.md`](design.md#model-and-runtime-strategy-for-a-16-gb-apple-silicon-mac) in separate Pixi environments.
- Create a fixed set of 20–30 Italian excerpts covering ordinary prose and known pronunciation risks.
- Record generation time, real-time factor, memory pressure where observable, audio format, and exact model configuration.

Verify:

- Run backend contract tests against a fake engine and opt-in smoke tests against each real engine.
- Generate the complete regression corpus with each candidate.
- Conduct randomized blind listening for intelligibility, pronunciation, prosody, voice consistency, artifacts, and overall preference.
- Treat ASR metrics as supporting evidence, not the model-selection oracle.

Checkpoint C4:

- Record the chosen default engine, voice, parameters, and fallback in `design.md`. The selected setup must run with acceptable stability and memory pressure on the target Mac.

## Milestone 5 — Resumable synthesis

Build:

- Generate one lossless WAV per chunk with a generation sidecar.
- Address outputs using the cache-key policy in [`design.md`](design.md#stable-contracts).
- Use atomic writes, checksums, structured errors, bounded retries, and a single-worker default for the target hardware.
- Support selection by book, chapter, chunk range, failed chunks, and forced regeneration.
- Validate existing files before treating them as complete.

Verify:

- Interrupt synthesis and confirm a rerun resumes without regenerating valid chunks.
- Run identical synthesis twice and assert that the second run generates nothing.
- Change one lexicon entry and assert only affected chunks receive new keys.
- Detect empty, truncated, corrupt, wrong-format, and checksum-mismatched WAV files.

Checkpoint C5:

- Generate the representative chapter twice; the second run is a no-op, all sidecars validate, and simulated interruption recovery succeeds.

## Milestone 6 — Round-trip ASR and review loop

Build:

- Implement the ASR adapter selected in [`design.md`](design.md#model-and-runtime-strategy-for-a-16-gb-apple-silicon-mac).
- Run ASR in a separate Pixi process after TTS exits so both models are never resident simultaneously.
- Compare transcripts with spoken text using shared Italian comparison normalization, WER/CER alignment, and the additional heuristics from the design.
- Classify chunks as `accepted`, `retryable`, or `review`.
- Bound automatic retries, then require an explicit human decision.
- Emit machine-readable and readable reports containing reason codes, source text, spoken text, transcript, alignment, metrics, and audio path.

Verify:

- Unit-test comparison normalization, metrics, and classification.
- Test deliberately truncated, repeated, silent, clipped, and speed-altered samples.
- Calibrate thresholds on the regression corpus and inspect false positives and false negatives.
- Confirm retries terminate and manual overrides remain explicit and auditable.

Checkpoint C6:

- The representative chapter contains no unclassified chunks. Every failure is regenerated successfully or manually reviewed, and threshold behavior is accepted.

## Milestone 7 — Assembly and media validation

Build:

- Assemble accepted chunks only, inserting the configured sentence, paragraph, and chapter pauses.
- Concatenate lossless PCM, derive chapter markers from accumulated durations, attach metadata and optional cover art, apply two-pass loudness normalization, and encode AAC once.
- Persist commands, loudness measurements, chapter timestamps, input checksums, and final media metadata.

Verify:

- Check assembly order and expected duration from chunk lengths plus pauses.
- Use `ffprobe` to verify codec, channels, sample rate, metadata, cover art, monotonic chapters, and total duration.
- Measure integrated loudness and true peak against configured tolerances.
- Confirm missing, stale, failed, and unreviewed chunks block assembly unless explicitly overridden.

Checkpoint C7:

- Listen through the representative chapter M4B, checking its start and end, every structural transition, representative joins, metadata, seeking, and playback in an audiobook-capable player.

## Milestone 8 — Full-book qualification

Build:

- Add idempotent orchestration across the existing stages without introducing a separate workflow engine.
- Document bootstrap, book configuration, lexicon editing, selective regeneration, review decisions, assembly, cache cleanup, and interruption recovery.
- Preserve model license and revision, voice provenance, configuration, manifests, and reports with the final build.

Verify:

- Run the representative chapter from a clean workspace and rerun it to prove idempotency.
- Perform a full-book text-only dry run and review chapter counts, warnings, unresolved tokens, chunk outliers, and estimated duration.
- Generate and verify the full book with zero missing, stale, failed, or unreviewed chunks.
- Validate loudness, chapters, metadata, duration, checksums, and playback.
- Listen to every flagged chunk and random samples from every chapter.

Checkpoint C8:

- Deliver the M4B with the locked environment, source/configuration hashes, model and voice provenance, manifests, verification report, and exact reproducible build command.

## Deferred scope

Unless the first source requires them, defer OCR for scanned books, a web service, distributed workers, a database, a GUI, and a Docker runtime. Pronunciation changes remain deterministic, versioned rules rather than automatic model rewrites.
