"""Deterministic serialization and digest helpers."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from pydantic import BaseModel


def canonical_json_bytes(value: BaseModel | Any) -> bytes:
    """Serialize JSON-compatible data with one stable byte representation."""

    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json")
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def sha256_bytes(data: bytes) -> str:
    """Return a lowercase SHA-256 digest."""

    return hashlib.sha256(data).hexdigest()


def canonical_sha256(value: BaseModel | Any) -> str:
    """Hash the canonical JSON representation of a value."""

    return sha256_bytes(canonical_json_bytes(value))
