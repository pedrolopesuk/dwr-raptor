"""Integration tests for the JSON bridge and the experiment store."""

from __future__ import annotations

import json
import os
import subprocess
import sys

import pytest

from drw.api import handle
from drw.execution.runner import Runner
from drw.schema.experiment import ExperimentSpec
from drw.store import ExperimentStore

pytestmark = pytest.mark.integration


def _call(request: dict, store: ExperimentStore) -> dict:
    return handle(request, store=store)


@pytest.fixture
def store(tmp_path) -> ExperimentStore:
    return ExperimentStore(tmp_path / "workspace")


@pytest.fixture
def sample_spec(store) -> dict:
    response = _call({"op": "sample_experiment", "params": {}}, store)
    assert response["ok"]
    return response["data"]["spec"]


def test_list_models_and_describe(store):
    models = _call({"op": "list_models", "params": {}}, store)["data"]["models"]
    ids = {m["model_id"] for m in models}
    assert {"oscillator", "predator-prey", "lorenz"} <= ids

    described = _call(
        {"op": "describe_model", "params": {"model_id": "predator-prey"}}, store
    )["data"]
    names = {p["name"] for p in described["schema"]["parameters"]}
    assert {"alpha", "beta", "prey0", "predator0"} <= names
    assert described["model_hash"]


def test_describe_unknown_model_is_not_found(store):
    response = _call({"op": "describe_model", "params": {"model_id": "nope"}}, store)
    assert response["ok"] is False
    assert response["error"]["code"] == "not_found"


def test_unknown_op(store):
    response = _call({"op": "explode", "params": {}}, store)
    assert response["ok"] is False
    assert response["error"]["code"] == "unknown_op"


def test_sample_experiment_is_valid(store, sample_spec):
    response = _call({"op": "validate", "params": {"spec": sample_spec}}, store)
    assert response["ok"] is True
    assert response["data"]["ok"] is True
    assert response["data"]["estimate"]["total_runs"] == 2


@pytest.mark.parametrize("model_id", ["oscillator", "lorenz", "predator-prey"])
def test_every_registered_model_seeds_a_valid_experiment(store, model_id):
    """Model-agnostic creation: every registered model can seed and validate."""
    response = _call({"op": "sample_experiment", "params": {"model_id": model_id}}, store)
    assert response["ok"] is True
    spec = response["data"]["spec"]
    assert spec["model_ref"]["model_id"] == model_id
    assert spec["baseline"]
    assert spec["factors"]

    validation = _call({"op": "validate", "params": {"spec": spec}}, store)
    assert validation["ok"] is True
    assert validation["data"]["ok"] is True, validation["data"]["diagnostics"]
    assert validation["data"]["estimate"]["total_runs"] == 2


@pytest.mark.parametrize("model_id", ["oscillator", "lorenz", "predator-prey"])
def test_every_registered_model_executes_through_the_bridge(store, model_id):
    """Model-agnostic execution: the same engine path runs any registered model."""
    spec = _call(
        {"op": "sample_experiment", "params": {"model_id": model_id}}, store
    )["data"]["spec"]
    run = _call({"op": "run", "params": {"spec": spec}}, store)
    assert run["ok"] is True, run
    data = run["data"]
    assert data["model_ref"]["model_id"] == model_id
    assert len(data["runs"]) == 2
    assert all(record["status"] == "succeeded" for record in data["runs"]), data["runs"]
    assert data["comparisons"]  # the differential artifacts are produced for every model


def test_validate_reports_actionable_errors(store, sample_spec):
    bad = json.loads(json.dumps(sample_spec))
    bad["factors"][0]["values"] = [999.0]  # far beyond the parameter bounds
    response = _call({"op": "validate", "params": {"spec": bad}}, store)
    assert response["ok"] is True  # the request succeeded ...
    assert response["data"]["ok"] is False  # ... but the spec is invalid
    codes = {d["code"] for d in response["data"]["diagnostics"]}
    assert "factor_out_of_bounds" in codes


def test_malformed_spec_is_rejected(store):
    response = _call({"op": "validate", "params": {"spec": {"hypothesis": "h"}}}, store)
    assert response["ok"] is False
    assert response["error"]["code"] == "invalid_spec"


def test_run_persists_and_reloads_unchanged_spec(store, sample_spec):
    run = _call({"op": "run", "params": {"spec": sample_spec}}, store)
    assert run["ok"] is True
    data = run["data"]
    assert data["experiment_id"].startswith("exp-")
    assert len(data["runs"]) == 2
    assert data["isolation"] == "subprocess"

    listed = _call({"op": "list_experiments", "params": {}}, store)["data"]["experiments"]
    assert [e["experiment_id"] for e in listed] == [data["experiment_id"]]

    loaded = _call(
        {"op": "get_experiment", "params": {"experiment_id": data["experiment_id"]}}, store
    )["data"]["experiment"]
    # Reopening returns the exact stored spec, not a recomputed one.
    assert loaded["spec"] == json.loads(json.dumps(sample_spec))


