"""Integration tests for the JSON bridge and the experiment store."""

from __future__ import annotations

import hashlib
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


def test_verify_evidence_empty_manifest_is_bad_request(store, sample_spec):
    experiment_id = _call({"op": "run", "params": {"spec": sample_spec}}, store)["data"][
        "experiment_id"
    ]
    manifest = store.experiment_dir(experiment_id) / "evidence" / "manifest.json"
    data = json.loads(manifest.read_text(encoding="utf-8"))
    data["files"] = []
    manifest.write_text(json.dumps(data), encoding="utf-8")

    response = _call(
        {"op": "verify_evidence", "params": {"experiment_id": experiment_id}}, store
    )
    assert response["ok"] is False
    assert response["error"]["code"] == "bad_request"


def _snapshot(directory) -> dict[str, str]:
    return {
        path.relative_to(directory).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(directory.rglob("*"))
        if path.is_file()
    }


def test_reproduce_experiment_op_is_read_only(store, sample_spec):
    experiment_id = _call({"op": "run", "params": {"spec": sample_spec}}, store)["data"][
        "experiment_id"
    ]
    directory = store.experiment_dir(experiment_id)
    before = _snapshot(directory)

    response = _call(
        {
            "op": "reproduce_experiment",
            "params": {"experiment_id": experiment_id, "rtol": 1e-9, "atol": 1e-12},
        },
        store,
    )
    assert response["ok"] is True
    report = response["data"]["report"]
    assert report["experiment_id"] == experiment_id
    assert report["verdict"] in ("identical", "equivalent_within_tolerance")
    assert report["fresh_runs_persisted"] is False
    assert len(report["reference_run_ids"]) == len(report["fresh_run_ids"]) == 2

    assert _snapshot(directory) == before


def test_reproduce_experiment_detects_a_difference(store, sample_spec):
    experiment_id = _call({"op": "run", "params": {"spec": sample_spec}}, store)["data"][
        "experiment_id"
    ]
    results_path = store.experiment_dir(experiment_id) / "results.json"
    results = json.loads(results_path.read_text(encoding="utf-8"))
    prey = results["runs"][1]["result"]["outputs"]["prey"]
    prey["values"] = [value + 1.0 for value in prey["values"]]
    results_path.write_text(json.dumps(results), encoding="utf-8")

    response = _call(
        {
            "op": "reproduce_experiment",
            "params": {"experiment_id": experiment_id, "rtol": 1e-9, "atol": 1e-12},
        },
        store,
    )
    assert response["data"]["report"]["verdict"] == "different"


def test_reproduce_experiment_request_validation(store, sample_spec):
    experiment_id = _call({"op": "run", "params": {"spec": sample_spec}}, store)["data"][
        "experiment_id"
    ]
    missing = _call(
        {"op": "reproduce_experiment", "params": {"experiment_id": experiment_id, "atol": 1e-9}},
        store,
    )
    assert missing["ok"] is False and missing["error"]["code"] == "bad_request"

    not_a_number = _call(
        {
            "op": "reproduce_experiment",
            "params": {"experiment_id": experiment_id, "rtol": "nope", "atol": 1e-9},
        },
        store,
    )
    assert not_a_number["ok"] is False and not_a_number["error"]["code"] == "bad_request"

    unknown = _call(
        {
            "op": "reproduce_experiment",
            "params": {"experiment_id": "exp-000000000000", "rtol": 1e-9, "atol": 1e-9},
        },
        store,
    )
    assert unknown["ok"] is False and unknown["error"]["code"] == "not_found"


def test_reproduce_experiment_missing_reference_is_bad_request(store, sample_spec):
    experiment_id = _call({"op": "run", "params": {"spec": sample_spec}}, store)["data"][
        "experiment_id"
    ]
    results_path = store.experiment_dir(experiment_id) / "results.json"
    results = json.loads(results_path.read_text(encoding="utf-8"))
    results["runs"] = []
    results_path.write_text(json.dumps(results), encoding="utf-8")

    response = _call(
        {
            "op": "reproduce_experiment",
            "params": {"experiment_id": experiment_id, "rtol": 1e-9, "atol": 1e-12},
        },
        store,
    )
    assert response["ok"] is False and response["error"]["code"] == "bad_request"


