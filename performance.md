# TTS Performance Investigation

This document records the Chatterbox synthesis performance problem, the measurements taken, the optimizations attempted, and the resulting recommendations.
Durable architecture decisions belong to [`design.md`](design.md); this document owns the performance evidence and methodology.
All measurements were taken on the target 16 GB Apple Silicon Mac running macOS Tahoe 26.5.2.

## The problem

The pinned Chatterbox Multilingual V3 default synthesizes at a real-time factor (RTF) around 4 to 5, meaning one second of audio costs 4 to 5 seconds of generation.
The shortest target-book chapter (133 chunks) took roughly 80 minutes, and the full book (6,480 chunks, roughly 12.6 hours of audio) extrapolates to roughly 70 hours.
The approved fallback Kokoro-82M runs at RTF around 0.16, roughly 30 times faster, but human review strongly preferred the Chatterbox voice.

## Where the time goes

Fitting the per-chunk generation sidecars of the first synthesized chapter gave `generation_seconds ≈ 9.1 + 3.6 × audio_seconds`.
The dominant slope is the T3 autoregressive transformer: it emits 25 speech tokens per audio second at roughly 6 to 7 sampling steps per second, in float32, with a batch of 2 for classifier-free guidance (CFG).
The fixed ~9 s per chunk covers the s3gen vocoder, the Perth neural watermarker, and validation and I/O.

The central finding: the sampling loop is dispatch-bound, not compute-bound.
Each step takes roughly 140 ms, while the arithmetic and weight traffic of the ~0.5 B parameter model need only roughly 20 ms of that.
The remainder is per-step Python (logit processors, KV-cache bookkeeping) and MPS kernel-launch overhead.
Consequently, optimizations that only cheapen arithmetic (lower precision, smaller batch) yield far less than their theoretical factor.

## Pipeline fixes (landed, engine-independent)

- Synthesis retries now vary the seed per attempt, so deterministic failures no longer burn `max_retries` identical regenerations.
- `synthesize_book` validates each chunk's on-disk state once per run instead of re-reading and re-hashing every WAV a second time.
- PCM conversion packs all samples in one `struct.pack` call instead of per sample (~0.2 s saved per 10 s chunk).

## Optimizations tested

Each engine-level lever is a committed qualification candidate under `config/qualification/`, evaluated against the untouched `chatterbox` baseline.

### fp16 T3 (`chatterbox-fp16`) — no benefit, not recommended

The T3 transformer and built-in conditionals are cast to float16 after load.
A full-corpus comparison first suggested fp16 was twice as slow (1316 s versus 684 s), but that run was invalid: it started immediately after the 12-minute baseline run on an already-hot machine, and its per-sample RTF climbed monotonically from ~6 to ~16, the signature of thermal throttling.
A controlled same-excerpt comparison on a warm model measured ~6.9 steps/s for fp16 versus ~6.6 steps/s for float32: statistically indistinguishable.
This matches the dispatch-bound analysis: halving arithmetic cost does not move a ~140 ms step whose arithmetic share is ~20 ms.

### No-CFG turbo sampler (`chatterbox-turbo`) — real but modest, ~20-25%

The pinned upstream sampler always runs a batch of 2 for CFG; the adapter's turbo mode uses the upstream batch-1 `inference_turbo` path instead.
Measured with four diverse excerpts in ABBA order (baseline, turbo, turbo, baseline), warmup excluded:

| Excerpt | Baseline pass 1 | Turbo pass 2 | Turbo pass 3 | Baseline pass 4 |
| --- | --- | --- | --- | --- |
| prose-01 | 41.9 s (RTF 6.9) | 25.7 s (3.8) | 25.4 s (3.7) | 144.7 s (24.0) |
| percent-01 | 35.1 s (6.5) | 28.1 s (5.1) | 27.5 s (5.0) | 80.0 s (14.9) |
| finance-01 | 27.3 s (5.0) | 31.0 s (5.0) | 29.5 s (4.8) | 38.4 s (7.0) |
| long-01 | 97.1 s (6.9) | 72.3 s (5.3) | 89.8 s (6.6) | 124.6 s (8.9) |

Aggregate RTF: baseline ~6.3 (coolest pass) versus turbo ~4.7 to 5.3, roughly 20 to 25 percent faster.
Pass 4 collapsed because roughly 20 minutes of accumulated GPU load throttled the machine; it is unusable as a sample but makes the turbo win conservative, since turbo ran hotter than the pass-1 baseline.
Turbo changes sampling (no CFG blending, `top_k` instead of `min_p`), so its prosody requires blind listening before adoption.

### Watermark skip (`chatterbox-nowm`) — implemented, unmeasured

Replaces the per-chunk Perth neural watermark with an identity; expected to remove a few seconds of the fixed per-chunk overhead.
Skipping the responsible-AI watermark permanently is a policy decision to record in `design.md` upon adoption.

### Sentence packing (`chunking.pack_sentences`) — landed, opt-in, ~10-15%

Greedily merges adjacent whole sentences of one block up to `max_characters`, reducing the intro chapter from 133 to roughly 104 chunks (about 22 percent fewer) and amortizing the ~9 s fixed overhead.
Enabling it changes every chunk identity and regenerates all audio, so it must be decided before large synthesis runs.

## Measurement methodology

Sequential long runs on this laptop are not comparable: thermal throttling degrades later runs, as both the invalid fp16 corpus run and ABBA pass 4 demonstrate.
Compare candidates with short interleaved passes in ABBA order on a cool machine, or leave a cool-down gap of at least 10 minutes between runs.
Use [`scripts/ab_timing.py`](scripts/ab_timing.py) for such comparisons; it warms the model outside the timed region, prints one `TIMING` JSON line per excerpt, and saves WAVs with `--save-dir` for listening.
Full-corpus `qualify-tts` runs remain the source of record for RTF, memory, and ASR evidence, but only one per thermal session is trustworthy.

## Findings and recommendations

- Chatterbox on this hardware has a practical floor near RTF 4 to 5; the sampling loop is dispatch-bound, so precision and batch tricks cannot reach the theoretical 2x.
- The realistic stack of turbo (~20-25%) plus watermark skip plus sentence packing (~10-15%) is roughly 35 to 45 percent wall-time reduction, taking the 80-minute chapter to roughly 45 to 50 minutes and the full book from ~70 to ~40-45 hours.
- Turbo adoption is gated on blind listening (`prepare-tts-listening chatterbox chatterbox-turbo` after a full turbo corpus run on a cool machine).
- The fp16 variant should be considered rejected; its candidate configuration remains only as recorded evidence.
- The order-of-magnitude lever remains workflow, not tuning: use Kokoro (RTF ~0.16) for drafts and full-pipeline iteration, and reserve Chatterbox for final renders run in overnight batches.
- Unexplored options if more speed is ever required: `torch.compile` or graph capture on MPS (immature), reducing per-step Python in a vendored sampling loop, and upstream Chatterbox releases.