def test_run_metrics_match_the_python_core(store, sample_spec):
    run = _call({"op": "run", "params": {"spec": sample_spec}}, store)["data"]

    spec = ExperimentSpec.model_validate(sample_spec)
    direct = Runner().run(spec)
    direct_metrics = {
        (c.variant_run_id, c.output): c.metrics["max_abs_delta"] for c in direct.comparisons
    }
    bridge_metrics = {
        (c["variant_run_id"], c["output"]): c["metrics"]["max_abs_delta"]
        for c in run["comparisons"]
    }
    assert bridge_metrics == direct_metrics


def test_run_without_persist_writes_nothing(store, sample_spec):
    response = _call({"op": "run", "params": {"spec": sample_spec, "persist": False}}, store)
    assert response["ok"] is True
    assert "evidence" not in response["data"]
    assert _call({"op": "list_experiments", "params": {}}, store)["data"]["experiments"] == []


def test_evidence_and_export(store, sample_spec):
    experiment_id = _call({"op": "run", "params": {"spec": sample_spec}}, store)["data"][
        "experiment_id"
    ]
    evidence = _call({"op": "evidence", "params": {"experiment_id": experiment_id}}, store)["data"][
        "evidence"
    ]
    assert evidence["manifest"]["n_runs"] == 2
    assert evidence["report"].startswith("#")
    assert {f["kind"] for f in evidence["files"]} >= {"experiment_spec", "results", "report"}

    exported = _call(
        {"op": "export_evidence", "params": {"experiment_id": experiment_id}}, store
    )["data"]
    from pathlib import Path

    assert Path(exported["path"]).is_file()


def test_verify_evidence_op(store, sample_spec):
    experiment_id = _call({"op": "run", "params": {"spec": sample_spec}}, store)["data"][
        "experiment_id"
    ]

    verified = _call(
        {"op": "verify_evidence", "params": {"experiment_id": experiment_id}}, store
    )
    assert verified["ok"] is True
    assert verified["data"]["verification"]["ok"] is True
    assert verified["data"]["verification"]["failed"] == 0

    # Tamper with a declared artifact; verification must fail (read-only request).
    target = store.experiment_dir(experiment_id) / "evidence" / "results.json"
    target.write_bytes(target.read_bytes() + b" ")
    tampered = _call(
        {"op": "verify_evidence", "params": {"experiment_id": experiment_id}}, store
    )
    assert tampered["ok"] is True
    assert tampered["data"]["verification"]["ok"] is False
    assert tampered["data"]["verification"]["failed"] == 1


def test_verify_evidence_unknown_experiment_is_not_found(store):
    response = _call(
        {"op": "verify_evidence", "params": {"experiment_id": "exp-000000000000"}}, store
    )
    assert response["ok"] is False
    assert response["error"]["code"] == "not_found"


def test_sensitivity_ranking_is_sorted_and_normalized(store, sample_spec):
    experiment_id = _call({"op": "run", "params": {"spec": sample_spec}}, store)["data"][
        "experiment_id"
    ]
    ranking = _call(
        {"op": "sensitivity", "params": {"experiment_id": experiment_id}}, store
    )["data"]
    assert ranking["metric"] == "peak_prey"
    rows = ranking["ranking"]
    assert rows  # at least one numeric parameter
    magnitudes = [abs(row["abs_delta"]) for row in rows]
    assert magnitudes == sorted(magnitudes, reverse=True)
    assert all("elasticity" in row and "clamped" in row for row in rows)


def test_path_traversal_is_rejected(store):
    response = _call(
        {"op": "get_experiment", "params": {"experiment_id": "../../etc/passwd"}}, store
    )
    assert response["ok"] is False
    assert response["error"]["code"] == "bad_request"


def test_missing_experiment_is_not_found(store):
    response = _call(
        {"op": "get_experiment", "params": {"experiment_id": "exp-000000000000"}}, store
    )
    assert response["ok"] is False
    assert response["error"]["code"] == "not_found"


def test_bridge_process_protocol(tmp_path):
    """The real one-shot process: JSON on stdin, JSON on stdout."""
    env = {**os.environ, "DRW_WORKSPACE": str(tmp_path)}
    request = {"op": "list_models", "params": {}}
    completed = subprocess.run(
        [sys.executable, "-m", "drw.api"],
        input=json.dumps(request),
        capture_output=True,
        text=True,
        env=env,
        check=True,
        timeout=120,
    )
    response = json.loads(completed.stdout)
    assert response["ok"] is True
    assert any(m["model_id"] == "predator-prey" for m in response["data"]["models"])
