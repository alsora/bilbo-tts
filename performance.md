# TTS Performance Investigation

This document records the Chatterbox synthesis performance problem, the measurements taken, the optimizations attempted, and the resulting recommendations.
Durable architecture decisions belong to [`design.md`](design.md); this document owns the performance evidence and methodology.
All measurements were taken on the target 16 GB Apple Silicon Mac running macOS Tahoe 26.5.2.

## The problem

Pinned Chatterbox Multilingual V3 throughput varies materially with excerpt length and thermal state: warmed corpus excerpts measured near RTF 6, while longer book chunks amortize more fixed overhead.
The private target-book estimate remains roughly 80 minutes for its shortest 133-chunk chapter and roughly 60 to 70 hours for the 6,480-chunk full book, but committed artifacts do not independently reproduce those totals.
The approved Kokoro-82M candidates have measured near RTF 0.11 to 0.16 depending on voice and speed, an order of magnitude faster, but human review strongly preferred the Chatterbox voice.

## Where the time goes

Fitting private per-chunk timing logs from the first synthesized chapter gave `generation_seconds ≈ 9.1 + 3.6 × audio_seconds`.
Current `GenerationRecord` sidecars do not persist `generation_seconds`, so the fit is recorded evidence rather than independently reproducible from committed artifacts.
The dominant slope is the T3 autoregressive transformer: it emits 25 speech tokens per audio second at roughly 6 to 7 sampling steps per second, in float32, with a batch of 2 for classifier-free guidance (CFG).
The fitted ~9 s intercept is not phase attribution.
With the current timer it may include fixed model work, S3Gen, the Perth neural watermarker, and PCM conversion, but it excludes WAV validation and disk persistence.

The working hypothesis is that the sampling loop is predominantly dispatch-bound rather than arithmetic-bound.
Each observed step takes roughly 140 ms, while a theoretical arithmetic and weight-traffic estimate for the ~0.5 B parameter model is roughly 20 ms.
The gap is consistent with per-step Python, logit processing, KV-cache bookkeeping, synchronization, and MPS kernel-launch overhead, but no committed phase profile currently divides it among those causes.
The measured fp16 result shows that cheaper T3 arithmetic alone did not provide its theoretical factor on this configuration.

## Pipeline fixes (landed, engine-independent)

- Synthesis retries now vary the seed per attempt, so deterministic failures no longer burn `max_retries` identical regenerations.
- `synthesize_book` validates each chunk's on-disk state once per run instead of re-reading and re-hashing every WAV a second time.
- PCM conversion packs all samples in one `struct.pack` call instead of per sample (~0.2 s saved per 10 s chunk).

## Optimizations tested

Each engine-level lever is a committed qualification candidate under `config/qualification/`, evaluated against the untouched `chatterbox` baseline.

### fp16 T3 (`chatterbox-fp16`) — no benefit, not recommended

The T3 transformer and built-in conditionals are cast to float16 after load.
A full-corpus comparison first suggested fp16 was twice as slow (1316 s versus 684 s), but that run was invalid: it started immediately after the 12-minute baseline run on an already-hot machine, and its per-sample RTF climbed monotonically from ~6 to ~16, consistent with thermal throttling.
A controlled same-excerpt comparison on a warm model measured ~6.9 steps/s for fp16 versus ~6.6 steps/s for float32, too small and insufficiently replicated to justify adoption.
This is consistent with the dispatch-heavy hypothesis but does not establish the theoretical arithmetic share.

### No-CFG turbo sampler (`chatterbox-turbo`) — promising, effect not yet precise

The pinned upstream sampler always runs a batch of 2 for CFG; the adapter's turbo mode uses the upstream batch-1 `inference_turbo` path instead.
The original experiment used four diverse excerpts in manually orchestrated ABBA order, with warmup excluded:

| Excerpt | Baseline pass 1 | Turbo pass 2 | Turbo pass 3 | Baseline pass 4 |
| --- | --- | --- | --- | --- |
| prose-01 | 41.9 s (RTF 6.9) | 25.7 s (3.8) | 25.4 s (3.7) | 144.7 s (24.0) |
| percent-01 | 35.1 s (6.5) | 28.1 s (5.1) | 27.5 s (5.0) | 80.0 s (14.9) |
| finance-01 | 27.3 s (5.0) | 31.0 s (5.0) | 29.5 s (4.8) | 38.4 s (7.0) |
| long-01 | 97.1 s (6.9) | 72.3 s (5.3) | 89.8 s (6.6) | 124.6 s (8.9) |

Aggregate RTF was baseline ~6.3 (coolest pass) versus turbo ~4.7 to 5.3.
The table's same-text generation times imply roughly 18 percent aggregate wall-time reduction across the two turbo passes, with high excerpt-level variance and one slower excerpt.
Pass 4 collapsed after roughly 20 minutes of accumulated GPU load, so this historical run does not provide a valid bracketing baseline or a confidence interval.
Treat the result as evidence that turbo is promising, not as a precise 20-to-25-percent estimate.
Turbo changes decoder behavior beyond CFG removal: it uses `top_k` instead of `min_p`, and the pinned upstream `inference_turbo` loop omits the learned per-speech-token positional embedding used by the default loop.
Its prosody and stability therefore require blind listening before adoption, and a faithful batch-1 baseline loop remains a useful separate experiment.

### Watermark skip (`chatterbox-nowm`) — implemented, unmeasured

