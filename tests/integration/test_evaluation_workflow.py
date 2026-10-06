"""Integration tests: evaluation through the CLI and the bridge (read-only)."""

from __future__ import annotations

import json

import pytest

from drw import cli
from drw.api import handle
from drw.dataset_store import DatasetStore
from drw.execution.runner import Runner
from drw.observations import build_dataset
from drw.schema.experiment import AnalysisSpec, ExperimentSpec, FactorSpec
from drw.schema.model import ModelRef
from drw.schema.observation import (
    MappingPair,
    ObservationMapping,
    ObservationSet,
    Provenance,
    Variable,
)
from drw.store import ExperimentStore

pytestmark = pytest.mark.integration


@pytest.fixture
def prepared(tmp_path):
    workspace = tmp_path / "ws"
    experiment_store = ExperimentStore(workspace)
    dataset_store = DatasetStore(workspace)

    spec = ExperimentSpec(
        name="eval base",
        hypothesis="evaluate a stored run against a dataset",
        model_ref=ModelRef(model_id="predator-prey", version="1.0.0"),
        baseline={
            "alpha": 1.1, "beta": 0.4, "delta": 0.1, "gamma": 0.4,
            "prey0": 10.0, "predator0": 5.0,
        },
        factors=(FactorSpec(parameter="alpha", values=[1.1]),),
        outputs=("prey",),
        analyses=(AnalysisSpec(method="delta"),),
    )
    result = Runner().run(spec)
    experiment_store.save(result)
    experiment_id = result.experiment_id
    peak = result.baseline.metrics["peak_prey"]

    dataset = build_dataset(
        "observed peaks",
        ObservationSet(
            variables=(Variable(name="peak_prey", kind="float", role="measurement", unit="count"),),
            columns={"peak_prey": [peak - 1.0, peak, peak + 1.0]},
        ),
        Provenance(
            source_kind="synthetic",
            imported_at="2026-01-01T00:00:00+00:00",
            dataset_version="1.0.0",
        ),
    )
    dataset_store.save(dataset)

    mapping = ObservationMapping(
        dataset=dataset.ref(),
        model_ref=ModelRef(model_id="predator-prey"),
        pairs=(MappingPair(observation="peak_prey", output="peak_prey"),),
    )
    return workspace, experiment_store, dataset_store, experiment_id, mapping


def _call(store, op, params):
    return handle({"op": op, "params": params}, store=store)


def test_bridge_evaluate(prepared):
    _workspace, experiment_store, _dataset_store, experiment_id, mapping = prepared
    response = _call(
        experiment_store,
        "evaluate",
        {"experiment_id": experiment_id, "mapping": mapping.model_dump(mode="json")},
    )
    assert response["ok"] is True, response
    evaluation = response["data"]["evaluation"]
    assert evaluation["ok"] is True
    pair = evaluation["pairs"][0]
    assert pair["observation"] == "peak_prey" and pair["output"] == "peak_prey"
    assert pair["usable_count"] == 3
    assert pair["metrics"]["max_abs_error"] == pytest.approx(1.0)
    assert pair["metrics"]["mae"] == pytest.approx(2.0 / 3.0)
    assert len(evaluation["evaluation_hash"]) == 64


def test_bridge_evaluate_is_deterministic(prepared):
    _workspace, experiment_store, _dataset_store, experiment_id, mapping = prepared
    first = _call(experiment_store, "evaluate", {"experiment_id": experiment_id, "mapping": mapping.model_dump(mode="json")})
    second = _call(experiment_store, "evaluate", {"experiment_id": experiment_id, "mapping": mapping.model_dump(mode="json")})
    assert first["data"]["evaluation"]["evaluation_hash"] == second["data"]["evaluation"]["evaluation_hash"]


def test_bridge_evaluate_errors(prepared):
    _workspace, experiment_store, _dataset_store, experiment_id, mapping = prepared
    assert _call(experiment_store, "evaluate", {}).get("error", {}).get("code") == "bad_request"
    assert (
        _call(experiment_store, "evaluate", {"experiment_id": "exp-000000000000", "mapping": mapping.model_dump(mode="json")})[
            "error"
        ]["code"]
        == "not_found"
    )
    bad_mapping = mapping.model_dump(mode="json")
    bad_mapping["dataset"]["dataset_id"] = "ds-" + "0" * 12
    bad_mapping["dataset"]["content_hash"] = "0" * 64
    assert (
        _call(experiment_store, "evaluate", {"experiment_id": experiment_id, "mapping": bad_mapping})["error"]["code"]
        == "not_found"
    )
    assert (
        _call(experiment_store, "evaluate", {"experiment_id": experiment_id, "mapping": {"nope": 1}})["error"]["code"]
        == "bad_request"
    )
    assert (
        _call(
            experiment_store,
            "evaluate",
            {"experiment_id": experiment_id, "mapping": mapping.model_dump(mode="json"), "config": {"metrics": ["nope"]}},
        )["error"]["code"]
        == "bad_request"
    )


def test_cli_evaluate(prepared, tmp_path, capsys):
    workspace, _experiment_store, _dataset_store, experiment_id, mapping = prepared
    mapping_path = tmp_path / "mapping.json"
    mapping_path.write_text(json.dumps(mapping.model_dump(mode="json")), encoding="utf-8")

    code = cli.main(["evaluate", experiment_id, "--mapping", str(mapping_path), "--workspace", str(workspace)])
    assert code == 0
    out = capsys.readouterr().out
    assert "ok: True" in out
    assert "peak_prey -> peak_prey" in out
    assert "mae" in out

    assert cli.main(["evaluate", experiment_id, "--mapping", str(mapping_path), "--json", "--workspace", str(workspace)]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True


def test_cli_evaluate_error_exit_codes(prepared, tmp_path, capsys):
    workspace, _experiment_store, _dataset_store, experiment_id, mapping = prepared
    # Missing mapping file.
    assert cli.main(["evaluate", experiment_id, "--mapping", str(tmp_path / "nope.json"), "--workspace", str(workspace)]) == 2
    # Unknown experiment.
    mapping_path = tmp_path / "mapping.json"
    mapping_path.write_text(json.dumps(mapping.model_dump(mode="json")), encoding="utf-8")
    assert cli.main(["evaluate", "exp-000000000000", "--mapping", str(mapping_path), "--workspace", str(workspace)]) == 2
    # Unknown run.
    assert cli.main(["evaluate", experiment_id, "--run", "nope", "--mapping", str(mapping_path), "--workspace", str(workspace)]) == 2
