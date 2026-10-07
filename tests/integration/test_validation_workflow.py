"""Integration tests: validation through the CLI and the bridge, with the store."""

from __future__ import annotations

import json
import shutil

import pytest

from drw import cli
from drw.api import handle
from drw.calibration import calibrate_for_experiment
from drw.calibration_store import CalibrationStore
from drw.dataset_store import DatasetStore
from drw.execution.runner import Runner
from drw.models.registry import build_model
from drw.observations import build_dataset
from drw.schema.calibration import (
    BudgetSpec,
    CalibrationConfig,
    CalibrationRef,
    ExecutionTemplate,
    ObjectiveConfig,
    OptimizerConfig,
    ParameterSelection,
    short_calibration_id,
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
from drw.schema.validation import (
    IndependenceSpec,
    ValidationConfig,
    ValidationDataset,
)
from drw.store import ExperimentStore
from drw.validation_store import ValidationStore

pytestmark = pytest.mark.integration


def _provenance() -> Provenance:
    return Provenance(
        source_kind="synthetic", imported_at="2026-01-01T00:00:00+00:00", dataset_version="1.0.0"
    )


def _scalar_dataset(name: str, values: list[float]):
    return build_dataset(
        name,
        ObservationSet(
            variables=(
                Variable(name="peak_prey", kind="float", role="measurement", unit="count"),
            ),
            columns={"peak_prey": values},
        ),
        _provenance(),
    )


def _mapping(dataset, model_id: str = "predator-prey") -> ObservationMapping:
    return ObservationMapping(
        dataset=dataset.ref(),
        model_ref=ModelRef(model_id=model_id),
        pairs=(MappingPair(observation="peak_prey", output="peak_prey"),),
    )


@pytest.fixture
def prepared(tmp_path):
    workspace = tmp_path / "ws"
    experiment_store = ExperimentStore(workspace)
    dataset_store = DatasetStore(workspace)

    spec = ExperimentSpec(
        name="validate base",
        hypothesis="validate a calibrated model",
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

    calibration_dataset = _scalar_dataset("observed peak", [peak - 0.5, peak, peak + 0.5])
    dataset_store.save(calibration_dataset)

    alpha = build_model("predator-prey").describe().parameter("alpha")
    calibration_config = CalibrationConfig(
        experiment_id=experiment_id,
        model_ref=ModelRef(model_id="predator-prey"),
        free=(
            ParameterSelection(name="alpha", lower=alpha.lower, upper=alpha.upper, initial=1.1),
        ),
        objective=ObjectiveConfig(metric="rmse"),
        optimizer=OptimizerConfig(name="random_search"),
        budget=BudgetSpec(max_evaluations=2),
        seed=0,
        execution=ExecutionTemplate(isolation="in_process", timeout_s=30.0),
        dataset=calibration_dataset.ref(),
        mapping=_mapping(calibration_dataset),
        evaluation=EvaluationConfig(),
        identifiability="off",
    )
    calibration = calibrate_for_experiment(experiment_id, experiment_store, calibration_config)
    CalibrationStore(experiment_store.root).save(calibration)

    validation_dataset = _scalar_dataset("held out", [peak + 1.0, peak + 1.5, peak + 2.0])
    dataset_store.save(validation_dataset)

    config = ValidationConfig(
        experiment_id=experiment_id,
        model_ref=ModelRef(model_id="predator-prey"),
        calibration=CalibrationRef(
            calibration_id=short_calibration_id(calibration.result_hash),
            result_hash=calibration.result_hash,
            experiment_id=calibration.experiment_id,
            model_id="predator-prey",
            status=calibration.status,
        ),
        datasets=(
            ValidationDataset(
                dataset=validation_dataset.ref(),
                mapping=_mapping(validation_dataset),
                independence=IndependenceSpec(
                    vs_dataset=calibration_dataset.ref(),
                    claimed_dimensions=("dataset",),
                ),
            ),
        ),
        evaluation=EvaluationConfig(),
        execution=ExecutionTemplate(isolation="in_process", timeout_s=30.0),
    )
    return workspace, experiment_store, experiment_id, config, calibration_dataset


def _call(store, op, params):
    return handle({"op": op, "params": params}, store=store)


# ---------------------------------------------------------------------------
# Bridge.
# ---------------------------------------------------------------------------


def test_bridge_run_validation_and_store(prepared):
    _workspace, store, experiment_id, config, _cal_dataset = prepared
    response = _call(
        store,
        "run_validation",
        {
            "experiment_id": experiment_id,
            "config": config.model_dump(mode="json"),
            "persist": True,
        },
    )
    assert response["ok"] is True, response
    validation = response["data"]["validation"]
    assert validation["agreement_status"] in ("evaluated", "partial")
    assert len(validation["datasets"]) == 1
    assert validation["datasets"][0]["agreement"] == "evaluated"
    assert validation["independence_status"] == "verified"
    ref = response["data"]["ref"]
    assert ref["validation_id"].startswith("val-")

    listed = _call(store, "list_validations", {})
    assert any(item["validation_id"] == ref["validation_id"] for item in listed["data"]["validations"])

    fetched = _call(store, "get_validation", {"validation_id": ref["validation_id"]})
    assert fetched["data"]["validation"]["result_hash"] == validation["result_hash"]

    verified = _call(store, "verify_validation", {"validation_id": ref["validation_id"]})
    assert verified["data"]["verification"]["ok"] is True

    staleness = _call(store, "check_validation_staleness", {"validation_id": ref["validation_id"]})
    assert staleness["data"]["staleness"]["fresh"] is True


def test_bridge_run_validation_errors(prepared):
    _workspace, store, experiment_id, config, _cal_dataset = prepared
    assert _call(store, "run_validation", {}).get("error", {}).get("code") == "bad_request"
    assert (
        _call(
            store,
            "run_validation",
            {"experiment_id": "exp-000000000000", "config": config.model_dump(mode="json")},
        )["error"]["code"]
        == "not_found"
    )
    assert (
        _call(
            store,
            "run_validation",
            {"experiment_id": experiment_id, "config": {"nope": 1}},
        )["error"]["code"]
        == "bad_request"
    )


def test_bridge_staleness_after_dataset_removed(prepared):
    _workspace, store, experiment_id, config, _cal_dataset = prepared
    response = _call(
        store,
        "run_validation",
        {"experiment_id": experiment_id, "config": config.model_dump(mode="json"), "persist": True},
    )
    validation_id = response["data"]["ref"]["validation_id"]
    # Remove the validation dataset from the workspace.
    dataset_id = config.datasets[0].dataset.dataset_id
    shutil.rmtree(DatasetStore(store.root).dataset_dir(dataset_id))
    staleness = _call(store, "check_validation_staleness", {"validation_id": validation_id})
    assert staleness["data"]["staleness"]["fresh"] is False
    assert "validation_dataset_missing" in staleness["data"]["staleness"]["reasons"]


# ---------------------------------------------------------------------------
# CLI.
# ---------------------------------------------------------------------------


def test_cli_validation_run_and_inspect(prepared, tmp_path, capsys):
    workspace, _store, experiment_id, config, _cal_dataset = prepared
    config_path = tmp_path / "validation.json"
    config_path.write_text(json.dumps(config.model_dump(mode="json")), encoding="utf-8")

    assert (
        cli.main(
            ["validation", "run", experiment_id, "--config", str(config_path), "--dry-run", "--workspace", str(workspace)]
        )
        == 0
    )
    assert "no model runs were executed" in capsys.readouterr().out

    code = cli.main(
        ["validation", "run", experiment_id, "--config", str(config_path), "--persist", "--json", "--workspace", str(workspace)]
    )
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["agreement_status"] in ("evaluated", "partial")
    validation_id = payload["validation_id"]

    assert cli.main(["validation", "list", "--workspace", str(workspace)]) == 0
    assert validation_id in capsys.readouterr().out

    assert cli.main(["validation", "get", validation_id, "--workspace", str(workspace)]) == 0
    assert "agreement=" in capsys.readouterr().out

    assert cli.main(["validation", "verify", validation_id, "--workspace", str(workspace)]) == 0

    assert cli.main(["validation", "staleness", validation_id, "--workspace", str(workspace)]) == 0
    assert "fresh" in capsys.readouterr().out


def test_cli_validation_error_codes(prepared, tmp_path):
    workspace, _store, experiment_id, config, _cal_dataset = prepared
    config_path = tmp_path / "validation.json"
    config_path.write_text(json.dumps(config.model_dump(mode="json")), encoding="utf-8")
    assert (
        cli.main(["validation", "run", "exp-000000000000", "--config", str(config_path), "--workspace", str(workspace)])
        == 2
    )
    assert (
        cli.main(["validation", "run", experiment_id, "--config", str(tmp_path / "nope.json"), "--workspace", str(workspace)])
        == 2
    )


def test_capabilities_expose_validation(prepared):
    _workspace, store, _experiment_id, _config, _cal_dataset = prepared
    response = _call(store, "capabilities", {"model_id": "predator-prey"})
    validation = response["data"]["capabilities"]["validation"]
    assert validation["default_metrics"] == ["rmse", "mae", "max_abs_error"]
    assert "dataset" in validation["verifiable_dimensions"]
    assert "measurement_process" in validation["declared_dimensions"]
    assert validation["default_max_evaluations"] == 10


def test_validation_store_round_trip(prepared):
    _workspace, store, experiment_id, config, _cal_dataset = prepared
    response = _call(
        store,
        "run_validation",
        {"experiment_id": experiment_id, "config": config.model_dump(mode="json"), "persist": True},
    )
    validation_id = response["data"]["ref"]["validation_id"]
    result = ValidationStore(store.root).load(validation_id)
    assert result.agreement_status in ("evaluated", "partial")
    assert ValidationStore(store.root).verify(validation_id).ok is True
