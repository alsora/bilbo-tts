# Resumable synthesis

Run synthesis only after the normalized text and chunking reports are approved.
A book selects its complete pinned model identity, voice, and settings through one candidate file:

```yaml
synthesis:
  model_config_path: config/qualification/kokoro-nicola-s120.yaml
  max_retries: 2
```

Production books currently use the interim Kokoro default shown above; a future return to Chatterbox changes only this path to `config/qualification/chatterbox.yaml`.
Run synthesis from the Pixi environment matching the selected engine:

```shell
.tools/bin/pixi run -e kokoro bilbo synthesize books/my-book/book.yaml
```

For an isolated private project, pass the same project root used by the text stages:

```shell
.tools/bin/pixi run -e kokoro bilbo synthesize \
  books/my-book/book.yaml \
  --project-root work/private-project
```

The stage processes chunks sequentially and loads the model only when selected audio must be generated.
Each chunk writes `work/<book-id>/audio/<chunk-id>/<cache-key>.wav` and an adjacent generation sidecar.
The current book state is recorded in `manifests/generation-manifest.json` and summarized in `reports/synthesis.md`.
Every existing pair is validated for identity, checksum, mono PCM16 format, sample rate, frame count, and duration before it is skipped.
An unchanged rerun is therefore a no-op and does not load model weights.

Restrict a run with repeatable chapter selection and inclusive chunk sequence bounds:

```shell
.tools/bin/pixi run -e kokoro bilbo synthesize books/my-book/book.yaml \
  --chapter chapter-0002 \
  --chunk-start 20 \
  --chunk-end 40
```

Combined selectors intersect.
Repeated `--chapter` values must be unique, contiguous, and supplied in chunk-manifest order.
Invalid, duplicate, reversed, gapped, or out-of-range selections fail before model loading.
Use `--failed` to select only chunks whose current cache identity has an exhausted TTS failure.
Use `--force` to regenerate otherwise valid selected chunks.
Automatic fallback is intentionally absent; switching a book between engines is a manual `model_config_path` change, and changing it regenerates all audio because the model identity is part of every chunk cache key.

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
