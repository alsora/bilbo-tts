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

Their dependencies will be added at the model qualification milestone.

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

Place a configured source below its owning book directory, for example `books/my-book/source/main.tex`.
The `book_id` in `book.yaml` must match the directory containing that configuration.

Run source ingestion from the project root:

```shell
.tools/bin/pixi run bilbo ingest books/my-book/book.yaml
```

The command emits an `ingest-summary/v1` JSON object on standard output.
It writes the canonical artifact to `work/my-book/manifests/book-document.json`.
It writes the chapter text, source references, warnings, and exclusions to `work/my-book/reports/extraction.md`.
Unchanged input produces byte-identical output files and checksums.

LaTeX is parsed through the locked Pandoc executable and ordinary `\input` or `\include` files below the source directory contribute to the source checksum.
Pandoc does not expose reliable LaTeX line positions in its JSON AST, so reports retain source paths without fabricated line numbers.
Born-digital PDFs are extracted page by page through PyMuPDF4LLM with OCR disabled.
An image-only or scanned PDF page exits with status 1, writes a failed extraction report, and does not write a partial canonical document.
Resolve scanned pages outside this milestone before rerunning ingestion.

Review `extraction.md` before downstream processing, paying particular attention to table order, equations, omissions, headers, footers, and adapter warnings.
Committed C2 fixtures and their reviewed golden outputs live under `tests/fixtures/`.
Run the ingestion integration checks without model downloads:

```shell
.tools/bin/pixi run pytest tests/integration/test_ingest_cli.py -v --no-cov
```
