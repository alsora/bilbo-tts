# Content-stage fixtures

`books/tiny-latex` is a self-contained LaTeX book covering front matter, included files, headings, paragraphs, nested lists, a quotation, a footnote, a table, an equation, a caption, and a bibliography exclusion.
`books/tiny-pdf` is a deterministic born-digital PDF covering two pages, columns, headings, paragraphs, lists, a quotation, a table, a caption, repeated page furniture, and an image exclusion.
`books/tiny-scanned` is a deterministic image-only PDF used to prove that deferred OCR blocks canonical output.

The PDF generator scripts use only the locked PyMuPDF dependency and produce byte-identical files on repeated runs.
The files below `golden/` are complete artifact envelopes, deterministic stage summaries, and readable extraction, normalization, and chunking reports produced from reviewed fixture inputs.
Integration tests compare generated files byte for byte so extraction, normalization, chunking, or dependency changes require explicit review.

Regenerate ingestion goldens only after reviewing the fixture extraction:

```shell
.tools/bin/pixi run python tests/fixtures/update_ingest_goldens.py
```

Regenerate normalization and chunking goldens only after reviewing their spoken text, transformations, warnings, limits, and source mapping:

```shell
.tools/bin/pixi run python tests/fixtures/update_text_goldens.py
```
