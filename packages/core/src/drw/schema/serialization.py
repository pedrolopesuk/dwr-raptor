"""Deterministic serialization and content hashing.

Provenance in DRW depends on being able to hash an object and get the same digest
regardless of key insertion order, whitespace or platform. Everything that ends
up in an evidence package goes through :func:`canonical_json` /
:func:`content_hash`.

Non-finite floats (``nan``/``inf``) are rendered as the strings ``"NaN"``,
``"Infinity"`` and ``"-Infinity"`` so the output is always strict, valid JSON.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import math
from pathlib import Path
from typing import Any

from pydantic import BaseModel

__all__ = [
    "canonical_bytes",
    "canonical_json",
    "content_hash",
    "dumps_pretty",
    "sha256_hex",
    "to_plain",
]


def _normalize_scalar(value: Any) -> Any:
    if isinstance(value, bool):
        return value
    if isinstance(value, float):
        if math.isnan(value):
            return "NaN"
        if math.isinf(value):
            return "Infinity" if value > 0 else "-Infinity"
        return value
    if hasattr(value, "item") and not isinstance(value, (str, bytes)):
        # numpy scalar (np.float64, np.int64, ...)
        try:
            return _normalize_scalar(value.item())
        except (ValueError, AttributeError):  # pragma: no cover - defensive
            return value
    return value


def to_plain(obj: Any) -> Any:
    """Recursively convert models/arrays/mappings into JSON-ready primitives."""
    if obj is None or isinstance(obj, (str, bool, int, float)):
        return _normalize_scalar(obj)
    if isinstance(obj, BaseModel):
        return to_plain(obj.model_dump(mode="json"))
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        return {field.name: to_plain(getattr(obj, field.name)) for field in dataclasses.fields(obj)}
    if isinstance(obj, Path):
        return str(obj)
    if isinstance(obj, dict):
        return {str(key): to_plain(value) for key, value in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [to_plain(item) for item in obj]
    if isinstance(obj, (set, frozenset)):
        return sorted((to_plain(item) for item in obj), key=repr)
    if hasattr(obj, "tolist"):  # numpy array
        return to_plain(obj.tolist())
    if hasattr(obj, "item"):  # numpy scalar fallback
        return _normalize_scalar(obj.item())
    return obj


def canonical_json(obj: Any, *, indent: int | None = None) -> str:
    """Serialize ``obj`` with sorted keys and stable separators."""
    plain = to_plain(obj)
    separators = (",", ":") if indent is None else (",", ": ")
    return json.dumps(
        plain,
        sort_keys=True,
        ensure_ascii=False,
        allow_nan=False,
        indent=indent,
        separators=separators,
    )


def dumps_pretty(obj: Any) -> str:
    """Human-readable canonical JSON (sorted keys, two-space indent)."""
    return canonical_json(obj, indent=2)


def canonical_bytes(obj: Any) -> bytes:
    return canonical_json(obj).encode("utf-8")


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def content_hash(obj: Any) -> str:
    """Stable SHA-256 over the canonical form of ``obj``."""
    return sha256_hex(canonical_bytes(obj))
