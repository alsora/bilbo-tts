"""Dependency-free conversion of model samples to normalized PCM."""

from __future__ import annotations

import math
import struct
from collections.abc import Iterable
from numbers import Real

from bilbo_tts.tts.contracts import TtsError


def float_samples_to_pcm_s16le(samples: Iterable[object]) -> bytes:
    """Convert finite mono float samples to clipped signed PCM16."""

    integers: list[int] = []
    append = integers.append
    for index, value in enumerate(samples):
        if isinstance(value, bool) or not isinstance(value, Real):
            raise TtsError(
                f"audio sample {index} is not a scalar number; "
                "mono one-dimensional audio is required"
            )
        sample = float(value)
        if not math.isfinite(sample):
            raise TtsError(f"audio sample {index} is not finite")
        if sample <= -1.0:
            append(-32_768)
        elif sample >= 1.0:
            append(32_767)
        else:
            # int() truncates toward zero, matching the historical conversion
            # so previously checksummed WAV outputs stay byte-identical.
            append(int(sample * 32_768.0))
    if not integers:
        raise TtsError("model returned empty audio")
    return struct.pack(f"<{len(integers)}h", *integers)
