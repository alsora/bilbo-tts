# M4B assembly and media validation

Run assembly only after every selected chunk has current generated audio and an `accepted` verification result.
Assembly runs in the default or base Pixi environment because FFmpeg and FFprobe are native base dependencies and no model is loaded.

Configure pauses, loudness targets and tolerances, and the mono AAC bitrate in `book.yaml`:

```yaml
assembly:
  pauses:
    clause_ms: 150
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

Assemble every chapter represented in the book-wide chunk manifest:

```shell
.tools/bin/pixi run bilbo assemble books/my-book/book.yaml
```

Assemble one representative chapter:

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
A contiguous multi-chapter output is written to `work/<book-id>/media/<book-id>-<first-chapter-id>-to-<last-chapter-id>.m4b`.
The current canonical evidence is written to `manifests/assembly-manifest.json`, and the readable evidence is written to `reports/assembly.md`.

Assembly validates each WAV and checksum, streams lossless PCM and explicit silence into one timeline, derives sample-accurate chapter markers, applies two-pass EBU R128 loudness normalization, and performs one AAC encode.
The final M4B is not published until FFprobe confirms its codec, channel count, sample rate, duration, metadata, optional cover art, and chapter timestamps.
A post-encode FFmpeg measurement must satisfy the configured integrated-loudness and true-peak tolerances.
The second pass reserves the configured true-peak tolerance as AAC encode headroom because lossy encoding can raise inter-sample peaks.
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
