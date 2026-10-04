"""Integration tests for the command line interface."""

from __future__ import annotations

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
