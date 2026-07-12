# bilbo-tts

`bilbo-tts` is a reproducible local pipeline for generating Italian audiobooks.

The architecture is documented in [`design.md`](design.md).

Implementation milestones and verification gates are documented in [`implementation.md`](implementation.md).

## Development environment

The initial development platform is Apple Silicon macOS.

Project dependencies are isolated with Pixi and do not rely on a system Python, FFmpeg, Pandoc, or libsndfile installation.

Bootstrap the pinned Pixi executable into the ignored project-local tools directory:

```shell
./scripts/bootstrap-pixi.sh
```

Install the locked default environment:

```shell
.tools/bin/pixi install --locked
```

Run all fast verification:

```shell
.tools/bin/pixi run check
```

Inspect the active environment without downloading models:

```shell
.tools/bin/pixi run bilbo doctor
```

Model-specific environments are named `chatterbox`, `kokoro`, and `asr`.

Each environment has an exact dependency pin and remains isolated from the default development environment.
The Chatterbox candidate uses the official V3 PyTorch MPS implementation because no maintained V3 MLX port exists.
The Kokoro and Whisper candidates use MLX.

## Testing

Install the locked development environment before running tests:

```shell
.tools/bin/pixi install --locked
```

Run the complete unit test suite with coverage:

```shell
.tools/bin/pixi run test
```

Run one test module or one specific test directly with Pytest:

```shell
.tools/bin/pixi run pytest tests/test_artifacts.py -v --no-cov
.tools/bin/pixi run pytest tests/test_artifacts.py::test_artifact_round_trip_is_deterministic -v --no-cov
```

Focused runs disable the repository-wide coverage gate, which is enforced by the complete suite.

Run the full fast verification gate, including formatting, linting, strict type checking, and tests:

```shell
.tools/bin/pixi run check
```

Pytest settings and the minimum coverage threshold are defined in [`pyproject.toml`](pyproject.toml).

## Book configuration and artifacts

Each book uses a strict `books/<book-id>/book.yaml` configuration with schema version `book-config/v1`.
The configuration records the source, presentation metadata, normalization and lexicon versions, synthesis identity and settings, and assembly parameters.
Paths in book configuration must be normalized relative paths and unknown or incompatible fields are rejected.

Derived data belongs under the ignored `work/<book-id>/` workspace.
Persistent manifests use versioned Pydantic contracts and deterministic canonical JSON.
Artifacts include payload checksums and exact upstream references, and downstream reads fail when stored data is corrupt, incompatible, missing, or stale.
Synthesis cache keys include every audio-affecting input while excluding presentation-only metadata.

## Source ingestion

Follow these steps from the repository root.

### 1. Prepare the book directory

Create one directory below `books/`.
Choose a short lowercase identifier containing letters, digits, hyphens, underscores, or dots, such as `my-book`.
The identifier must start and end with a letter or digit, and separators cannot be repeated.
The directory name and the `book_id` value in `book.yaml` must match exactly.

For a LaTeX book, use this layout:

```text
books/
  my-book/
    book.yaml
    source/
      main.tex
      chapters/
        chapter-one.tex
      assets/
        cover.jpg
```

Copy the complete LaTeX source tree below `source/`, not only the entry-point file.
All files reached through `\input`, `\include`, or static `\import` must remain below that directory.
LaTeX files must be UTF-8, and symlinks or paths that escape the source directory are rejected.
The entry point may use parts, chapters, sections, lists, quotations, footnotes, tables, equations, figures, citations, and cross-references.
Inline citations are recorded and omitted from narration, while cross-references retain Italian structural names and source-derived numbers.

For a PDF book, use this layout:

```text
books/
  my-book/
    book.yaml
    source/
      book.pdf
```

PDF ingestion requires a born-digital PDF with selectable text.
OCR is intentionally disabled, so an image-only or scanned page stops ingestion instead of producing incomplete text.

