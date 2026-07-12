# Running a book end to end

`bilbo run` executes the complete pipeline on a book: text stages, selected-scope text qualification, isolated synthesis, verification with bounded retries, chaptered M4B assembly, and a reproducible build bundle.
Omit `--chapter` to run the whole book, or repeat `--chapter` in manifest order to run one contiguous chapter scope.

The examples below use the milestone 8 qualification scope, which qualifies source chapters 2–6 only.
Their stable ordered scope is `chapter-0002`, `chapter-0003`, `chapter-0004`, `chapter-0005`, and `chapter-0006`.
The goal of that milestone is one chaptered five-chapter M4B, not five separate chapter files and not a whole-book M4B.
The commands below are operating instructions and do not assert that target generation or C8 listening approval has completed.

## Bootstrap and preflight

Run the bootstrap, locked install, environment check, and fast repository checks from the repository root:

```shell
./scripts/bootstrap-pixi.sh
.tools/bin/pixi install --locked
.tools/bin/pixi run bilbo doctor
.tools/bin/pixi run check
```

The examples below use `books/my-book/book.yaml` with the repository as the project root.
For a private project, replace only the configuration path and pass its established `--project-root` on every command.
The repeated chapter arguments must remain in exactly the order shown.

Run the exact text-only qualification for the target scope:

```shell
.tools/bin/pixi run bilbo run books/my-book/book.yaml \
  --project-root . \
  --chapter chapter-0002 \
  --chapter chapter-0003 \
  --chapter chapter-0004 \
  --chapter chapter-0005 \
  --chapter chapter-0006 \
  --text-only
```

This command always refreshes or validates the book-wide ingestion, normalization, and chunking artifacts before calculating selected-scope evidence.
It loads no TTS or ASR model and writes no media or build bundle.

## Interpret and review text evidence

Open `work/my-book/reports/text-only-qualification.md`.
Confirm that it names exactly the selected chapters and inspect every extraction warning, normalization warning, unresolved token, forced split, and chunk outlier.
The speech estimate is deterministic rather than measured audio duration.
It counts selected spoken-text words at 150 words per minute and adds every configured pause attached to a selected chunk.
The full-source exclusion count and document-level extraction warnings remain book-wide even though chapter metrics and review gates are selected-scope.
The canonical `book-document.json`, `normalized-document.json`, and `chunk-manifest.json` also remain book-wide.

Generate complete focused extraction and chunking reports for each selected chapter:

```shell
for chapter in \
  chapter-0002 chapter-0003 chapter-0004 chapter-0005 chapter-0006
do
  .tools/bin/pixi run bilbo review-extraction books/my-book/book.yaml \
    --project-root . \
    --chapter "$chapter"
  .tools/bin/pixi run bilbo review-chunking books/my-book/book.yaml \
    --project-root . \
    --chapter "$chapter"
done
```

The focused reports are written below `work/my-book/reports/review/`.
Resolve source or lexicon defects before model generation, then rerun the exact text-only command.
Treat a warning as cleared only when the corrected artifact no longer reports it or the reviewer explicitly accepts the documented behavior.

## Run the full build

Before the full command, ensure tracked repository files are committed and unchanged:

```shell
git status --short --untracked-files=no
```

The final bundle step rejects staged, modified, or deleted tracked files because its code provenance is the exact committed `HEAD`.
Untracked private source files do not fail that check, but the configured source, book configuration, lexicons, cover, and voice reference are still checksum-validated.
Do not remove or relocate untracked private inputs between text qualification and the full run.

Run the exact full command for the target scope:

```shell
.tools/bin/pixi run bilbo run books/my-book/book.yaml \
  --project-root . \
  --chapter chapter-0002 \
  --chapter chapter-0003 \
  --chapter chapter-0004 \
  --chapter chapter-0005 \
  --chapter chapter-0006
```

`bilbo run` validates book-wide text artifacts, qualifies the selected chapters, starts synthesis in the configured TTS Pixi environment, exits that process, runs ASR and bounded TTS retries in isolated processes, assembles one M4B, and publishes a deterministic build bundle.
It never keeps the TTS and ASR models resident at the same time.
Selected generation is complete only when the command reports no selected failures and verification reports every selected chunk as `accepted`.
Book-wide generation manifests may still identify missing audio outside the selected chapters, which does not fail the selected scope.

For `my-book` with the five-chapter scope, the selected M4B path is:

```text
work/my-book/media/my-book-chapter-0002-to-chapter-0006.m4b
```

The main operator evidence is written to:

```text
work/my-book/reports/text-only-qualification.md
work/my-book/reports/synthesis.md
work/my-book/reports/verification.md
work/my-book/reports/assembly.md
work/my-book/reports/run.md
work/my-book/manifests/generation-manifest.json
work/my-book/manifests/verification-manifest.json
work/my-book/manifests/assembly-manifest.json
work/my-book/deliverables/build-<sha256>/
```

For a private project root, prepend that root to the `work/<book-id>/...` paths.
The assembly report must show the exact selected scope, its ordered chapter markers, no unaccepted override, and passing duration, metadata, loudness, true-peak, and FFprobe checks.
The verification report must show zero selected `retryable` and `review` chunks before assembly.

