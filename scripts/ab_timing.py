"""Time selected corpus excerpts for one TTS qualification candidate.

This is a measurement tool, not a pipeline stage: it prints one `TIMING`
JSON line per excerpt and optionally saves each result as a WAV for
listening. Model load and a warmup generation are excluded from timing.

Sequential long runs thermally throttle the target laptop and corrupt
comparisons, so compare candidates with short interleaved passes in ABBA
order (baseline, variant, variant, baseline); see performance.md.

Usage:
    .tools/bin/pixi run -e chatterbox python scripts/ab_timing.py \
        chatterbox prose-01,percent-01,finance-01,long-01 \
        --save-dir work/ab-audio
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from bilbo_tts.qualification.audio import pcm_wav_bytes
from bilbo_tts.qualification.candidates import candidate_path, load_tts_candidate
from bilbo_tts.qualification.corpus import default_corpus_path, load_corpus
from bilbo_tts.tts import TtsRequest
from bilbo_tts.tts.factory import create_tts_engine

WARMUP_TEXT = "Breve riscaldamento del modello."


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("candidate", help="Candidate name: a config/qualification/<name>.yaml stem")
    parser.add_argument("excerpts", help="Comma-separated corpus excerpt identifiers")
    parser.add_argument(
        "--save-dir",
        type=Path,
        default=None,
        help="Optional directory receiving one <candidate>-<excerpt>.wav per generation",
    )
    parser.add_argument(
        "--project-root",
        type=Path,
        default=Path("."),
        help="Repository root containing config/qualification/",
    )
    arguments = parser.parse_args()

    config = load_tts_candidate(candidate_path(arguments.project_root, arguments.candidate))
    corpus = {
        excerpt.excerpt_id: excerpt
        for excerpt in load_corpus(default_corpus_path(arguments.project_root)).excerpts
    }
    unknown = [name for name in arguments.excerpts.split(",") if name not in corpus]
    if unknown:
        parser.error(f"unknown corpus excerpts: {', '.join(unknown)}")
    engine = create_tts_engine(config, arguments.project_root)

    warmup = TtsRequest(spoken_text=WARMUP_TEXT, voice=config.voice, settings=config.settings)
    engine.synthesize(warmup)

    if arguments.save_dir is not None:
        arguments.save_dir.mkdir(parents=True, exist_ok=True)
    for excerpt_id in arguments.excerpts.split(","):
        excerpt = corpus[excerpt_id]
        request = TtsRequest(
            spoken_text=excerpt.spoken_text,
            voice=config.voice,
            settings=config.settings,
        )
        start = time.perf_counter()
        result = engine.synthesize(request)
        elapsed = time.perf_counter() - start
        record: dict[str, object] = {
            "candidate": arguments.candidate,
            "excerpt": excerpt_id,
            "generation_seconds": round(elapsed, 2),
            "audio_seconds": round(result.duration_seconds, 2),
            "rtf": round(elapsed / result.duration_seconds, 2),
        }
        if arguments.save_dir is not None:
            wav_path = arguments.save_dir / f"{arguments.candidate}-{excerpt_id}.wav"
            wav_path.write_bytes(pcm_wav_bytes(result))
            record["wav_path"] = str(wav_path)
        print("TIMING " + json.dumps(record), flush=True)


if __name__ == "__main__":
    main()
