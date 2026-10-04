"""Unit tests for deterministic serialization and hashing."""

from __future__ import annotations

from pathlib import Path

import pytest

from drw.execution.context import RunContext
from drw.schema.serialization import canonical_json, content_hash, to_plain

pytestmark = pytest.mark.unit


def test_key_order_does_not_affect_canonical_form():
    a = {"b": 1, "a": [2, {"d": 4, "c": 3}]}
    b = {"a": [2, {"c": 3, "d": 4}], "b": 1}
    assert canonical_json(a) == canonical_json(b)
    assert content_hash(a) == content_hash(b)


def test_non_finite_floats_are_renderable():
    text = canonical_json({"nan": float("nan"), "inf": float("inf"), "neg": float("-inf")})
    assert "NaN" in text
    assert "Infinity" in text
    assert "-Infinity" in text


def test_to_plain_handles_path_and_dataclass():
    context = RunContext(run_id="r", experiment_id="e", workdir=Path("work"))
    plain = to_plain(context)
    assert plain["workdir"] == "work"
    assert plain["run_id"] == "r"


def test_content_hash_is_stable():
    assert content_hash({"a": 1}) == content_hash({"a": 1})
    assert content_hash({"a": 1}) != content_hash({"a": 2})
