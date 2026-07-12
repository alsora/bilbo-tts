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

Each environment has an exact dependency pin and remains isolated from the default development environment.
The Chatterbox candidate uses the official V3 PyTorch MPS implementation because no maintained V3 MLX port exists.
The Kokoro and Whisper candidates use MLX.

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
The overlay file format, placement rules, and correction workflow are documented in [Pronunciation lexicons](#pronunciation-lexicons).
`chunking.max_characters` is an explicit positive character limit; engine-specific phoneme limits are deferred until model qualification.
`synthesis.model_config_path` selects one reviewed candidate file under the repository's `config/qualification/` directory, which owns the complete pinned model identity, voice, and generation settings.
The path is repository-relative even for books in private project roots, so every book shares the same reviewed candidate files.
The optional `synthesis.max_retries` bounds regeneration attempts per chunk and defaults to 2.
The `fake` candidate selects the deterministic dependency-free engine used by committed integration fixtures; production books use the interim Kokoro default documented below.
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

## Italian normalization and chunking

Run these stages only after approving the extraction report.

```shell
.tools/bin/pixi run bilbo normalize books/my-book/book.yaml
.tools/bin/pixi run bilbo chunk books/my-book/book.yaml
```

For an isolated project root, pass the same `--project-root` option to both commands that was used for ingestion.
`normalize` validates the stored book artifact and configured lexicon checksums.
It writes `work/my-book/manifests/normalized-document.json` and `work/my-book/reports/normalization.md`.
The manifest preserves the complete display text, spoken text, and transformation audit trail.
The review report summarizes rules and warnings, omits unchanged warning-free blocks, and shows final spoken text with only the minimal span changed by each rule.
Normalization preserves typographic apostrophes and quotation marks produced by rendered source text.
Apostrophe and quote variants are canonicalized later for ASR comparison rather than rewritten in `spoken_text`.
Specific Italian patterns such as dates, ratios, percentages, currencies, ranges, section references, and bounded equations run before generic number expansion.
Decimal fractional parts are pronounced as grouped numbers, so `0,25%` becomes `zero virgola venticinque per cento`.
Unsupported mathematical notation remains visible and produces an `unresolved-math` warning instead of guessed speech.

`chunk` validates the normalized artifact and its upstream book artifact.
It writes `work/my-book/manifests/chunk-manifest.json` and `work/my-book/reports/chunking.md`.
The manifest retains every stable source-derived identifier, character count, source mapping, and pause value.
The full-book review report contains per-chapter metrics, forced intra-sentence split contexts, and ordering, limit, or pause anomalies.
Ordinary sentence boundaries and complete chunk text remain only in the manifest and focused chapter reports.
A sentence longer than `max_characters` splits first at punctuation and then at whitespace.
Forced splits avoid extra or very short chunks and prefer semicolons and colons over commas.
A single word longer than the configured limit fails with an actionable error rather than violating the limit.
Optional `chunking.pack_sentences: true` greedily merges adjacent whole sentences of one block up to `max_characters`, amortizing per-chunk synthesis overhead.
A packed chunk keeps the configured pause of its first sentence, and pauses between its merged sentences come from the model's prosody instead of `assembly.pauses.sentence_ms`.
Enabling packing changes every chunk identity, so an existing book regenerates all audio; decide before large synthesis runs.
Optional `chunking.split_at_colons: true` also ends a sentence at a colon followed by whitespace, so the next clause receives the explicit `assembly.pauses.sentence_ms` pause.
Use it when the selected engine renders colon pauses much shorter than a narrator would; Kokoro measures near 80 ms.
Time and ratio colons such as `12:30` are unaffected because they contain no whitespace, and enabling the option renumbers sentence identities so affected audio regenerates.

Generate the complete chunk and pause report for the representative chapter:

```shell
.tools/bin/pixi run bilbo review-chunking books/my-book/book.yaml \
  --chapter chapter-0002
```

The command writes `work/my-book/reports/review/chapter-0002-chunking.md`.
To complete checkpoint C3, review the focused extraction and chunking reports together with the compact normalization report.
Resolve or explicitly accept every warning, sample every transformation category, confirm each source block maps to chunks in order, and inspect the smallest and largest chunks.
Changing the source or lexicons makes downstream artifacts stale, so rerun `normalize` and then `chunk`.
Unchanged reruns are byte-identical.

Committed text-stage fixtures and reviewed goldens run without model downloads:

```shell
.tools/bin/pixi run pytest tests/integration/test_text_pipeline_cli.py -v --no-cov
```

### Pronunciation lexicons

Pronunciation lexicons are reviewed replacement rules that rewrite `spoken_text` during normalization.
They exist in two layers with different purposes.

The model-independent layer defines what a human Italian narrator would read aloud, such as acronym spellings and abbreviation expansions.
It consists of the always-active built-in `config/lexicons/finance-it.yaml` plus any book overlays that correct the spoken form itself.
The model-specific layer works around how one TTS engine mispronounces text that is already correct Italian, typically loanwords.
Keep those workarounds in overlay files named for the engine, such as `kokoro-it.yaml` or `chatterbox-it.yaml`.
An overlay lives either inside the book directory for book-specific corrections or in the repository's `config/lexicons/` directory, referenced with `scope: shared`, when the corrections are reusable across books.
The reviewed Kokoro corrections live in the shared `config/lexicons/kokoro-it.yaml`.

Use this placement rule when a word sounds wrong.
If the written form is not what should be spoken, for example `BCE` should be read as `bi ci e`, add a model-independent entry.
If a narrator would read the text exactly as written but the engine renders it badly, add an entry to that engine's overlay.
If both engines mispronounce a correct word, start with one entry per engine overlay, because the respelling that fixes one engine is usually not optimal for the other.
Promote a respelling to the model-independent layer only after listening confirms it works well for every qualified engine.

Overlay selection is by convention, not enforcement: the normalize stage applies every lexicon listed in `book.yaml` regardless of the configured engine.
This works because each book pins exactly one synthesis engine.
When switching a book to another engine, also swap the model-specific overlay entries in `normalization.lexicons`.

#### Overlay file format

Each lexicon is a YAML file with schema version `pronunciation-lexicon/v1`:

```yaml
schema_version: pronunciation-lexicon/v1
lexicon_id: my-book-kokoro-it
entries:
  - entry_id: loanword-management
    mode: literal
    pattern: management
    spoken: mànagement
    priority: 50
    case_sensitive: false
    word_boundaries: true
    notes: espeak-ng stresses the wrong syllable without the explicit accent.
```

`lexicon_id` is a short lowercase identifier and `entry_id` values must be unique within the file.
`mode` is `literal` or `regex`; a regex pattern must be valid and must not match empty text.
`spoken` is the constant replacement text; regex group references are not expanded.
`priority` defaults to 0, and entries apply in descending priority.
At equal priority, entries from later-listed overlays apply before earlier lexicons, so an overlay can take precedence over the built-in finance lexicon.
`case_sensitive` defaults to false.
`word_boundaries` defaults to true and prevents matches inside larger words.
Use `notes` to record what was wrong and why the replacement fixes it, because lexicons are reviewed data.
Unknown fields are rejected with an actionable validation error.

#### Wiring an overlay into a book

List each overlay with its checksum in `book.yaml`.
A book-scoped path resolves below the book directory, while `scope: shared` resolves below the repository's `config/lexicons/` directory:

```yaml
normalization:
  version: it-v1
  lexicons:
    - path: lexicons/my-book-it.yaml
      sha256: <64-character hex checksum of lexicons/my-book-it.yaml>
    - path: kokoro-it.yaml
      sha256: <64-character hex checksum of config/lexicons/kokoro-it.yaml>
      scope: shared
```

Compute the checksum from the exact file bytes:

```shell
shasum -a 256 config/lexicons/kokoro-it.yaml
```

Every edit to a lexicon file changes its checksum, so update the matching `sha256` value in `book.yaml` in the same change.
After a lexicon change, rerun `normalize`, `chunk`, and `synthesize`.
The synthesis cache key hashes each chunk's spoken text, so only chunks whose spoken text actually changed are regenerated.

#### Crafting and verifying a correction

Kokoro converts text to phonemes with espeak-ng, which honors written Italian accents, so a respelling deterministically controls stress and phonemes.
Verify a Kokoro respelling without generating audio by printing the exact phonemes the model will receive:

```shell
.tools/bin/pixi run -e kokoro python -c "
from misaki import espeak
print(espeak.EspeakG2P(language='it')('il mànagement')[0])"
```

Iterate on the spelling until the phoneme string is correct, then confirm with one short synthesis.

Chatterbox has no phoneme stage and reads raw text through a learned tokenizer, so a respelling only nudges the model.
Verify a Chatterbox entry by synthesizing one sentence containing the word and listening, then adjust the phonetic Italian respelling until it sounds right.
Accented phonetic respellings such as `compiùter` are a good starting point.

Verification compares ASR transcripts against the final `spoken_text`, so a respelled loanword registers a small expected WER hit on chunks that contain it.
Treat that as known noise when reviewing verification reports rather than as a synthesis regression.

#### Worked example: iterating on one word

This example fixes the loanword `duration`, which espeak-ng reads with Italian letter rules as `dʊrˈatjon`.

First compare the phonemes of several candidate respellings in one run:

```shell
.tools/bin/pixi run -e kokoro python - <<'EOF'
from misaki import espeak
g2p = espeak.EspeakG2P(language="it")
for spelling in ("duration", "durescion", "durèscion", "diurèscion"):
    print(f"{spelling:12} -> {g2p(spelling)[0]}")
EOF
```

Then generate short before/after audio snippets with the book's configured voice and speed, and pick the winner by ear:

```shell
.tools/bin/pixi run -e kokoro python - <<'EOF'
from pathlib import Path
from huggingface_hub import snapshot_download
from kokoro_mlx import KokoroTTS

snapshot = snapshot_download(
    repo_id="mlx-community/Kokoro-82M-bf16",
    revision="a71e4d38b236d968966a2002c4c895dbd12b1c3c",
)
tts = KokoroTTS.from_pretrained(snapshot)
out = Path("work/scratch")
out.mkdir(parents=True, exist_ok=True)
clips = {
    "before": "Duration, convessità e rischio di reinvestimento influenzano la sensibilità delle obbligazioni.",
    "after": "Durèscion, convessità e rischio di reinvestimento influenzano la sensibilità delle obbligazioni.",
}
for tag, text in clips.items():
    tts.save(text, str(out / f"duration-{tag}.wav"), voice="im_nicola", speed=1.2, language="it")
EOF
```

Use a full sentence rather than the bare word, because neighboring sounds and pace affect how the correction lands.
Keep the pinned model revision, voice, and speed identical to the book configuration so the snippet predicts production output.

Once a respelling wins, record it as a reviewed entry in the engine overlay:

```yaml
  - entry_id: loanword-duration
    mode: literal
    pattern: duration
    spoken: durèscion
    priority: 50
    case_sensitive: false
    word_boundaries: true
    notes: espeak-ng reads duration as Italian duratjon; the reviewed Italianized rendering was preferred over a closer English one.
```

Finally update the overlay's `sha256` in `book.yaml`, rerun `normalize` and `chunk`, and confirm the applied rule count in the normalization summary.
The transformation audit trail records each application as `lexicon.<lexicon_id>.<entry_id>`, and the next `synthesize` run regenerates only the chunks whose spoken text changed.

## TTS qualification

The fixed reviewed Italian corpus and exact candidate configurations live under `config/qualification/`.
Qualification commands select a candidate by name: the stem of a `config/qualification/<name>.yaml` file.
One engine can therefore have several qualified variants side by side, such as `chatterbox` and an experimental `chatterbox-fp16`, each with its own evidence under `work/tts-qualification/<name>/`.
Three committed experimental Chatterbox variants exist for speed evaluation against the pinned `chatterbox` baseline:
`chatterbox-fp16` runs the T3 transformer and built-in conditionals in float16;
`chatterbox-nowm` skips the Perth neural watermark;
`chatterbox-turbo` samples without classifier-free guidance through the upstream batch-1 turbo path.
The dtype and sampler experiments require the built-in voice.
None of them changes the pinned production default until its adoption is recorded in `design.md`.
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

## Resumable synthesis

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

Restrict a run with any combination of chapter and inclusive chunk sequence bounds:

```shell
.tools/bin/pixi run -e kokoro bilbo synthesize books/my-book/book.yaml \
  --chapter chapter-0002 \
  --chunk-start 20 \
  --chunk-end 40
```

Combined selectors intersect.
Invalid chapter identifiers and ranges fail before model loading.
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

## Round-trip verification

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

The current state is stored in `manifests/verification-manifest.json`.
Immutable generation-bound attempt records are stored below `verification/attempts/`.
The complete readable evidence is stored in `reports/verification.md`.
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

## M4B assembly and media validation

Run assembly only after every selected chunk has current generated audio and an `accepted` verification result.
Assembly runs in the default or base Pixi environment because FFmpeg and FFprobe are native base dependencies and no model is loaded.

Configure pauses, loudness targets and tolerances, and the mono AAC bitrate in `book.yaml`:

```yaml
assembly:
  pauses:
    sentence_ms: 250
    paragraph_ms: 600
    chapter_ms: 1500
  loudness_lufs: -18
  true_peak_db: -2
  loudness_tolerance_lu: 0.5
  true_peak_tolerance_db: 0.5
  aac_bitrate_kbps: 64
```

Pause values are copied into the chunk manifest by the chunk stage.
Changing pause values therefore requires rerunning `chunk` before assembly.
Assembly uses the stored per-chunk pause values rather than silently applying newer configuration to an old chunk manifest.

Assemble the complete book:

```shell
.tools/bin/pixi run bilbo assemble books/my-book/book.yaml
```

Assemble only the representative chapter:

```shell
.tools/bin/pixi run bilbo assemble books/my-book/book.yaml \
  --chapter chapter-0002
```

For an isolated private project, pass the same project root used by every earlier stage:

```shell
.tools/bin/pixi run bilbo assemble \
  books/my-book/book.yaml \
  --project-root work/private-project \
  --chapter chapter-0002
```

Full-book output is written to `work/<book-id>/media/<book-id>.m4b`.
Chapter-scoped output adds the stable chapter identifier to the filename.
The current canonical evidence is written to `manifests/assembly-manifest.json`, and the readable evidence is written to `reports/assembly.md`.

Assembly validates each WAV and checksum, streams lossless PCM and explicit silence into one timeline, derives sample-accurate chapter markers, applies two-pass EBU R128 loudness normalization, and performs one AAC encode.
The final M4B is not published until FFprobe confirms its codec, channel count, sample rate, duration, metadata, optional cover art, and chapter timestamps.
A post-encode FFmpeg measurement must satisfy the configured integrated-loudness and true-peak tolerances.
The manifest records exact inputs, commands, tool versions, loudness measurements, chapter ranges, probed media metadata, and the final checksum.
An unchanged rerun validates and reuses the existing output, while `--force` intentionally re-encodes it.

Missing, failed, corrupt, wrong-format, mixed-rate, or stale generation and verification artifacts always block assembly.
Non-accepted or missing verification results also block by default.
An exceptional build may include current generated audio with a non-accepted or missing result only when both `--allow-unaccepted` and a non-empty `--override-note` are supplied.
The manifest records the note and every affected chunk identifier.
This override never permits stale verification or invalid generated audio.

Presentation metadata maps the book title to M4B title and album tags, the author to artist and album-artist tags, the subtitle to the description tag, and the narrator to the composer tag.
When `metadata.cover_path` is configured, assembly attaches the JPEG or PNG as cover art.
Metadata and cover changes rebuild final media without invalidating synthesized chunks.

Run the model-free assembly checks with:

```shell
.tools/bin/pixi run pytest \
  tests/test_assembly.py \
  tests/integration/test_assembly_cli.py \
  -v --no-cov
```

To complete checkpoint C7, play the representative chapter M4B in an audiobook-capable player.
Listen to the chapter start and end, every structural transition, and representative joins.
Confirm title, author, optional cover, chapter seeking, and uninterrupted playback before approving the checkpoint.
