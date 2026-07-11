"""Dependency-free conversion of model samples to normalized PCM."""

from __future__ import annotations

import math
import struct
from collections.abc import Iterable
from numbers import Real

from bilbo_tts.tts.contracts import TtsError


def float_samples_to_pcm_s16le(samples: Iterable[object]) -> bytes:
    """Convert finite mono float samples to clipped signed PCM16."""

    pcm = bytearray()
    for index, value in enumerate(samples):
        if isinstance(value, bool) or not isinstance(value, Real):
            raise TtsError(
                f"audio sample {index} is not a scalar number; "
                "mono one-dimensional audio is required"
            )
        sample = float(value)
        if not math.isfinite(sample):
            raise TtsError(f"audio sample {index} is not finite")
        clipped = min(1.0, max(-1.0, sample))
        integer = min(32_767, max(-32_768, int(clipped * 32_768)))
        pcm.extend(struct.pack("<h", integer))
    if not pcm:
        raise TtsError("model returned empty audio")
    return bytes(pcm)
