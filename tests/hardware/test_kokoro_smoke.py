from __future__ import annotations

import os
import platform
import sys
from pathlib import Path

import pytest

from bilbo_tts.qualification.candidates import candidate_path, load_tts_candidate
from bilbo_tts.qualification.corpus import default_corpus_path, load_corpus
from bilbo_tts.tts import TtsRequest
from bilbo_tts.tts.factory import create_tts_engine

ROOT = Path(__file__).parents[2]
pytestmark = [
    pytest.mark.hardware,
    pytest.mark.skipif(
        os.environ.get("BILBO_HARDWARE_TESTS") != "1",
        reason="set BILBO_HARDWARE_TESTS=1 to run model hardware tests",
    ),
]


def test_kokoro_generates_short_italian_excerpt_on_apple_silicon() -> None:
    assert sys.platform == "darwin"
    assert platform.machine() == "arm64"
    config = load_tts_candidate(candidate_path(ROOT, "kokoro"))
    excerpt = load_corpus(default_corpus_path(ROOT)).excerpts[0]
    engine = create_tts_engine(config, ROOT)

    health = engine.health()
    assert health.healthy, health.detail
    result = engine.synthesize(
        TtsRequest(
            spoken_text=excerpt.spoken_text,
            voice=config.voice,
            settings=config.settings,
        )
    )

    assert result.sample_rate_hz == 24_000
    assert result.frame_count > 0
