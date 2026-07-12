# Round-trip verification

Configure the pinned ASR model, automatic quality-retry bound, and calibrated limits in each book:

```yaml
verification:
  model_config_path: config/qualification/asr.yaml
  max_auto_retries: 2
  thresholds:
    max_wer: 0.70
    max_cer: 0.85
    max_missing_prefix_words: 1
    max_missing_suffix_words: 1
    max_repeated_ngram_count: 0
    max_silence_ratio: 0.95
    max_clipped_sample_ratio: 0.001
    min_speaking_rate_wpm: 70
    max_speaking_rate_wpm: 260
```

The WER and CER limits accommodate the pinned Whisper model rendering spoken Italian numbers as digits in the reviewed Kokoro regression corpus.
They are supporting signals rather than the only acceptance rule.
Missing boundaries, excess repetition, silence, clipping, duration, and speaking rate are measured independently.

Run verification from the default environment after synthesis has exited:

```shell
.tools/bin/pixi run bilbo verify books/my-book/book.yaml \
  --chapter chapter-0002
```

For an isolated private project, use the same project root as the earlier stages:

```shell
.tools/bin/pixi run bilbo verify \
  books/my-book/book.yaml \
  --project-root work/private-project \
  --chapter chapter-0002
```

The public command is a lightweight coordinator.
It starts one ASR child in the `asr` environment, waits for that process to exit, and only then starts one engine-specific TTS child when retryable chunks exist.
This ordering prevents the Whisper and TTS models from sharing unified memory.
Each quality retry advances the recorded deterministic seed offset and runs all queued chunks in one TTS model load.
Automatic retries stop at `verification.max_auto_retries`.
Repeat `--chapter` in manifest order to verify one contiguous multi-chapter scope.

The merged current state is stored in `manifests/verification-manifest.json` in complete chunk-manifest order.
Immutable generation-bound attempt records are stored below `verification/attempts/`.
The readable evidence for the most recent selected scope is stored in `reports/verification.md`.
The report includes source text, spoken text, transcript, alignment, WER, CER, audio measurements, reason codes, checksums, retry numbers, and review decisions.
An unchanged rerun reuses every matching attempt without loading Whisper.

`accepted` chunks need no action.
`retryable` chunks are regenerated automatically while the retry budget remains.
`review` chunks require listening and an explicit decision.
Human listening may also mark an automatically accepted chunk for regeneration when ASR misses a pronunciation or acoustic defect.
Record a reviewed false positive with:

```shell
.tools/bin/pixi run bilbo review-verification \
  books/my-book/book.yaml \
  --chunk block-000001.s0000.p0000 \
  --action accept \
  --reviewer "Ada Autrice" \
  --note "Listened to the complete chunk; the audio is correct."
```

Use `--action regenerate` to authorize another deterministic attempt after the automatic bound.
Every decision is bound to the exact generation checksum, so regenerating audio makes the previous decision stale.
Do not edit verification manifests, attempt records, or reports by hand.

Run the model-free verification checks with:

```shell
.tools/bin/pixi run pytest \
  tests/test_verification.py \
  tests/test_verification_process.py \
  tests/integration/test_verification_stage.py \
  -v --no-cov
```

Run the opt-in real Whisper smoke test with:

```shell
BILBO_HARDWARE_TESTS=1 .tools/bin/pixi run -e asr pytest \
  tests/hardware/test_whisper_smoke.py -v --no-cov
```
