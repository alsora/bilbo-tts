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