def test_reproduce_experiment_execution_failure(store, sample_spec, monkeypatch):
    from types import SimpleNamespace

    from drw.schema.model import ModelRef
    from drw.schema.result import RunRecord, RunStatus

    experiment_id = _call({"op": "run", "params": {"spec": sample_spec}}, store)["data"][
        "experiment_id"
    ]
    directory = store.experiment_dir(experiment_id)
    before = _snapshot(directory)
    failed = [
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
    monkeypatch.setattr(
        "drw.reproduce.Runner",
        lambda: SimpleNamespace(run=lambda spec, **kwargs: SimpleNamespace(runs=failed)),
    )

    response = _call(
        {
            "op": "reproduce_experiment",
            "params": {"experiment_id": experiment_id, "rtol": 1e-9, "atol": 1e-12},
        },
        store,
    )
    # The request is processed; the report itself records the execution failure.
    assert response["ok"] is True
    assert response["data"]["report"]["verdict"] == "execution_failed"
    assert response["data"]["report"]["fresh_runs_persisted"] is False
    assert _snapshot(directory) == before


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


def test_uncertainty_op(store, sample_spec):
    experiment_id = _call({"op": "run", "params": {"spec": sample_spec}}, store)["data"][
        "experiment_id"
    ]

    response = _call({"op": "uncertainty", "params": {"experiment_id": experiment_id}}, store)
    assert response["ok"] is True
    summary = response["data"]["uncertainty"]
    assert summary["sampling_method"] == "grid"
    assert summary["quantile_method"] == "linear"
    assert summary["quantiles"] == [5.0, 50.0, 95.0]
    assert summary["descriptive_only"] is True
    assert summary["requested_variants"] == 1  # the demo spec is a single-value grid
    assert summary["note"]  # grid designs are flagged as not a sampling distribution
    peak = next(output for output in summary["outputs"] if output["output"] == "peak_prey")
    assert peak["requested_variants"] == 1 and peak["sufficient"] is False
    assert peak["std"] is None


def test_uncertainty_op_unknown_experiment_is_not_found(store):
    response = _call(
        {"op": "uncertainty", "params": {"experiment_id": "exp-000000000000"}}, store
    )
    assert response["ok"] is False and response["error"]["code"] == "not_found"


def test_uncertainty_op_no_runs_is_bad_request(store, sample_spec):
    experiment_id = _call({"op": "run", "params": {"spec": sample_spec}}, store)["data"][
        "experiment_id"
    ]
    results_path = store.experiment_dir(experiment_id) / "results.json"
    results = json.loads(results_path.read_text(encoding="utf-8"))
    results["runs"] = []
    results_path.write_text(json.dumps(results), encoding="utf-8")

    response = _call(
        {"op": "uncertainty", "params": {"experiment_id": experiment_id}}, store
    )
    assert response["ok"] is False and response["error"]["code"] == "bad_request"


def test_global_sensitivity_op(store, sample_spec):
    experiment_id = _call({"op": "run", "params": {"spec": sample_spec}}, store)["data"][
        "experiment_id"
    ]
    response = _call(
        {
            "op": "global_sensitivity",
            "params": {
                "experiment_id": experiment_id,
                "output": "peak_prey",
                "factors": ["alpha", "beta"],
                "sample_count": 8,
                "seed": 3,
                "bootstrap_resamples": 20,
            },
        },
        store,
    )
    assert response["ok"] is True
    report = response["data"]["report"]
    assert report["output"] == "peak_prey"
    assert report["factors"] == ["alpha", "beta"]
    assert report["evaluations_requested"] == 32
    assert report["evaluations_completed"] == 32
    assert report["inconclusive"] is False
    assert {row["name"] for row in report["results"]} == {"alpha", "beta"}


def test_global_sensitivity_op_validation(store, sample_spec):
    experiment_id = _call({"op": "run", "params": {"spec": sample_spec}}, store)["data"][
        "experiment_id"
    ]

    unknown_factor = _call(
        {
            "op": "global_sensitivity",
            "params": {"experiment_id": experiment_id, "factors": ["nope"], "sample_count": 8},
        },
        store,
    )
    assert unknown_factor["ok"] is False and unknown_factor["error"]["code"] == "bad_request"

    not_a_list = _call(
        {
            "op": "global_sensitivity",
            "params": {"experiment_id": experiment_id, "factors": "alpha"},
        },
        store,
    )
    assert not_a_list["ok"] is False and not_a_list["error"]["code"] == "bad_request"

    unknown_experiment = _call(
        {
            "op": "global_sensitivity",
            "params": {"experiment_id": "exp-000000000000", "sample_count": 8},
        },
        store,
    )
    assert unknown_experiment["ok"] is False and unknown_experiment["error"]["code"] == "not_found"

    # The seed must be a non-negative integer (consistent with the CLI and web UI).
    negative_seed = _call(
        {
            "op": "global_sensitivity",
            "params": {
                "experiment_id": experiment_id, "factors": ["alpha"], "sample_count": 8,
                "seed": -1,
            },
        },
        store,
    )
    assert negative_seed["ok"] is False and negative_seed["error"]["code"] == "bad_request"
    assert "seed" in negative_seed["error"]["message"]

    # A study exceeding the evaluation cap is rejected before executing.
    over_cap = _call(
        {
            "op": "global_sensitivity",
            "params": {"experiment_id": experiment_id, "factors": ["alpha"], "sample_count": 4096},
        },
        store,
    )
    assert over_cap["ok"] is False and over_cap["error"]["code"] == "bad_request"
    assert "evaluations" in over_cap["error"]["message"]


# --- global-sensitivity progress reporting (job journal, ADR-0009) ----------


def _stored_experiment_id(store, sample_spec) -> str:
    return _call({"op": "run", "params": {"spec": sample_spec}}, store)["data"]["experiment_id"]


def _job_status(store, job_id) -> dict:
    response = _call({"op": "job_status", "params": {"job_id": job_id}}, store)
    assert response["ok"] is True
    return response["data"]


def test_global_sensitivity_progress_reports_measured_completion(store, sample_spec):
    experiment_id = _stored_experiment_id(store, sample_spec)
    job_id = "job-" + "a" * 16

    response = _call(
        {
            "op": "global_sensitivity",
            "params": {
                "experiment_id": experiment_id,
                "output": "peak_prey",
                "factors": ["alpha", "beta"],
                "sample_count": 8,
                "seed": 3,
                "bootstrap_resamples": 5,
                "job_id": job_id,
            },
        },
        store,
    )
    assert response["ok"] is True, response
    report = response["data"]["report"]
    assert report["inconclusive"] is False
    total = report["evaluations_requested"]
    assert total == 8 * (2 + 2)

    status = _job_status(store, job_id)
    assert status["phase"] == "finished"
    assert status["terminal"] is True
    assert status["status"] == "succeeded"
    assert status["total_runs"] == total
    # Measured, not estimated: one run_completed event per evaluation.
    assert status["completed_runs"] == total
    events = status["events"]
    assert events[0]["event"] == "started"
    assert events[-1]["event"] == "finished"
    assert sum(1 for event in events if event["event"] == "run_completed") == total


def test_global_sensitivity_progress_reports_invalid_study_as_failed(store, sample_spec):
    experiment_id = _stored_experiment_id(store, sample_spec)
    job_id = "job-" + "b" * 16

    response = _call(
        {
            "op": "global_sensitivity",
            "params": {
                "experiment_id": experiment_id,
                "factors": ["nope"],
                "sample_count": 8,
                "job_id": job_id,
            },
        },
        store,
    )
    assert response["ok"] is False and response["error"]["code"] == "bad_request"

    status = _job_status(store, job_id)
    assert status["phase"] == "finished"
    assert status["terminal"] is True
    assert status["status"] == "failed"
    assert status["status"] != "succeeded"
    assert status["completed_runs"] == 0


def test_global_sensitivity_progress_reports_over_cap_study_as_failed(store, sample_spec):
    experiment_id = _stored_experiment_id(store, sample_spec)
    job_id = "job-" + "c" * 16

    response = _call(
        {
            "op": "global_sensitivity",
            "params": {
                "experiment_id": experiment_id,
                "factors": ["alpha"],
                "sample_count": 4096,
                "job_id": job_id,
            },
        },
        store,
    )
    assert response["ok"] is False and response["error"]["code"] == "bad_request"

    status = _job_status(store, job_id)
    assert status["phase"] == "finished"
    assert status["terminal"] is True
    assert status["status"] == "failed"
    assert status["completed_runs"] == 0


def test_global_sensitivity_progress_inconclusive_is_not_success(store, sample_spec, monkeypatch):
    from drw.global_sensitivity import SobolReport

    experiment_id = _stored_experiment_id(store, sample_spec)
    job_id = "job-" + "d" * 16

    def inconclusive(*_args, **_kwargs):
        return SobolReport(
            model_id="predator-prey",
            output="peak_prey",
            sample_count=8,
            seed=3,
            dimensions=1,
            factors=["alpha"],
            evaluations_requested=24,
            evaluations_completed=24,
            inconclusive=True,
            reasons=["output variance is zero or non-finite; the indices are undefined"],
        )

    monkeypatch.setattr("drw.global_sensitivity.sobol_indices_for_experiment", inconclusive)

    response = _call(
        {
            "op": "global_sensitivity",
            "params": {
                "experiment_id": experiment_id,
                "factors": ["alpha"],
                "sample_count": 8,
                "job_id": job_id,
            },
        },
        store,
    )
    assert response["ok"] is True
    assert response["data"]["report"]["inconclusive"] is True

    status = _job_status(store, job_id)
    assert status["phase"] == "finished"
    assert status["terminal"] is True
    assert status["status"] == "inconclusive"
    assert status["status"] != "succeeded"
