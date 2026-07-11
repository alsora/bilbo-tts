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
