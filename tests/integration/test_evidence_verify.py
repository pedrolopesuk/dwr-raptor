"""Integration tests: first-party verification of an evidence package."""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

import pytest

from drw.execution.evidence import (
    EvidenceVerificationError,
    build_evidence_package,
    verify_evidence,
)
from drw.execution.runner import Runner
from drw.schema.files import load_experiment_spec

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def built_package(tmp_path_factory, repo_root) -> Path:
    """A real evidence package, built once and copied per test."""
    root = tmp_path_factory.mktemp("evidence")
    spec = load_experiment_spec(repo_root / "models" / "examples" / "predator-prey" / "experiment.yaml")
    result = Runner().run(spec)
    build_evidence_package(result, root)
    return root


@pytest.fixture
def manifest(built_package, tmp_path) -> Path:
    destination = tmp_path / "package"
    shutil.copytree(built_package, destination)
    return destination / "manifest.json"


def _status(manifest_path: Path, name: str) -> str:
    report = verify_evidence(manifest_path)
    return next(a.status for a in report.artifacts if a.path == name)


def test_valid_package_verifies(manifest):
    report = verify_evidence(manifest)
    assert report.ok is True
    assert report.failed == 0
    assert report.verified == len(report.artifacts) == 4
    assert {a.path for a in report.artifacts} == {
        "experiment-spec.json",
        "model-schema.json",
        "results.json",
        "report.md",
    }
    assert all(a.status == "ok" for a in report.artifacts)
    assert report.extra_files == []
    assert report.experiment_id


def test_modified_file_is_detected(manifest):
    """Same size, different content ⇒ hash_mismatch (not size_mismatch)."""
    target = manifest.parent / "report.md"
    data = target.read_bytes()
    target.write_bytes(data[:-1] + bytes([data[-1] ^ 1]))

    report = verify_evidence(manifest)
    assert report.ok is False
    assert report.failed == 1
    assert _status(manifest, "report.md") == "hash_mismatch"


def test_size_mismatch_is_detected(manifest):
    target = manifest.parent / "results.json"
    target.write_bytes(target.read_bytes() + b" ")

    report = verify_evidence(manifest)
    assert report.ok is False
    assert _status(manifest, "results.json") == "size_mismatch"


def test_missing_file_is_detected(manifest):
    (manifest.parent / "experiment-spec.json").unlink()

    report = verify_evidence(manifest)
    assert report.ok is False
    assert _status(manifest, "experiment-spec.json") == "missing"


def test_extra_file_is_reported_but_not_verified(manifest):
    (manifest.parent / "untracked.txt").write_text("not part of the package", encoding="utf-8")

    report = verify_evidence(manifest)
    # Declared artifacts are all intact, so the package still verifies ...
    assert report.ok is True
    # ... but the undeclared file is surfaced and is NOT among the verified records.
    assert "untracked.txt" in report.extra_files
    assert "untracked.txt" not in {a.path for a in report.artifacts}


def test_path_escape_entry_is_rejected(manifest):
    data = json.loads(manifest.read_text(encoding="utf-8"))
    data["files"][0]["path"] = "../escaped.txt"
    manifest.write_text(json.dumps(data), encoding="utf-8")

    report = verify_evidence(manifest)
    assert report.ok is False
    assert report.artifacts[0].status == "invalid_path"


def test_malformed_manifest_raises(manifest):
    manifest.write_text("this is not json", encoding="utf-8")
    with pytest.raises(EvidenceVerificationError):
        verify_evidence(manifest)


def test_manifest_without_files_list_raises(manifest):
    manifest.write_text(json.dumps({"experiment_id": "exp-000000000000"}), encoding="utf-8")
    with pytest.raises(EvidenceVerificationError):
        verify_evidence(manifest)


def test_missing_manifest_raises(tmp_path):
    with pytest.raises(EvidenceVerificationError):
        verify_evidence(tmp_path / "does-not-exist" / "manifest.json")


def test_verification_is_read_only(manifest):
    before = {
        p.name: hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(manifest.parent.iterdir())
        if p.is_file()
    }
    verify_evidence(manifest)
    after = {
        p.name: hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(manifest.parent.iterdir())
        if p.is_file()
    }
    assert after == before
