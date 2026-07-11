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
  engine: fixture
  model_revision: fixture-v1
  voice:
    voice_id: narrator
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
The `fixture` synthesis values satisfy the current configuration contract but do not select the production voice or model.
Replace those values during model qualification before generating audio.
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
The default development environment can run the deterministic fake candidate without importing or downloading a model.

Run the fake qualification path:

```shell
.tools/bin/pixi run bilbo qualify-tts fake --project-root .
```

The command writes canonical evidence to `work/tts-qualification/fake/result.json`.
It writes one validated mono 16-bit PCM WAV per excerpt under `work/tts-qualification/fake/audio/`.
It writes a compact exception-focused report to `work/tts-qualification/fake/summary.md`.

Run a real candidate only from its isolated environment after the corresponding adapter and hardware checks are available:

```shell
.tools/bin/pixi run -e chatterbox bilbo qualify-tts chatterbox --project-root .
.tools/bin/pixi run -e kokoro bilbo qualify-tts kokoro --project-root .
```

Model downloads use the ignored cache paths below `work/cache/`.
The qualification runner records exact model, voice, settings, inference parameters, checksums, timings, real-time factor, failures, and process peak RSS when macOS exposes it.
No real model is imported by ordinary tests or `pixi run check`.

After two complete qualification runs, create a deterministic blind-listening package:

```shell
.tools/bin/pixi run bilbo prepare-tts-listening chatterbox kokoro \
  --project-root . \
  --seed 20260711
```

The command writes opaque WAV names and `rating-sheet.md` below `work/tts-qualification/listening/`.
Keep `mapping.json` closed until all ratings have been recorded.
