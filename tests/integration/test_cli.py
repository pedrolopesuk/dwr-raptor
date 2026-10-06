"""Integration tests for the command line interface."""

from __future__ import annotations

import json

import pytest

from drw import cli

pytestmark = pytest.mark.integration


def test_list_models(capsys):
    assert cli.main(["list-models"]) == 0
    out = capsys.readouterr().out
    for model_id in ("oscillator", "predator-prey", "lorenz"):
        assert model_id in out


def test_validate_example_has_no_errors(repo_root, capsys):
    code = cli.main(["validate", str(repo_root / "models/examples/predator-prey/experiment.yaml")])
    assert code == 0
    assert "valid" in capsys.readouterr().out


def test_run_writes_evidence_package(repo_root, tmp_path, capsys):
    out_dir = tmp_path / "run"
    code = cli.main(
        ["run", str(repo_root / "models/examples/predator-prey/experiment.yaml"), "--out", str(out_dir)]
    )
    assert code == 0
    assert (out_dir / "manifest.json").exists()
    assert (out_dir / "report.md").exists()


def test_demo_writes_artifact(repo_root, tmp_path, capsys):
    out_dir = tmp_path / "demo"
    assert cli.main(["demo", "--out", str(out_dir)]) == 0
    assert (out_dir / "sensitivity.json").exists()
    assert (out_dir / "manifest.json").exists()


def test_export_schemas(tmp_path):
    assert cli.main(["export-schemas", "--out", str(tmp_path)]) == 0
    assert (tmp_path / "model-schema.schema.json").exists()
    assert (tmp_path / "experiment-spec.schema.json").exists()


def test_verify_command_ok_failure_and_bad_input(repo_root, tmp_path, capsys):
    out_dir = tmp_path / "run"
    assert (
        cli.main(
            ["run", str(repo_root / "models/examples/predator-prey/experiment.yaml"), "--out", str(out_dir)]
        )
        == 0
    )
    manifest = out_dir / "manifest.json"

    # A freshly written package verifies.
    assert cli.main(["verify", str(manifest)]) == 0
    assert "result: OK" in capsys.readouterr().out

    # A modified artifact fails with a non-success exit code.
    results = out_dir / "results.json"
    results.write_bytes(results.read_bytes() + b" ")
    assert cli.main(["verify", str(manifest)]) == 1
    assert "FAILED" in capsys.readouterr().out

    # A missing manifest is a usage error (exit 2), not a failed verification.
    assert cli.main(["verify", str(tmp_path / "nope.json")]) == 2


def test_verify_rejects_an_empty_manifest(repo_root, tmp_path, capsys):
    out_dir = tmp_path / "run"
    assert (
        cli.main(
            ["run", str(repo_root / "models/examples/predator-prey/experiment.yaml"), "--out", str(out_dir)]
        )
        == 0
    )
    manifest = out_dir / "manifest.json"
    data = json.loads(manifest.read_text(encoding="utf-8"))
    data["files"] = []
    manifest.write_text(json.dumps(data), encoding="utf-8")

    assert cli.main(["verify", str(manifest)]) == 2
    assert "error" in capsys.readouterr().err.lower()


def test_verify_handles_a_directory_listing_error(repo_root, tmp_path, monkeypatch, capsys):
    out_dir = tmp_path / "run"
    assert (
        cli.main(
            ["run", str(repo_root / "models/examples/predator-prey/experiment.yaml"), "--out", str(out_dir)]
        )
        == 0
    )
    manifest = out_dir / "manifest.json"

    def boom(self):
        raise OSError("simulated listing failure")

    monkeypatch.setattr("pathlib.Path.iterdir", boom)
    assert cli.main(["verify", str(manifest)]) == 2
    assert "error" in capsys.readouterr().err.lower()


def _stored_experiment(repo_root, workspace):
    from drw.execution.runner import Runner
    from drw.schema.files import load_experiment_spec
    from drw.store import ExperimentStore

    store = ExperimentStore(workspace)
    spec = load_experiment_spec(repo_root / "models/examples/predator-prey/experiment.yaml")
    result = Runner().run(spec)
    store.save(result)
    return store, result.experiment_id


def test_reproduce_command_success_and_usage_errors(repo_root, tmp_path, capsys):
    workspace = tmp_path / "ws"
    _store, experiment_id = _stored_experiment(repo_root, workspace)

    assert (
        cli.main(
            ["reproduce", experiment_id, "--rtol", "1e-9", "--atol", "1e-12", "--workspace", str(workspace)]
        )
        == 0
    )
    out = capsys.readouterr().out
    assert "verdict: identical" in out
    assert "model hash match: True" in out

    # Invalid tolerance configuration -> usage error (exit 2).
    assert (
        cli.main(
            ["reproduce", experiment_id, "--rtol", "-1", "--atol", "0", "--workspace", str(workspace)]
        )
        == 2
    )
    # Unknown experiment -> usage error (exit 2).
    assert (
        cli.main(
            ["reproduce", "exp-000000000000", "--rtol", "1e-9", "--atol", "1e-9", "--workspace", str(workspace)]
        )
        == 2
    )


