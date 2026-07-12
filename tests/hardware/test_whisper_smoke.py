from __future__ import annotations

import os
import platform
import sys
from pathlib import Path

import pytest

from bilbo_tts.asr import MODEL_ID, MODEL_REVISION, MlxWhisperTranscriber
from bilbo_tts.qualification.audio import validate_wav_bytes
from bilbo_tts.qualification.candidates import candidate_path, load_asr_candidate

ROOT = Path(__file__).parents[2]
pytestmark = [
    pytest.mark.hardware,
    pytest.mark.skipif(
        os.environ.get("BILBO_HARDWARE_TESTS") != "1",
        reason="set BILBO_HARDWARE_TESTS=1 to run model hardware tests",
    ),
]


def test_whisper_transcribes_existing_tts_wav_on_apple_silicon() -> None:
    assert sys.platform == "darwin"
    assert platform.machine() == "arm64"
    configured_path = os.environ.get("BILBO_WHISPER_SMOKE_WAV")
    wav_path = (
        Path(configured_path).expanduser()
        if configured_path
        else ROOT / "work" / "tts-qualification" / "kokoro" / "audio" / "prose-01.wav"
    )
    assert wav_path.is_file(), (
        f"ASR smoke-test WAV is missing: {wav_path}. Complete Kokoro qualification or set "
        "BILBO_WHISPER_SMOKE_WAV to an existing qualification WAV"
    )
    config = load_asr_candidate(candidate_path(ROOT, "asr"))

    validate_wav_bytes(wav_path.read_bytes())
    transcript = MlxWhisperTranscriber(config).transcribe(wav_path)

    assert config.model_id == MODEL_ID
    assert config.revision == MODEL_REVISION
    assert transcript.strip()
