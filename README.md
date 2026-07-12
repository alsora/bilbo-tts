# bilbo-tts

`bilbo-tts` is a reproducible local pipeline for generating Italian audiobooks.

A book flows through ordered, idempotent stages: source extraction, Italian normalization, chunking, resumable TTS synthesis, ASR round-trip verification, and chaptered M4B assembly.
Every stage writes checksum-validated manifests and readable review reports below the ignored `work/<book-id>/` workspace, and unchanged reruns are byte-identical no-ops.

## Setup

The initial development platform is Apple Silicon macOS.
Project dependencies are isolated with Pixi and do not rely on a system Python, FFmpeg, Pandoc, or libsndfile installation.

Bootstrap the pinned Pixi executable into the ignored project-local tools directory, then install the locked default environment:

```shell
./scripts/bootstrap-pixi.sh
.tools/bin/pixi install --locked
```

Inspect the active environment without downloading models:

```shell
.tools/bin/pixi run bilbo doctor
```

Model-specific environments are named `chatterbox`, `kokoro`, and `asr`.
Each environment has an exact dependency pin and remains isolated from the default development environment.
The Chatterbox candidate uses the official V3 PyTorch MPS implementation because no maintained V3 MLX port exists.
The Kokoro and Whisper candidates use MLX.

## Adding a book

Create one directory below `books/` with the complete source tree and a strict `book.yaml`:

```text
books/
  my-book/
    book.yaml
    source/
      main.tex
```

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
  model_config_path: config/qualification/kokoro-nicola-s120.yaml
```

Born-digital PDF sources are also supported with `format: pdf`.
The complete directory rules, configuration reference, private-book layout, extraction commands, and review checklist are documented in [Adding a book](docs/adding-a-book.md).

## Running the whole pipeline

`bilbo run` executes every stage on a book and publishes a reproducible build bundle:

```shell
.tools/bin/pixi run bilbo run books/my-book/book.yaml --project-root .
```

Repeat `--chapter` in manifest order to build one contiguous chapter scope, and use `--text-only` to stop after text qualification before any model stage:

```shell
.tools/bin/pixi run bilbo run books/my-book/book.yaml \
  --project-root . \
  --chapter chapter-0002 \
  --chapter chapter-0003 \
  --text-only
```

The full command requires a clean tracked working tree because the build bundle records the exact committed `HEAD`.
Outputs land below `work/<book-id>/`: stage reports under `reports/`, canonical manifests under `manifests/`, the final M4B under `media/`, and the build bundle under `deliverables/`.
After interruption or a recoverable failure, rerun the exact same command; valid artifacts are checksum-validated and reused.
The complete operating guide, including text-evidence review, selective regeneration, cache cleaning, bundle reproduction, and the listening checklist, is documented in [Running a book end to end](docs/running-a-book.md).

Individual stages can also be run and reviewed one at a time; see the stage documentation in the index below.

## Testing

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
No real model is imported by ordinary tests or `pixi run check`.
Opt-in hardware smoke tests for the real models require `BILBO_HARDWARE_TESTS=1` and are documented in [TTS qualification](docs/tts-qualification.md) and [Round-trip verification](docs/verification.md).

## Documentation

Operating guides:

- [Adding a book](docs/adding-a-book.md): book layout, `book.yaml` reference, extraction, and the extraction review checklist.
- [Running a book end to end](docs/running-a-book.md): the complete `bilbo run` operating guide from preflight to build bundle.
- [Italian normalization and chunking](docs/text-pipeline.md): the deterministic text stages and their review reports.
- [Pronunciation lexicons](docs/pronunciation-lexicons.md): reviewed pronunciation overrides and the correction workflow.
- [TTS qualification](docs/tts-qualification.md): candidate evaluation, smoke tests, ASR scoring, and blind listening.
- [Resumable synthesis](docs/synthesis.md): the `synthesize` stage, chunk selection, retries, and resumption.
- [Round-trip verification](docs/verification.md): the `verify` stage, thresholds, and human review decisions.
- [M4B assembly and media validation](docs/assembly.md): the `assemble` stage, pauses, loudness, and metadata.

Reference documents:

- [Design](docs/design.md): architecture, stable contracts, environment policy, model strategy, and normalization policy.
- [Implementation](docs/implementation.md): delivery milestones, verification gates, and checkpoint criteria.
- [Performance](docs/performance.md): performance evidence and measurement methodology.