Replaces the per-chunk Perth neural watermark with an identity; the intended saving remains unmeasured and must not be assigned from the regression intercept.
Skipping the responsible-AI watermark permanently is a policy decision to record in `design.md` upon adoption.

### Sentence packing (`chunking.pack_sentences`) — landed, opt-in, expected ~5-6% on the measured chapter

Greedily merges adjacent whole sentences of one block up to `max_characters`, reducing the intro chapter from 133 to roughly 104 chunks (about 22 percent fewer) and amortizing the ~9 s fixed overhead.
Applying the fitted fixed overhead directly gives roughly 264 seconds saved from an 80-minute chapter, or about 5.5 percent; the earlier 10-to-15-percent estimate was too high.
The whole-book benefit depends on the actual packed chunk count and must not be extrapolated from this chapter alone.
Enabling it changes every chunk identity and regenerates all audio, so it must be decided before large synthesis runs.

## Measurement methodology

Benchmarking and profiling answer different questions and must be run separately.
Benchmark runs measure candidate-level wall time without profiler instrumentation.
Profile runs identify Python and MPS operator costs but perturb execution, especially when per-dispatch synchronization is enabled.

Sequential long runs on this laptop are not directly comparable because thermal throttling degrades later runs, as both the invalid fp16 corpus run and the historical ABBA pass 4 demonstrate.
One thermal session must use either ABBA or BAAB order, and the next independent cool session must use the opposite order so each candidate starts equally often.
A fixed cool-down is only a fallback; elapsed time alone does not prove that temperature and clock limits returned to their starting state.
The timing evidence records `pmset -g therm` snapshots where available, but absence of a reported thermal warning is not proof of equal silicon temperature.
Do not combine sessions with different candidate pairs in one evidence file.

Run one counterbalanced session from the matching model environment:

```sh
.tools/bin/pixi run -e chatterbox python scripts/ab_timing.py compare \
  chatterbox chatterbox-turbo \
  prose-01,percent-01,finance-01,long-01 \
  --order ABBA \
  --output work/ab-results/chatterbox-vs-turbo.jsonl \
  --save-dir work/ab-audio
```

After the machine has returned to a comparable cool state, run a second session with `--order BAAB` and append it to the same output.
Use `--cooldown-seconds` only when a measured thermal-stability check is unavailable and record that limitation with the result.

The comparison tool runs every pass in a fresh subprocess, performs one untimed warmup that includes lazy model loading, explicitly synchronizes MPS at sample boundaries, and writes one versioned JSONL record per session, pass, and sample.
Records include candidate and corpus hashes, model and code revisions, package versions, repository state, host metadata, thermal snapshots, peak RSS, exact unrounded timings, and pass-specific WAV paths.
Saved WAV encoding occurs after the timed region and pass-specific paths prevent later passes from overwriting listening evidence.

Summarize only complete four-pass sessions:

```sh
.tools/bin/pixi run -e chatterbox python scripts/ab_timing.py summarize \
  work/ab-results/chatterbox-vs-turbo.jsonl
```

Use paired same-text wall-time reduction as the primary throughput result.
Report RTF separately because candidate changes can alter output duration and make RTF move differently from elapsed generation time.
The summary takes the median of each candidate's two passes for every excerpt, aggregates those medians within each thermal session, then reports the median session-level reduction with a deterministic percentile-bootstrap 95 percent interval.
Do not use a summary with only one thermal session as a precise effect estimate.

Use a separate profile run when investigating the sampling loop:

```sh
.tools/bin/pixi run -e chatterbox python scripts/ab_timing.py profile \
  chatterbox prose-01 \
  --python-profile work/profiles/chatterbox-prose-01.prof \
  --mps-signposts
```

Capture the emitted MPS OS Signposts with Instruments or the macOS logging tools while the profile command runs.
Add `--wait-until-completed` only when a serialized dispatch timeline is required, because it materially slows execution and invalidates benchmark timing.
Inspect the Python profile and MPS trace for T3 prefill, per-token decoding, logit processing, KV-cache operations, S3Gen, watermarking, and PCM conversion before assigning regression slope or intercept to specific components.

Full-corpus `qualify-tts` runs remain the source of record for audio, ASR, and memory qualification.
They are not directly comparable to warmed A/B samples because the first qualification excerpt includes lazy model loading and a long corpus run experiences internal thermal drift.
Commit sanitized aggregate summaries needed for durable decisions; gitignored `work/` artifacts alone are not reproducible evidence.

## Findings and recommendations

- The available measurements are consistent with a dispatch-heavy sampling loop, but no committed phase profile establishes the claimed ~20 ms arithmetic share or a hard RTF floor.
- Turbo is promising, watermark skip is unmeasured, and sentence packing predicts about 5 to 6 percent on the measured chapter; no combined stack has yet justified the earlier 35-to-45-percent projection.
- Turbo adoption is gated on blind listening (`prepare-tts-listening chatterbox chatterbox-turbo` after a full turbo corpus run on a cool machine).
- The fp16 variant should be considered rejected; its candidate configuration remains only as recorded evidence.
- The order-of-magnitude lever remains workflow, not tuning: use Kokoro for drafts and full-pipeline iteration, and reserve Chatterbox for final renders run in overnight batches.
- Unexplored options include a faithful batch-1 decoder, static KV and token buffers, reduced or CPU-fused logit processing, model-level chunk batching, S3Gen step and dtype experiments, newer PyTorch MPS runtimes, MLX compatibility checks, and remote CUDA or NVIDIA NIM execution.