## Review and selectively regenerate audio

Listen to every selected chunk named by a text warning, forced split, chunk outlier, verification reason code, retry, or manual review decision.
The verification report includes source text, spoken text, transcript, alignment, measurements, reason codes, and the generated WAV path for each selected chunk.
Also inspect `chunk-manifest.json` when mapping a text-only chunk identifier to its global sequence number.

Record an acceptable verification false positive with the reviewer name and a specific listening note:

```shell
.tools/bin/pixi run bilbo review-verification books/my-book/book.yaml \
  --project-root . \
  --chunk block-000001.s0000.p0000 \
  --action accept \
  --reviewer "Ada Autrice" \
  --note "Listened to the complete chunk; pronunciation and audio are correct."
```

Queue a flagged or listening-rejected chunk for deterministic regeneration:

```shell
.tools/bin/pixi run bilbo review-verification books/my-book/book.yaml \
  --project-root . \
  --chunk block-000001.s0000.p0000 \
  --action regenerate \
  --reviewer "Ada Autrice" \
  --note "Pronunciation is incorrect at the named term."
```

Rerun the exact full command after recording the decision.
The coordinator regenerates queued audio in the TTS process, invalidates generation-bound review evidence, reverifies the replacement in the ASR process, and rebuilds media only when its inputs changed.

For an operator-directed regeneration outside the review queue, look up the chunk's global `sequence` in `chunk-manifest.json` and force only that sequence:

```shell
.tools/bin/pixi run -e kokoro bilbo synthesize books/my-book/book.yaml \
  --project-root . \
  --chapter chapter-0002 \
  --chunk-start 20 \
  --chunk-end 20 \
  --force
```

Use the Pixi environment selected by the book instead of `kokoro` when another engine is configured.
After a direct forced synthesis, rerun the full command so verification, assembly, and bundle evidence are refreshed.

## Resume, rerun, and clean caches

After interruption or any recoverable failure, rerun the exact same command.
Valid text artifacts, generation sidecars and WAVs, verification attempts, media, and bundles are checksum-validated and reused.
Never repair generated manifests, sidecars, reports, or bundle files by hand.

Model-download caches may be removed while no Bilbo, Pixi, TTS, or ASR process is running:

```shell
rm -rf work/cache
```

The next model command recreates the cache and downloads the same pinned revisions.
Do not delete `work/<book-id>/audio/`, `work/<book-id>/verification/`, manifests, reports, media, or deliverables when the intent is only to clear model caches.

## Reproduce and inspect the build bundle

The bundle is stored at `work/my-book/deliverables/build-<sha256>/`, where the suffix is the canonical SHA-256 of `build-manifest.json`.
It contains the final M4B, `environment/pixi.lock`, book, TTS, and ASR configurations, the built-in and configured lexicons, six canonical pipeline manifests, and seven stage reports.
It also contains the configured cover and owned voice reference when present.
It does not contain the source tree, individual chunk WAVs, verification-attempt sidecars, model caches, or `reports/run.md`.
Every copied member appears in the manifest with its role and SHA-256.
The manifest also records the clean repository commit, source identity, model and license metadata, voice identity, selected chapters, and exact reproducible command as an argument array.

Reproduction requires a clean checkout of the recorded commit, the locked environment, and the original source at the configured path with the recorded source checksum.
Restore any private source separately because source bytes are intentionally not copied into the bundle.
From that checkout, execute the manifest's command array without reordering its repeated `--chapter` arguments:

```shell
.tools/bin/pixi run python - \
  work/my-book/deliverables/build-<sha256>/build-manifest.json <<'PY'
import json
import subprocess
import sys
from pathlib import Path

manifest = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
subprocess.run(manifest["reproducible_command"], check=True)
PY
```

An unchanged reproduction validates and reuses the same content-addressed directory.
Any missing, extra, changed, or symlinked bundle member causes validation to fail instead of silently reusing a tampered bundle.

## Manual C8 listening checklist

Checkpoint C8 remains awaiting human approval until a reviewer completes all of these checks:

1. Confirm that the M4B contains exactly `chapter-0002` through `chapter-0006` in source order and no other chapter.
2. Listen to the beginning and end of each selected chapter and every chapter transition.
3. Seek to every chapter marker in an audiobook-capable player and confirm its title and landing position.
4. Listen to every chunk flagged by text qualification, verification, retries, manual decisions, or known limitations.
5. Sample the beginning, middle, and end of each selected chapter plus representative sentence, paragraph, and clause joins.
6. Check pronunciation, intelligibility, pace, prosody, voice consistency, silence, clipping, repetition, truncation, and audible encoding artifacts.
7. Confirm title, author, narrator, subtitle, optional cover art, playback continuity, and remembered position behavior.
8. Compare the listened file checksum with `assembly-manifest.json` and the copy recorded in `build-manifest.json`.
9. Record the reviewer, date, player, listened regions, accepted limitations, and final approve or reject decision outside generated evidence.

Do not mark C8 complete merely because automated generation, verification, assembly, or bundling succeeds.
