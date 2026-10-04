"""Integration test: spec -> runs -> differential analysis -> evidence package."""

from __future__ import annotations

import hashlib
import json

import pytest

from drw.execution.evidence import build_evidence_package
from drw.execution.runner import ExperimentValidationError, Runner
from drw.schema.files import load_experiment_spec

pytestmark = pytest.mark.integration


@pytest.fixture
def spec(repo_root):
    return load_experiment_spec(repo_root / "models" / "examples" / "predator-prey" / "experiment.yaml")


def test_experiment_runs_and_produces_comparisons(spec):
    result = Runner().run(spec)
    assert len(result.runs) == 2
    assert result.baseline.label == "baseline"
    assert all(run.succeeded for run in result.runs)
    # One comparison per (variant, output: prey, predator).
    assert len(result.comparisons) == 2
    for comparison in result.comparisons:
        assert comparison.alignment == "exact"
        assert comparison.metrics["max_abs_delta"] > 0.0
        assert len(comparison.delta) == len(comparison.reference)


def test_repeated_execution_is_reproducible(spec):
    first = Runner().run(spec)
    second = Runner().run(spec)
    assert first.experiment_id == second.experiment_id
    assert first.spec_hash == second.spec_hash
    assert first.model_hash == second.model_hash
    for a, b in zip(first.comparisons, second.comparisons, strict=True):
        assert a.metrics["max_abs_delta"] == pytest.approx(b.metrics["max_abs_delta"], rel=1e-12)
        assert a.delta == b.delta


def test_evidence_package_manifest_hashes_are_correct(spec, tmp_path):
    result = Runner().run(spec)
    manifest_path = build_evidence_package(result, tmp_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    assert manifest["n_runs"] == 2
    assert manifest["n_succeeded"] == 2
    assert manifest["n_failed"] == 0
    assert manifest["spec_hash"] == result.spec_hash
    assert (tmp_path / "report.md").exists()

    for entry in manifest["files"]:
        data = (tmp_path / entry["path"]).read_bytes()
        assert hashlib.sha256(data).hexdigest() == entry["sha256"]
        assert len(data) == entry["size_bytes"]


def test_run_budget_is_enforced_before_execution(spec):
    over_budget = spec.model_copy(
        update={"execution": spec.execution.model_copy(update={"max_runs": 1})}
    )
    with pytest.raises(ExperimentValidationError):
        Runner().run(over_budget)
