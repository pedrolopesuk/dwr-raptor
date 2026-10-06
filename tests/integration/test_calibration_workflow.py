"""Integration tests: calibration through the CLI and the bridge, with the store."""

from __future__ import annotations

import json

import pytest

from drw import cli
from drw.api import handle
from drw.calibration_store import CalibrationStore
from drw.dataset_store import DatasetStore
from drw.execution.runner import Runner
from drw.models.registry import build_model
from drw.observations import build_dataset
from drw.schema.calibration import (
    BudgetSpec,
    CalibrationConfig,
    ExecutionTemplate,
    ObjectiveConfig,
    OptimizerConfig,
    ParameterSelection,
)
from drw.schema.evaluation import EvaluationConfig
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
        name="calibrate base",
        hypothesis="calibrate a stored experiment",
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
        "observed peak",
        ObservationSet(
            variables=(Variable(name="peak_prey", kind="float", role="measurement", unit="count"),),
            columns={"peak_prey": [peak - 0.5, peak, peak + 0.5]},
        ),
        Provenance(
            source_kind="synthetic", imported_at="2026-01-01T00:00:00+00:00", dataset_version="1.0.0"
        ),
    )
    dataset_store.save(dataset)

    alpha = build_model("predator-prey").describe().parameter("alpha")
    mapping = ObservationMapping(
        dataset=dataset.ref(),
        model_ref=ModelRef(model_id="predator-prey"),
        pairs=(MappingPair(observation="peak_prey", output="peak_prey"),),
    )
    config = CalibrationConfig(
        experiment_id=experiment_id,
        model_ref=ModelRef(model_id="predator-prey"),
        free=(
            ParameterSelection(
                name="alpha", lower=alpha.lower, upper=alpha.upper, initial=1.1
            ),
        ),
        objective=ObjectiveConfig(metric="rmse"),
        optimizer=OptimizerConfig(name="random_search"),
        budget=BudgetSpec(max_evaluations=4),
        seed=0,
        execution=ExecutionTemplate(isolation="in_process", timeout_s=30.0),
        dataset=dataset.ref(),
        mapping=mapping,
        evaluation=EvaluationConfig(),
        identifiability="off",
    )
    return workspace, experiment_store, experiment_id, config


def _call(store, op, params):
    return handle({"op": op, "params": params}, store=store)


def test_bridge_calibrate_and_store(prepared):
    _workspace, store, experiment_id, config = prepared
    response = _call(
        store, "calibrate", {"experiment_id": experiment_id, "config": config.model_dump(mode="json"), "persist": True}
    )
    assert response["ok"] is True, response
    calibration = response["data"]["calibration"]
    assert calibration["status"] in ("budget_exhausted", "converged", "not_converged")
    assert calibration["best"] is not None
    assert calibration["provenance"]["scipy_version"]
    ref = response["data"]["ref"]
    assert ref["calibration_id"].startswith("cal-")

    listed = _call(store, "list_calibrations", {})
    assert any(item["calibration_id"] == ref["calibration_id"] for item in listed["data"]["calibrations"])

    fetched = _call(store, "get_calibration", {"calibration_id": ref["calibration_id"]})
    assert fetched["ok"] is True
    assert fetched["data"]["calibration"]["result_hash"] == calibration["result_hash"]

    verified = _call(store, "verify_calibration", {"calibration_id": ref["calibration_id"]})
    assert verified["data"]["verification"]["ok"] is True


def test_bridge_calibrate_errors(prepared):
    _workspace, store, experiment_id, config = prepared
    assert _call(store, "calibrate", {}).get("error", {}).get("code") == "bad_request"
    assert (
        _call(store, "calibrate", {"experiment_id": "exp-000000000000", "config": config.model_dump(mode="json")})[
            "error"
        ]["code"]
        == "not_found"
    )
    assert (
        _call(store, "calibrate", {"experiment_id": experiment_id, "config": {"nope": 1}})["error"]["code"]
        == "bad_request"
    )


def test_cli_calibrate(prepared, tmp_path, capsys):
    workspace, _store, experiment_id, config = prepared
    config_path = tmp_path / "calibration.json"
    config_path.write_text(json.dumps(config.model_dump(mode="json")), encoding="utf-8")

    # Dry run: no execution, exit 0.
    assert cli.main(["calibrate", experiment_id, "--config", str(config_path), "--dry-run", "--workspace", str(workspace)]) == 0
    assert "no model runs were executed" in capsys.readouterr().out

    code = cli.main(["calibrate", experiment_id, "--config", str(config_path), "--persist", "--workspace", str(workspace)])
    assert code == 0
    out = capsys.readouterr().out
    assert "best parameters" in out
    assert "stored calibration" in out
    assert CalibrationStore(workspace).list()


def test_cli_calibrate_error_codes(prepared, tmp_path, capsys):
    workspace, _store, experiment_id, config = prepared
    config_path = tmp_path / "calibration.json"
    config_path.write_text(json.dumps(config.model_dump(mode="json")), encoding="utf-8")
    # Unknown experiment -> exit 2.
    assert cli.main(["calibrate", "exp-000000000000", "--config", str(config_path), "--workspace", str(workspace)]) == 2
    # Missing config file -> exit 2.
    assert cli.main(["calibrate", experiment_id, "--config", str(tmp_path / "nope.json"), "--workspace", str(workspace)]) == 2


def test_capabilities_expose_calibration(prepared):
    _workspace, store, _experiment_id, _config = prepared
    response = _call(store, "capabilities", {"model_id": "predator-prey"})
    calibration = response["data"]["capabilities"]["calibration"]
    assert calibration["default_optimizer"] == "powell"
    assert "random_search" in calibration["optimizers"]
    assert "differential_evolution" in calibration["optimizers"]
