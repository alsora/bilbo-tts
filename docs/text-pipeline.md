# Italian normalization and chunking

Run these stages only after approving the extraction report described in [Adding a book](adding-a-book.md).

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
Specific Italian patterns such as dates, multi-part ratios, percentages, currencies, symbol-bearing ranges, section references, and bounded LaTeX equations run before generic number expansion.
Bounded LaTeX handling removes equation wrappers, labels, and spacing commands, unwraps simple `\text{...}` groups, and speaks common operators, arrows, identifier scripts, escaped percentages, and euros.
Decimal fractional parts are pronounced as grouped numbers, so `0,25%` becomes `zero virgola venticinque per cento`.
Unsupported mathematical notation remains visible and produces an `unresolved-math` warning instead of guessed speech.

Reviewed pronunciation replacement rules can rewrite `spoken_text` during normalization; their layering, file format, and correction workflow are documented in [Pronunciation lexicons](pronunciation-lexicons.md).

`chunk` validates the normalized artifact and its upstream book artifact.
It writes `work/my-book/manifests/chunk-manifest.json` and `work/my-book/reports/chunking.md`.
The manifest retains every stable source-derived identifier, character count, source mapping, and pause value.
The book-wide review report contains per-chapter metrics, forced intra-sentence split contexts, and ordering, limit, or pause anomalies.
Ordinary sentence boundaries and complete chunk text remain only in the manifest and focused chapter reports.
A sentence longer than `max_characters` splits first at punctuation and then at whitespace.
Forced splits avoid extra or very short chunks and prefer semicolons and colons over commas.
A single word longer than the configured limit fails with an actionable error rather than violating the limit.
Optional `chunking.pack_sentences: true` greedily merges adjacent whole sentences of one block up to `max_characters`, amortizing per-chunk synthesis overhead.
A packed chunk keeps the configured pause of its first sentence, and pauses between its merged sentences come from the model's prosody instead of `assembly.pauses.sentence_ms`.
Enabling packing changes every chunk identity, so an existing book regenerates all audio; decide before large synthesis runs.
Optional `chunking.split_at_colons: true` also ends a sentence at a colon followed by whitespace, so the next clause receives the shorter explicit `assembly.pauses.clause_ms` pause.
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
