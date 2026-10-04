"""Unit tests: hashing is stable across processes and interpreter locations."""

from __future__ import annotations

import json
import subprocess
import sys

import pytest

from drw.execution.environment import environment_fingerprint, fingerprint_hash
from drw.schema.serialization import content_hash

pytestmark = pytest.mark.unit


def test_content_hash_is_stable_across_processes():
    data = {"b": 1, "a": [2.5, {"c": 3}], "d": "text"}
    local = content_hash(data)
    script = (
        "import json, sys;"
        "from drw.schema.serialization import content_hash;"
        "print(content_hash(json.loads(sys.argv[1])))"
    )
    proc = subprocess.run(
        [sys.executable, "-c", script, json.dumps(data)],
        capture_output=True,
        text=True,
        check=True,
    )
    assert proc.stdout.strip() == local


def test_environment_hash_ignores_interpreter_path():
    fingerprint = environment_fingerprint()
    baseline = fingerprint_hash(fingerprint)
    relocated = dict(fingerprint)
    relocated["python_executable"] = "C:/some/other/venv/python.exe"
    assert fingerprint_hash(relocated) == baseline


def test_environment_hash_changes_when_a_version_changes():
    fingerprint = dict(environment_fingerprint())
    fingerprint["numpy"] = "0.0.0-test"
    assert fingerprint_hash(fingerprint) != fingerprint_hash(environment_fingerprint())
