"""Integration tests: CSV dataset inspect/import through the CLI and the bridge."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from drw import cli
from drw.api import handle
from drw.store import ExperimentStore

pytestmark = pytest.mark.integration

LIGHTCURVE = "\n".join(
    [
        "time,flux,flux_err",
        "2026-01-01T00:00:00Z,12.30,0.10",
        "2026-01-01T00:01:00Z,12.35,0.10",
        "2026-01-01T00:02:00Z,12.28,0.11",
        "",
    ]
)

CONFIG = {
    "name": "lightcurve",
    "imported_at": "2026-01-01T00:00:00+00:00",
    "columns": [
        {"column": "time", "role": "coordinate"},
        {
            "column": "flux",
            "role": "measurement",
            "unit": "Jy",
            "depends_on": ["time"],
            "uncertainty": {"type": "std", "column": "flux_err"},
        },
        {"column": "flux_err", "role": "uncertainty", "unit": "Jy"},
    ],
}


@pytest.fixture
def workspace(tmp_path) -> Path:
    root = tmp_path / "ws"
    sources = root / "dataset-sources"
    sources.mkdir(parents=True)
    (sources / "lightcurve.csv").write_text(LIGHTCURVE, encoding="utf-8")
    return root


@pytest.fixture
def store(workspace) -> ExperimentStore:
    return ExperimentStore(workspace)


def _call(store, op, params):
    return handle({"op": op, "params": params}, store=store)


# ---------------------------------------------------------------------------
# Bridge.
# ---------------------------------------------------------------------------


def test_list_dataset_sources(store):
    response = _call(store, "list_dataset_sources", {})
    assert response["ok"] is True
    assert [item["filename"] for item in response["data"]["sources"]] == ["lightcurve.csv"]


def test_inspect_dataset(store):
    response = _call(store, "inspect_dataset", {"filename": "lightcurve.csv"})
    assert response["ok"] is True
    inspection = response["data"]["inspection"]
    assert inspection["row_count"] == 3
    assert [column["column"] for column in inspection["columns"]] == ["time", "flux", "flux_err"]
    assert inspection["columns"][0]["suggested_role"] == "coordinate"


def test_import_dataset_dry_run_then_import(store):
    dry = _call(store, "import_dataset", {"filename": "lightcurve.csv", "config": CONFIG, "dry_run": True})
    assert dry["ok"] is True
    assert dry["data"]["stored"] is False
    assert _call(store, "list_datasets", {})["data"]["datasets"] == []

    real = _call(store, "import_dataset", {"filename": "lightcurve.csv", "config": CONFIG})
    assert real["ok"] is True, real
    ref = real["data"]["ref"]
    assert ref["dataset_id"].startswith("ds-")
    assert real["data"]["verification"]["ok"] is True
    assert [d["dataset_id"] for d in _call(store, "list_datasets", {})["data"]["datasets"]] == [
        ref["dataset_id"]
    ]


def test_import_dataset_is_idempotent_for_identical_content(store):
    first = _call(store, "import_dataset", {"filename": "lightcurve.csv", "config": CONFIG})["data"]["ref"]
    second = _call(store, "import_dataset", {"filename": "lightcurve.csv", "config": CONFIG})["data"]["ref"]
    assert first["dataset_id"] == second["dataset_id"]
    assert first["content_hash"] == second["content_hash"]


def test_describe_and_get_dataset(store):
    ref = _call(store, "import_dataset", {"filename": "lightcurve.csv", "config": CONFIG})["data"]["ref"]
    described = _call(store, "describe_dataset", {"dataset_id": ref["dataset_id"]})
    assert described["ok"] is True
    assert described["data"]["ref"] == ref
    assert len(described["data"]["dataset"]["observation_set"]["variables"]) == 3
    assert described["data"]["verification"]["ok"] is True

    aliased = _call(store, "get_dataset", {"dataset_id": ref["dataset_id"]})
    assert aliased["data"]["ref"] == ref


def test_verify_dataset(store):
    ref = _call(store, "import_dataset", {"filename": "lightcurve.csv", "config": CONFIG})["data"]["ref"]
    response = _call(store, "verify_dataset", {"dataset_id": ref["dataset_id"]})
    assert response["ok"] is True
    assert response["data"]["verification"]["ok"] is True


def test_import_dataset_validation_errors(store):
    assert _call(store, "inspect_dataset", {})["error"]["code"] == "bad_request"
    assert _call(store, "inspect_dataset", {"filename": "nope.csv"})["error"]["code"] == "not_found"
    assert (
        _call(store, "inspect_dataset", {"filename": "../escape.csv"})["error"]["code"]
        == "bad_request"
    )
    assert (
        _call(store, "inspect_dataset", {"filename": "lightcurve.csv", "missing_codes": "x"})[
            "error"
        ]["code"]
        == "bad_request"
    )
    bad_config = _call(
        store, "import_dataset", {"filename": "lightcurve.csv", "config": {"name": "x"}}
    )
    assert bad_config["error"]["code"] == "bad_request"
    unknown_op_target = _call(store, "describe_dataset", {"dataset_id": "ds-" + "0" * 12})
    assert unknown_op_target["error"]["code"] == "not_found"
    invalid_id = _call(store, "describe_dataset", {"dataset_id": "nope"})
    assert invalid_id["error"]["code"] == "bad_request"


def test_verify_unknown_dataset_is_not_ok(store):
    response = _call(store, "verify_dataset", {"dataset_id": "ds-" + "0" * 12})
    assert response["ok"] is True
    assert response["data"]["verification"]["ok"] is False


def test_path_traversal_is_contained(store):
    for filename in ("../outside.csv", "..\\outside.csv", "sub/../../outside.csv"):
        response = _call(store, "inspect_dataset", {"filename": filename})
        assert response["ok"] is False and response["error"]["code"] == "bad_request"


# ---------------------------------------------------------------------------
# CLI.
# ---------------------------------------------------------------------------


def test_cli_inspect(workspace, capsys):
    source = workspace / "dataset-sources" / "lightcurve.csv"
    assert cli.main(["dataset", "inspect", str(source)]) == 0
    out = capsys.readouterr().out
    assert "time" in out and "flux_err" in out and "rows=3" in out
    assert "advisory" in out

    assert cli.main(["dataset", "inspect", str(source), "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["row_count"] == 3


def test_cli_import_list_describe_verify(workspace, tmp_path, capsys):
    source = workspace / "dataset-sources" / "lightcurve.csv"
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps(CONFIG), encoding="utf-8")

    assert cli.main(["dataset", "import", str(source), "--config", str(config_path), "--dry-run", "--workspace", str(workspace)]) == 0
    assert "validated (dry run)" in capsys.readouterr().out

    assert cli.main(["dataset", "import", str(source), "--config", str(config_path), "--workspace", str(workspace)]) == 0
    out = capsys.readouterr().out
    dataset_id = out.split("imported dataset: ")[1].splitlines()[0].strip()
    assert dataset_id.startswith("ds-")

    assert cli.main(["dataset", "list", "--workspace", str(workspace)]) == 0
    assert dataset_id in capsys.readouterr().out

    assert cli.main(["dataset", "describe", dataset_id, "--workspace", str(workspace)]) == 0
    assert "variables:" in capsys.readouterr().out

    assert cli.main(["dataset", "verify", dataset_id, "--workspace", str(workspace)]) == 0
    assert "result: OK" in capsys.readouterr().out


def test_cli_error_exit_codes(workspace, tmp_path, capsys):
    source = workspace / "dataset-sources" / "lightcurve.csv"
    # Missing source file.
    assert cli.main(["dataset", "inspect", str(tmp_path / "nope.csv")]) == 2
    # Missing / malformed config.
    assert cli.main(["dataset", "import", str(source), "--config", str(tmp_path / "nope.json"), "--workspace", str(workspace)]) == 2
    bad_config = tmp_path / "bad.json"
    bad_config.write_text("{not json", encoding="utf-8")
    assert cli.main(["dataset", "import", str(source), "--config", str(bad_config), "--workspace", str(workspace)]) == 2
    # Unknown dataset id.
    assert cli.main(["dataset", "describe", "ds-" + "0" * 12, "--workspace", str(workspace)]) == 2
    # Invalid id.
    assert cli.main(["dataset", "verify", "nope", "--workspace", str(workspace)]) == 2


def test_cli_verify_reports_a_failure(workspace, tmp_path, capsys):
    source = workspace / "dataset-sources" / "lightcurve.csv"
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps(CONFIG), encoding="utf-8")
    assert cli.main(["dataset", "import", str(source), "--config", str(config_path), "--workspace", str(workspace)]) == 0
    dataset_id = capsys.readouterr().out.split("imported dataset: ")[1].splitlines()[0].strip()

    # Tamper with the stored payload; verification must fail (exit 1).
    data_path = workspace / "datasets" / dataset_id / "data.json"
    payload = json.loads(data_path.read_text(encoding="utf-8"))
    payload["columns"]["flux"][0] = 999.0
    data_path.write_text(json.dumps(payload), encoding="utf-8")

    assert cli.main(["dataset", "verify", dataset_id, "--workspace", str(workspace)]) == 1
    assert "FAILED" in capsys.readouterr().out
