"""Integration tests: reproduce a real stored experiment (read-only)."""

from __future__ import annotations

import hashlib
import json
from types import SimpleNamespace

import pytest

from drw.execution.runner import ExperimentValidationError, Runner
from drw.reproduce import ReproduceError, reproduce_experiment
from drw.schema.files import load_experiment_spec
from drw.schema.model import ModelRef
from drw.schema.result import RunRecord, RunStatus
from drw.store import ExperimentStore

pytestmark = pytest.mark.integration


@pytest.fixture
def stored(repo_root, tmp_path):
    store = ExperimentStore(tmp_path / "workspace")
    spec = load_experiment_spec(repo_root / "models/examples/predator-prey/experiment.yaml")
    result = Runner().run(spec)
    store.save(result)
    return store, result.experiment_id


def _snapshot(root) -> dict[str, str]:
    return {
        path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def test_reproduce_identical_and_preserves_stored_data(stored):
    store, experiment_id = stored
    directory = store.experiment_dir(experiment_id)
    before = _snapshot(directory)

    report = reproduce_experiment(experiment_id, rtol=0.0, atol=0.0, store=store)

    assert report.verdict == "identical"
    assert report.numerical == "identical"
    assert report.fresh_runs_persisted is False
    assert report.experiment_id == experiment_id
    assert len(report.reference_run_ids) == len(report.fresh_run_ids) == 2
    assert report.runs and all(run.comparable for run in report.runs)
    assert all(output.identical for run in report.runs for output in run.outputs)
    assert all(output.max_abs_delta == 0.0 for run in report.runs for output in run.outputs)
    assert report.provenance.spec_hash_match is True
    assert report.provenance.model_hash_match is True
    assert report.provenance.environment_hash_match is True

    # Read-only: the stored experiment, reference, evidence and artifacts are unchanged.
    assert _snapshot(directory) == before


def test_reproduce_detects_a_numerical_difference(stored):
    store, experiment_id = stored
    results_path = store.experiment_dir(experiment_id) / "results.json"
    results = json.loads(results_path.read_text(encoding="utf-8"))
    variant = results["runs"][1]["result"]["outputs"]["prey"]
    variant["values"] = [value + 1.0 for value in variant["values"]]
    results_path.write_text(json.dumps(results), encoding="utf-8")

    report = reproduce_experiment(experiment_id, rtol=1e-9, atol=1e-12, store=store)

    assert report.verdict == "different"
    changed = [
        output
        for run in report.runs
        for output in run.outputs
        if output.output == "prey" and output.status == "different"
    ]
    assert changed, "the tampered prey output should be classified as different"
    assert changed[0].passes_tolerance is False


def test_reproduce_reports_a_model_fingerprint_difference(stored):
    store, experiment_id = stored
    results_path = store.experiment_dir(experiment_id) / "results.json"
    results = json.loads(results_path.read_text(encoding="utf-8"))
    results["model_hash"] = "deadbeef"
    results_path.write_text(json.dumps(results), encoding="utf-8")

    report = reproduce_experiment(experiment_id, rtol=1e-9, atol=1e-12, store=store)

    assert report.provenance.model_hash_match is False
    assert any("model" in message for message in report.provenance.differences)
    # A hash difference is reported separately from the numerical verdict.
    assert report.verdict in ("identical", "equivalent_within_tolerance")


def test_reproduce_unknown_experiment(stored):
    store, _ = stored
    with pytest.raises(KeyError):
        reproduce_experiment("exp-000000000000", rtol=1e-6, atol=1e-9, store=store)


def test_reproduce_missing_reference_runs(stored):
    store, experiment_id = stored
    results_path = store.experiment_dir(experiment_id) / "results.json"
    results = json.loads(results_path.read_text(encoding="utf-8"))
    results["runs"] = []
    results_path.write_text(json.dumps(results), encoding="utf-8")

    with pytest.raises(ReproduceError):
        reproduce_experiment(experiment_id, rtol=1e-6, atol=1e-9, store=store)


def test_reproduce_invalid_tolerances_do_not_touch_the_store(stored):
    store, experiment_id = stored
    directory = store.experiment_dir(experiment_id)
    before = _snapshot(directory)
    with pytest.raises(ReproduceError):
        reproduce_experiment(experiment_id, rtol=-1.0, atol=0.0, store=store)
    assert _snapshot(directory) == before


def _failed_fresh_runs(experiment_id: str) -> list[RunRecord]:
    return [
        RunRecord(
            run_id=f"fresh-r{index:04d}",
            experiment_id=experiment_id,
            label="baseline" if index == 0 else "variant",
            status=RunStatus.FAILED,
            model_ref=ModelRef(model_id="predator-prey"),
            result=None,
        )
        for index in range(2)
    ]


def test_reproduce_execution_failure_preserves_stored_data(stored, monkeypatch):
    store, experiment_id = stored
    directory = store.experiment_dir(experiment_id)
    before = _snapshot(directory)

    monkeypatch.setattr(
        "drw.reproduce.Runner",
        lambda: SimpleNamespace(
            run=lambda spec, **kwargs: SimpleNamespace(runs=_failed_fresh_runs(experiment_id))
        ),
    )
    report = reproduce_experiment(experiment_id, rtol=1e-9, atol=1e-12, store=store)

    assert report.verdict == "execution_failed"
    assert report.numerical == "inconclusive"
    assert report.fresh_runs_persisted is False
    assert _snapshot(directory) == before


def test_reproduce_validation_failure_preserves_stored_data(stored, monkeypatch):
    store, experiment_id = stored
    directory = store.experiment_dir(experiment_id)
    before = _snapshot(directory)

    def boom(spec, **kwargs):
        raise ExperimentValidationError(())

    monkeypatch.setattr("drw.reproduce.Runner", lambda: SimpleNamespace(run=boom))
    with pytest.raises(ReproduceError):
        reproduce_experiment(experiment_id, rtol=1e-9, atol=1e-12, store=store)
    assert _snapshot(directory) == before
