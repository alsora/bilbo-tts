# Pronunciation lexicons

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

## Overlay file format

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
`phoneme_override` is an optional reviewed phoneme sequence applied by the Kokoro adapter after G2P; see [Phoneme overrides](#phoneme-overrides-when-no-respelling-works).
Use `notes` to record what was wrong and why the replacement fixes it, because lexicons are reviewed data.
Unknown fields are rejected with an actionable validation error.

## Wiring an overlay into a book

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

## Crafting and verifying a correction

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

## Phoneme overrides when no respelling works

A few Italian pronunciations cannot be produced by any spelling, for example a plain voiced `dz` onset for `zero` or the long palatal lateral `ʎː` in `meglio`.
For those cases an entry in the shared `config/lexicons/kokoro-it.yaml` overlay combines a unique marker respelling with a reviewed phoneme sequence:

```yaml
  - entry_id: consonant-zero
    mode: literal
    pattern: zero
    spoken: dzzèro
    phoneme_override: dzˈɛro
    notes: Kokoro weakens its ordinary zero onset toward s; the reviewed dz sequence replaces the marker's phonemes after G2P.
```

Normalization rewrites the word to the marker `spoken` text as with any other entry.
When the Kokoro adapter sees a marker in the request text, it phonemizes the marker in isolation, then replaces that phoneme sequence with the `phoneme_override` value in the ordinary G2P output.
Deriving the source phonemes at synthesis time keeps the overlay as the single reviewed source of truth and cannot drift from the pinned espeak-ng behavior.

Craft the marker so it is unique, cannot occur in ordinary text, and already sounds close to the target, because the marker's ordinary rendering is kept wherever the replacement does not apply.
Replacement is best-effort: espeak-ng can render a marker differently inside a clause than in isolation, for example reducing the final unstressed vowel of `impegnando-si` mid-sentence, and those occurrences keep their ordinary phonemes.
Author the `phoneme_override` value in the same phoneme alphabet that the espeak-ng verification snippet above prints, and confirm the result with one short synthesis and a listening check.
The opt-in hardware test `tests/hardware/test_kokoro_smoke.py` pins the isolation-versus-clause-final derivation assumption for every override entry.

Two entries may share one marker only when they declare the same `phoneme_override`, and conflicting values are rejected at load time.
Because the override changes generated audio without changing the synthesis cache key, regenerate the chunks containing the marker after editing an override value.

Verification compares ASR transcripts against the final `spoken_text`, so a respelled loanword registers a small expected WER hit on chunks that contain it.
Treat that as known noise when reviewing verification reports rather than as a synthesis regression.

## Worked example: iterating on one word

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
