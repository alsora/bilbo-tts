# Adding a book

This guide describes how to configure a new book, run source extraction, and review the extracted text.

## Book configuration and artifacts

Each book uses a strict `books/<book-id>/book.yaml` configuration with schema version `book-config/v1`.
The configuration records the source, presentation metadata, normalization and lexicon versions, the model config path selecting one synthesis candidate, and assembly parameters.
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
  model_config_path: config/qualification/fake.yaml
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
Entries in `normalization.lexicons` are checksum-pinned overlays applied in listed order, resolved inside the book directory or, with `scope: shared`, inside the repository's `config/lexicons/` directory.
Keep engine-specific pronunciation overrides in separately named overlay files so model-independent speech text remains auditable.
The overlay file format, placement rules, and correction workflow are documented in [Pronunciation lexicons](pronunciation-lexicons.md).
`chunking.max_characters` is an explicit positive character limit; engine-specific phoneme limits are deferred until model qualification.
`synthesis.model_config_path` selects one reviewed candidate file under the repository's `config/qualification/` directory, which owns the complete pinned model identity, voice, and generation settings.
The path is repository-relative even for books in private project roots, so every book shares the same reviewed candidate files.
The optional `synthesis.max_retries` bounds regeneration attempts per chunk and defaults to 2.
The `fake` candidate selects the deterministic dependency-free engine used by committed integration fixtures; production books use the interim Kokoro default documented in [TTS qualification](tts-qualification.md).
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