def test_reproduce_command_reports_a_difference(repo_root, tmp_path, capsys):
    workspace = tmp_path / "ws"
    store, experiment_id = _stored_experiment(repo_root, workspace)
    results_path = store.experiment_dir(experiment_id) / "results.json"
    results = json.loads(results_path.read_text(encoding="utf-8"))
    prey = results["runs"][1]["result"]["outputs"]["prey"]
    prey["values"] = [value + 1.0 for value in prey["values"]]
    results_path.write_text(json.dumps(results), encoding="utf-8")

    assert (
        cli.main(
            ["reproduce", experiment_id, "--rtol", "1e-9", "--atol", "1e-12", "--workspace", str(workspace)]
        )
        == 1
    )
    assert "verdict: different" in capsys.readouterr().out


def test_reproduce_command_reports_execution_failure(repo_root, tmp_path, monkeypatch, capsys):
    from types import SimpleNamespace

    from drw.schema.model import ModelRef
    from drw.schema.result import RunRecord, RunStatus

    workspace = tmp_path / "ws"
    _store, experiment_id = _stored_experiment(repo_root, workspace)
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

    assert (
        cli.main(
            ["reproduce", experiment_id, "--rtol", "1e-9", "--atol", "1e-12", "--workspace", str(workspace)]
        )
        == 2
    )
    assert "verdict: execution_failed" in capsys.readouterr().out


def _stored_sampled_experiment(workspace):
    from drw.execution.runner import Runner
    from drw.schema.experiment import AnalysisSpec, ExperimentSpec, FactorSpec, SamplingSpec
    from drw.schema.model import ModelRef
    from drw.store import ExperimentStore

    spec = ExperimentSpec(
        name="uncertainty demo",
        hypothesis="how does the prey peak vary across the sampled alpha range?",
        model_ref=ModelRef(model_id="predator-prey", version="1.0.0"),
        baseline={
            "alpha": 1.1,
            "beta": 0.4,
            "delta": 0.1,
            "gamma": 0.4,
            "prey0": 10.0,
            "predator0": 5.0,
        },
        factors=(FactorSpec(parameter="alpha", lower=0.5, upper=2.0),),
        sampling=SamplingSpec(method="latin_hypercube", n_samples=5, seed=4),
        analyses=(AnalysisSpec(method="delta"), AnalysisSpec(method="uncertainty")),
    )
    store = ExperimentStore(workspace)
    result = Runner().run(spec)
    store.save(result)
    return store, result.experiment_id


def test_uncertainty_command(tmp_path, capsys):
    workspace = tmp_path / "ws"
    _store, experiment_id = _stored_sampled_experiment(workspace)

    assert cli.main(["uncertainty", experiment_id, "--workspace", str(workspace)]) == 0
    out = capsys.readouterr().out
    assert "sampling: latin_hypercube" in out
    assert "variants=" in out and "valid_output_samples=" in out
    assert "quantile" in out.lower() and "linear" in out
    assert "descriptive summary" in out

    # Unknown experiment -> usage error (exit 2).
    assert cli.main(["uncertainty", "exp-000000000000", "--workspace", str(workspace)]) == 2


def test_uncertainty_command_no_runs(tmp_path):
    workspace = tmp_path / "ws"
    store, experiment_id = _stored_sampled_experiment(workspace)
    results_path = store.experiment_dir(experiment_id) / "results.json"
    results = json.loads(results_path.read_text(encoding="utf-8"))
    results["runs"] = []
    results_path.write_text(json.dumps(results), encoding="utf-8")

    assert cli.main(["uncertainty", experiment_id, "--workspace", str(workspace)]) == 2


def test_sobol_command(repo_root, tmp_path, capsys):
    workspace = tmp_path / "ws"
    _store, experiment_id = _stored_experiment(repo_root, workspace)

    code = cli.main(
        [
            "sobol", experiment_id, "--output", "peak_prey", "--factors", "alpha,beta",
            "--n", "8", "--seed", "3", "--bootstrap", "20", "--workspace", str(workspace),
        ]
    )
    assert code == 0
    out = capsys.readouterr().out
    assert "output: peak_prey" in out
    assert "S1" in out and "evaluations=32" in out

    # Unknown factor -> usage error (exit 2).
    assert cli.main(["sobol", experiment_id, "--factors", "nope", "--n", "8", "--workspace", str(workspace)]) == 2
    # Unknown experiment -> usage error (exit 2).
    assert cli.main(["sobol", "exp-000000000000", "--n", "8", "--workspace", str(workspace)]) == 2
    # Negative seed -> usage error (exit 2).
    assert cli.main(
        [
            "sobol", experiment_id, "--factors", "alpha,beta", "--n", "8", "--seed", "-1",
            "--workspace", str(workspace),
        ]
    ) == 2
    # A study exceeding the evaluation cap is rejected before executing (exit 2).
    assert cli.main(
        [
            "sobol", experiment_id, "--factors", "alpha,beta", "--n", "4096",
            "--workspace", str(workspace),
        ]
    ) == 2
