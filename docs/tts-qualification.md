# TTS qualification

The fixed reviewed Italian corpus and exact candidate configurations live under `config/qualification/`.
Qualification commands select a candidate by name: the stem of a `config/qualification/<name>.yaml` file.
One engine can therefore have several qualified variants side by side, such as `chatterbox` and an experimental `chatterbox-fp16`, each with its own evidence under `work/tts-qualification/<name>/`.
Three committed experimental Chatterbox variants exist for speed evaluation against the pinned `chatterbox` baseline:
`chatterbox-fp16` runs the T3 transformer and built-in conditionals in float16;
`chatterbox-nowm` skips the Perth neural watermark;
`chatterbox-turbo` samples without classifier-free guidance through the upstream batch-1 turbo path.
The dtype and sampler experiments require the built-in voice.
None of them changes the pinned production default until its adoption is recorded in [`design.md`](design.md).
The evidence limitations, counterbalanced thermal-session methodology, persisted JSONL format, summary statistics, and separate profiling procedure are documented in [`performance.md`](performance.md).
Run candidate timing through `scripts/ab_timing.py compare` with an explicit `ABBA` or `BAAB` order, then use its `summarize` command only after both starting orders have completed in independent cool sessions.
The default development environment can run the deterministic fake candidate without importing or downloading a model.
Human review strongly preferred the Chatterbox Multilingual V3 voice, but its observed throughput varies materially with excerpt length and thermal state and remains impractical for full-book iteration.
The interim production default is therefore the much faster Kokoro `kokoro-nicola-s120` candidate: voice `im_nicola` at speed 1.2.
Chatterbox remains the long-term target while the performance investigation continues in parallel.
Both engines retain accent defects on some Italian words, which should be addressed only through reviewed model-specific pronunciation overrides.
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
Set `BILBO_CHATTERBOX_SMOKE_CANDIDATE=<name>` to smoke-test a committed Chatterbox variant before running its full corpus.
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