Book source files are not globally ignored by Git because some projects may choose to version them.
Do not stage or commit private or copyrighted source material unless that is intentional.
To keep a private book inside ignored storage, use an isolated project root such as `work/private-project/` and place the book under `work/private-project/books/my-book/`.
Pass that root explicitly while keeping the configuration path relative to it:

```shell
.tools/bin/pixi run bilbo ingest books/my-book/book.yaml --project-root work/private-project
```

This layout writes derived outputs below `work/private-project/work/my-book/`.

### 2. Create `book.yaml`

Create `books/my-book/book.yaml` with the following minimal LaTeX configuration:

```yaml
schema_version: book-config/v1
book_id: my-book
language: it

input:
  format: latex
  path: source/main.tex

metadata:
  title: Titolo del libro
  author: Nome Autore

normalization:
  version: it-v1
  lexicons: []

chunking:
  max_characters: 300

synthesis:
  engine: fake
  model_revision: fake-v1
  voice:
    voice_id: fake-voice
  settings:
    sample_rate_hz: 24000
    seed: 7
```

For a PDF, change only the input section:

```yaml
input:
  format: pdf
  path: source/book.pdf
```

`schema_version`, `book_id`, `language`, `input`, `metadata`, `normalization`, `chunking`, and `synthesis` are required.
`language` is currently fixed to `it`.
Every configured path is relative to the directory containing `book.yaml`; absolute paths, `..`, backslashes, and mismatched file extensions are rejected.
Optional metadata fields are `subtitle`, `narrator`, and `cover_path`.
`cover_path`, when present, must point to a relative JPEG or PNG file.
The reviewed built-in finance lexicon in `config/lexicons/finance-it.yaml` is always active for Italian normalization.
Entries in `normalization.lexicons` are checksum-pinned, book-relative overlays applied in listed order.
Keep engine-specific pronunciation overrides in separately named overlay files so model-independent speech text remains auditable.
`chunking.max_characters` is an explicit positive character limit; engine-specific phoneme limits are deferred until model qualification.
The `fake` synthesis values select the deterministic dependency-free engine used by committed integration fixtures.
For production, replace them with the qualified Chatterbox values documented below.
The optional `assembly` section may be omitted to use the default pause and loudness settings.
Unknown fields and misspelled field names are rejected with an actionable validation error.

### 3. Run extraction

Install the locked environment once:

```shell
.tools/bin/pixi install --locked
```

Run ingestion from the repository root:

```shell
.tools/bin/pixi run bilbo ingest books/my-book/book.yaml
```

Successful output is a single JSON object with `"status":"completed"`, chapter and block counts, warning and exclusion counts, and output checksums.
The command writes the canonical artifact to `work/my-book/manifests/book-document.json`.
The command writes the readable review report to `work/my-book/reports/extraction.md`.
If extraction fails, read the JSON error and any generated report, correct the source or configuration, and rerun the same command.
Rerunning unchanged input produces byte-identical files and checksums.

### 4. Review extraction

Open `work/my-book/reports/extraction.md` before running any downstream stage.
The report contains a chapter outline, warning and exclusion counts, and the full text of blocks with warnings or non-paragraph structure.
The canonical `book-document.json` retains every extracted block.

Generate the complete reading-order report for the representative chapter:

```shell
.tools/bin/pixi run bilbo review-extraction books/my-book/book.yaml \
  --chapter chapter-0002
```

The command writes `work/my-book/reports/review/chapter-0002-extraction.md`.

Use this review checklist:

1. Confirm that the chapter titles, count, and order match the source.
2. Compare at least one representative chapter against the source from beginning to end.
3. Check that every paragraph appears once and that no text is missing, duplicated, or moved.
4. Check that headings, list items, quotations, captions, and footnotes appear in the intended reading position.
5. For PDFs, check page references, multi-column reading order, and removal of repeated headers and footers.
6. Read every warning and exclusion, especially those for tables, equations, images, citations, and unsupported material.
7. Check tables row by row because they are flattened into spoken order and always require review.
8. Check equations and inline mathematics because normalization supports only a bounded deterministic vocabulary and warns on unsupported notation.
9. Search for extraction artifacts such as raw LaTeX commands, unresolved references, joined words, broken punctuation, or image placeholders.
10. Approve each omission explicitly or correct the source and rerun ingestion.

