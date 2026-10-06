"""Unit tests for the M12B calibration store (Phase D)."""

from __future__ import annotations

import json

import pytest

from drw.calibration_store import (
    CalibrationExistsError,
    CalibrationNotFoundError,
    CalibrationStore,
    InvalidCalibrationId,
)
from drw.schema.calibration import (
    BudgetSpec,
    CalibrationCandidateSummary,
    CalibrationConfig,
    CalibrationObjective,
    CalibrationProvenance,
    CalibrationResult,
    ExecutionTemplate,
    ObjectiveConfig,
    ParameterSelection,
    compute_calibration_hash,
    compute_result_hash,
    short_calibration_id,
)
from drw.schema.evaluation import EvaluationConfig
from drw.schema.model import ModelRef
from drw.schema.observation import (
    DatasetRef,
    MappingPair,
    ObservationMapping,
    short_dataset_id,
)

pytestmark = pytest.mark.unit

HASH = "a" * 64


def make_config(**over) -> CalibrationConfig:
    ref = DatasetRef(dataset_id=short_dataset_id(HASH), content_hash=HASH, name="d")
    payload = {
        "experiment_id": "exp-000000000000",
        "model_ref": ModelRef(model_id="model"),
        "free": (ParameterSelection(name="a", lower=0.0, upper=10.0, initial=1.0),),
        "objective": ObjectiveConfig(),
        "budget": BudgetSpec(),
        "execution": ExecutionTemplate(),
        "dataset": ref,
        "mapping": ObservationMapping(
            dataset=ref, model_ref=ModelRef(model_id="model"),
            pairs=(MappingPair(observation="y", output="y"),),
        ),
        "evaluation": EvaluationConfig(),
    }
    payload.update(over)
    return CalibrationConfig(**payload)


def make_provenance() -> CalibrationProvenance:
    return CalibrationProvenance(
        experiment_id="exp-000000000000",
        model_id="model",
        model_hash="b" * 64,
        environment_hash="c" * 64,
        scipy_version="1.11.0",
        dataset_content_hash=HASH,
        dataset_science_hash="d" * 64,
        mapping_hash="e" * 64,
        evaluation_config_hash="f" * 64,
    )


def make_result(**over) -> CalibrationResult:
    config = over.pop("config", make_config())
    candidate = CalibrationCandidateSummary(
        index=0, parameters={"a": 2.0}, run_id="r0", run_status="succeeded", objective=0.0
    )
    payload = {
        "calibration_hash": compute_calibration_hash(config),
        "result_hash": "",
        "experiment_id": "exp-000000000000",
        "model_ref": ModelRef(model_id="model"),
        "config": config,
        "status": "converged",
        "stop_reason": "optimizer_converged",
        "converged": True,
        "best": candidate,
        "objective": CalibrationObjective(metric="rmse", observation="y", output="y", value=0.0),
        "evaluations_requested": 5,
        "evaluations_completed": 5,
        "evaluations_invalid": 0,
        "iterations": 3,
        "wall_seconds": 0.5,
        "history": [candidate],
        "provenance": make_provenance(),
    }
    payload.update(over)
    result = CalibrationResult(**payload)
    return result.model_copy(update={"result_hash": compute_result_hash(result)})


def test_save_load_round_trip(tmp_path):
    store = CalibrationStore(tmp_path)
    result = make_result()
    ref = store.save(result)
    assert ref.calibration_id == short_calibration_id(result.result_hash)
    assert store.exists(ref.calibration_id)
    loaded = store.load(ref.calibration_id)
    assert loaded.result_hash == result.result_hash
    assert loaded.history[0].parameters == {"a": 2.0}
    assert loaded.best is not None and loaded.best.objective == 0.0


def test_save_is_idempotent(tmp_path):
    store = CalibrationStore(tmp_path)
    result = make_result()
    first = store.save(result)
    second = store.save(result)
    assert first.calibration_id == second.calibration_id
    assert first.result_hash == second.result_hash
    assert len(store.list()) == 1


def test_list_and_ref(tmp_path):
    store = CalibrationStore(tmp_path)
    a = make_result()
    store.save(a)
    refs = store.list()
    assert len(refs) == 1
    assert refs[0].calibration_id == short_calibration_id(a.result_hash)
    assert refs[0].experiment_id == "exp-000000000000"


def test_verify_ok(tmp_path):
    store = CalibrationStore(tmp_path)
    result = make_result()
    ref = store.save(result)
    report = store.verify(ref.calibration_id)
    assert report.ok is True
    assert report.errors == 0
    assert any(check.name == "result_hash" for check in report.checks)


def test_verify_detects_tampering(tmp_path):
    store = CalibrationStore(tmp_path)
    result = make_result()
    ref = store.save(result)
    target = store.directory(ref.calibration_id) / "history.json"
    target.write_text("[]\n", encoding="utf-8")
    report = store.verify(ref.calibration_id)
    assert report.ok is False
    assert report.errors >= 1


def test_conflicting_payload_under_existing_id_rejected(tmp_path):
    store = CalibrationStore(tmp_path)
    result = make_result()
    calibration_id = short_calibration_id(result.result_hash)
    directory = store.directory(calibration_id)
    directory.mkdir(parents=True)
    (directory / "manifest.json").write_text(
        json.dumps({"result_hash": "0" * 64, "experiment_id": "x", "model_id": "y", "status": "failed"}),
        encoding="utf-8",
    )
    with pytest.raises(CalibrationExistsError):
        store.save(result)


def test_missing_and_invalid_ids(tmp_path):
    store = CalibrationStore(tmp_path)
    with pytest.raises(CalibrationNotFoundError):
        store.load("cal-" + "0" * 12)
    with pytest.raises(InvalidCalibrationId):
        store.load("../escape")