Pandoc does not expose reliable LaTeX line positions in its JSON AST.
LaTeX blocks therefore retain a source path without fabricated line numbers, while PDF blocks retain 1-based page numbers.
Treat the extraction as approved only when its reading order, structure, omissions, and warnings are understood and acceptable.

Committed C2 fixtures and their reviewed golden outputs live under `tests/fixtures/`.
Run the ingestion integration checks without model downloads:

```shell
.tools/bin/pixi run pytest tests/integration/test_ingest_cli.py -v --no-cov
```

## Italian normalization and chunking

Run these stages only after approving the extraction report.

```shell
.tools/bin/pixi run bilbo normalize books/my-book/book.yaml
.tools/bin/pixi run bilbo chunk books/my-book/book.yaml
```

For an isolated project root, pass the same `--project-root` option to both commands that was used for ingestion.
`normalize` validates the stored book artifact and configured lexicon checksums.
It writes `work/my-book/manifests/normalized-document.json` and `work/my-book/reports/normalization.md`.
The manifest preserves the complete display text, spoken text, and transformation audit trail.
The review report summarizes rules and warnings, omits unchanged warning-free blocks, and shows final spoken text with only the minimal span changed by each rule.
Normalization preserves typographic apostrophes and quotation marks produced by rendered source text.
Apostrophe and quote variants are canonicalized later for ASR comparison rather than rewritten in `spoken_text`.
Specific Italian patterns such as dates, ratios, percentages, currencies, ranges, section references, and bounded equations run before generic number expansion.
Decimal fractional parts are pronounced as grouped numbers, so `0,25%` becomes `zero virgola venticinque per cento`.
Unsupported mathematical notation remains visible and produces an `unresolved-math` warning instead of guessed speech.

`chunk` validates the normalized artifact and its upstream book artifact.
It writes `work/my-book/manifests/chunk-manifest.json` and `work/my-book/reports/chunking.md`.
The manifest retains every stable source-derived identifier, character count, source mapping, and pause value.
The full-book review report contains per-chapter metrics, forced intra-sentence split contexts, and ordering, limit, or pause anomalies.
Ordinary sentence boundaries and complete chunk text remain only in the manifest and focused chapter reports.
A sentence longer than `max_characters` splits first at punctuation and then at whitespace.
Forced splits avoid extra or very short chunks and prefer semicolons and colons over commas.
A single word longer than the configured limit fails with an actionable error rather than violating the limit.

Generate the complete chunk and pause report for the representative chapter:

```shell
.tools/bin/pixi run bilbo review-chunking books/my-book/book.yaml \
  --chapter chapter-0002
```

The command writes `work/my-book/reports/review/chapter-0002-chunking.md`.
To complete checkpoint C3, review the focused extraction and chunking reports together with the compact normalization report.
Resolve or explicitly accept every warning, sample every transformation category, confirm each source block maps to chunks in order, and inspect the smallest and largest chunks.
Changing the source or lexicons makes downstream artifacts stale, so rerun `normalize` and then `chunk`.
Unchanged reruns are byte-identical.

Committed text-stage fixtures and reviewed goldens run without model downloads:

```shell
.tools/bin/pixi run pytest tests/integration/test_text_pipeline_cli.py -v --no-cov
```

## TTS qualification

The fixed reviewed Italian corpus and exact candidate configurations live under `config/qualification/`.
Qualification commands select a candidate by name: the stem of a `config/qualification/<name>.yaml` file.
One engine can therefore have several qualified variants side by side, such as `chatterbox` and an experimental `chatterbox-fp16`, each with its own evidence under `work/tts-qualification/<name>/`.
The default development environment can run the deterministic fake candidate without importing or downloading a model.
The qualified default is Chatterbox Multilingual V3 with its pinned built-in voice.
The qualified fallback is Kokoro-82M with Italian voice `if_sara`.
Human review strongly preferred Chatterbox and accepted Kokoro as an intelligible lower-quality fallback.
Chatterbox retains a mild English-native accent on some Italian words, which should be addressed only through reviewed model-specific pronunciation overrides.
The exact revisions, settings, runtime limits, and selection policy are recorded in [`design.md`](design.md#model-and-runtime-strategy-for-a-16-gb-apple-silicon-mac).

Run the fake qualification path:

```shell
.tools/bin/pixi run bilbo qualify-tts fake --project-root .
```

The command writes canonical evidence to `work/tts-qualification/fake/result.json`.
It writes one validated mono 16-bit PCM WAV per excerpt under `work/tts-qualification/fake/audio/`.
It writes a compact exception-focused report to `work/tts-qualification/fake/summary.md`.

Run each opt-in smoke test from its isolated environment on Apple Silicon:

```shell
BILBO_HARDWARE_TESTS=1 .tools/bin/pixi run -e chatterbox pytest \
  tests/hardware/test_chatterbox_smoke.py -v --no-cov
BILBO_HARDWARE_TESTS=1 .tools/bin/pixi run -e kokoro pytest \
  tests/hardware/test_kokoro_smoke.py -v --no-cov
```

The smoke tests use the same short committed Italian excerpt and are skipped unless `BILBO_HARDWARE_TESTS=1`.
They resolve only the immutable model revisions recorded in the candidate configurations.
Chatterbox requires macOS 15.1 or newer because earlier MPS frameworks reject long-output convolution even when the short smoke test passes.
Run a complete candidate only after its smoke test passes:

```shell
.tools/bin/pixi run -e chatterbox bilbo qualify-tts chatterbox --project-root .
.tools/bin/pixi run -e kokoro bilbo qualify-tts kokoro --project-root .
```

Each `qualify-tts` command must finish and its process must exit before starting another model process.
After a candidate has a completed 24-sample `result.json`, score it from the separate ASR environment:

```shell
.tools/bin/pixi run -e asr bilbo score-tts-asr chatterbox --project-root .
.tools/bin/pixi run -e asr bilbo score-tts-asr kokoro --project-root .
```

Do not run a TTS qualification process while `score-tts-asr` is running because both model families use unified memory.
The scorer validates the complete TTS result and every referenced WAV and checksum before loading the pinned `mlx-community/whisper-large-v3-turbo` snapshot.
It resolves revision `a4aaeec0636e6fef84abdcbe3544cb2bf7e9f6fb` once, transcribes all samples sequentially, and never resolves a mutable branch.
ASR evidence is written atomically below `work/tts-qualification/asr/<candidate-name>/` as canonical `result.json` and compact `summary.md`.
Comparison normalization applies Unicode canonical normalization and case folding, canonicalizes apostrophe variants while retaining the apostrophe, replaces other punctuation with spaces, removes accent distinctions, and collapses whitespace identically for references and transcripts.
WER counts normalized whitespace-delimited words, while CER counts normalized non-whitespace characters.
Both rates use the reference-unit count as their denominator.
For an empty reference, an empty transcript has rate zero and a nonempty transcript has a rate equal to its insertion count, avoiding division by zero while preserving every insertion.
Raw corpus references and raw Whisper transcripts remain in the evidence.

Run the opt-in Whisper smoke test only after a qualification WAV already exists:

```shell
BILBO_HARDWARE_TESTS=1 .tools/bin/pixi run -e asr pytest \
  tests/hardware/test_whisper_smoke.py -v --no-cov
```

The smoke test defaults to Kokoro `prose-01` and accepts another existing qualification WAV through `BILBO_WHISPER_SMOKE_WAV`.
It loads no TTS model.
Model downloads use the ignored cache paths below `work/cache/`.
The qualification runner records exact model, voice, settings, inference parameters, checksums, timings, real-time factor, failures, and process peak RSS when macOS exposes it.
No real model is imported by ordinary tests or `pixi run check`.
If health reports a missing package, rerun the command in the matching Pixi environment.
If health reports unavailable MPS or Metal, verify that the command is running on Apple Silicon in the intended environment.
For an MPS or Metal out-of-memory failure, stop other GPU workloads and rerun the failed smoke test before attempting the full corpus.
Treat a repeated model-load or memory failure as qualification evidence instead of changing the pinned model or settings.
If ASR rejects an incomplete TTS result or a WAV checksum, rerun that candidate's complete `qualify-tts` command before retrying scoring.
If one transcription fails, inspect the failure and WAV named in the ASR summary, close other Metal workloads, and rerun the same scoring command.
Do not edit generated evidence to recover from a failure because reruns replace reports atomically.

After two or more complete qualification runs, create a deterministic blind-listening package from their candidate names:

```shell
.tools/bin/pixi run bilbo prepare-tts-listening chatterbox kokoro \
  --project-root . \
  --seed 20260711
```

The command writes opaque WAV names and `rating-sheet.md` below `work/tts-qualification/listening/`.
Comparing named variants of the same engine and voice is the intended way to evaluate an engine change blind.
Keep `mapping.json` closed until all ratings have been recorded.

## Resumable synthesis

Run synthesis only after the normalized text and chunking reports are approved.
Production books use the qualified Chatterbox identity and request settings:

```yaml
synthesis:
  engine: chatterbox
  model_revision: 5bb1f6ee58e50c3b8d408bc82a6d3740c2db6e18
  voice:
    voice_id: builtin
  settings:
    sample_rate_hz: 24000
    seed: 20260711
    speed: 1.0
    temperature: 0.8
  max_retries: 2
```

Run Chatterbox from its isolated Pixi environment:

```shell
.tools/bin/pixi run -e chatterbox bilbo synthesize books/my-book/book.yaml
```

For an isolated private project, pass the same project root used by the text stages:

```shell
.tools/bin/pixi run -e chatterbox bilbo synthesize \
  books/my-book/book.yaml \
  --project-root work/private-project
```

The stage processes chunks sequentially and loads the model only when selected audio must be generated.
Each chunk writes `work/<book-id>/audio/<chunk-id>/<cache-key>.wav` and an adjacent generation sidecar.
The current book state is recorded in `manifests/generation-manifest.json` and summarized in `reports/synthesis.md`.
Every existing pair is validated for identity, checksum, mono PCM16 format, sample rate, frame count, and duration before it is skipped.
An unchanged rerun is therefore a no-op and does not load model weights.

Restrict a run with any combination of chapter and inclusive chunk sequence bounds:

```shell
.tools/bin/pixi run -e chatterbox bilbo synthesize books/my-book/book.yaml \
  --chapter chapter-0002 \
  --chunk-start 20 \
  --chunk-end 40
```

Combined selectors intersect.
Invalid chapter identifiers and ranges fail before model loading.
Use `--failed` to select only chunks whose current cache identity has an exhausted TTS failure.
Use `--force` to regenerate otherwise valid selected chunks.
Automatic fallback is intentionally absent; switch the book configuration to the pinned Kokoro identity and run from the `kokoro` environment when the documented manual contingency is required.

If synthesis is interrupted, rerun the same command.
Completed sidecar/WAV pairs remain valid, while missing or incomplete pairs are regenerated.
Each retry deterministically offsets the configured seed by the retry number, because seeded generation would otherwise reproduce the same failure; the recorded retry number keeps every attempt reproducible.
After `max_retries + 1` failed attempts, the stage writes a structured failure sidecar, continues other selected chunks, emits a partial or failed summary, and exits nonzero.
Correct the reported problem and rerun with `--failed`.
Do not edit generated sidecars or manifests by hand.

Run the model-free synthesis integration checks with:

```shell
.tools/bin/pixi run pytest tests/integration/test_synthesis_cli.py -v --no-cov
```
