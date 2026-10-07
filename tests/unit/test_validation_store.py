"""Unit tests for the M12C validation store and staleness (Phase D)."""

from __future__ import annotations

import json

import pytest

from drw.schema.calibration import CalibrationRef, short_calibration_id
from drw.schema.evaluation import EvaluationConfig
from drw.schema.model import ModelRef
from drw.schema.observation import (
    DatasetRef,
    MappingPair,
    ObservationMapping,
    short_dataset_id,
)
from drw.schema.serialization import content_hash
from drw.schema.validation import (
    IndependenceReport,
    IndependenceSpec,
    ValidationCalibrationSnapshot,
    ValidationConfig,
    ValidationDataset,
    ValidationDatasetResult,
    ValidationProvenance,
    ValidationResult,
    compute_validation_result_hash,
    short_validation_id,
)
from drw.validation_store import (
    InvalidValidationId,
    ValidationExistsError,
    ValidationNotFoundError,
    ValidationStore,
    check_validation_staleness,
)

pytestmark = pytest.mark.unit

CAL_RESULT_HASH = "a" * 64
CAL_DATASET_HASH = "b" * 64
VAL_DATASET_HASH = "c" * 64
MODEL_HASH = "d" * 64
ENV_HASH = "e" * 64


def dataset_ref(content_hash: str) -> DatasetRef:
    return DatasetRef(
        dataset_id=short_dataset_id(content_hash), content_hash=content_hash, name="d"
    )


def mapping_for(content_hash: str) -> ObservationMapping:
    return ObservationMapping(
        dataset=dataset_ref(content_hash),
        model_ref=ModelRef(model_id="model"),
        pairs=(MappingPair(observation="y", output="y"),),
    )


def make_config() -> ValidationConfig:
    return ValidationConfig(
        experiment_id="exp-000000000000",
        model_ref=ModelRef(model_id="model"),
        calibration=CalibrationRef(
            calibration_id=short_calibration_id(CAL_RESULT_HASH),
            result_hash=CAL_RESULT_HASH,
            experiment_id="exp-000000000000",
            model_id="model",
            status="converged",
        ),
        datasets=(
            ValidationDataset(
                dataset=dataset_ref(VAL_DATASET_HASH),
                mapping=mapping_for(VAL_DATASET_HASH),
                independence=IndependenceSpec(vs_dataset=dataset_ref(CAL_DATASET_HASH)),
            ),
        ),
        evaluation=EvaluationConfig(),
    )


def make_result(**over) -> ValidationResult:
    config = over.pop("config", make_config())
    payload = {
        "validation_hash": config.content_hash(),
        "result_hash": "",
        "experiment_id": "exp-000000000000",
        "model_ref": ModelRef(model_id="model"),
        "config": config,
        "calibration": ValidationCalibrationSnapshot(
            calibration_id=config.calibration.calibration_id,
            result_hash=CAL_RESULT_HASH,
            calibration_hash="1" * 64,
            model_id="model",
            model_hash=MODEL_HASH,
            parameters={"a": 1.0},
            dataset_content_hash=CAL_DATASET_HASH,
            dataset_science_hash="2" * 64,
            mapping_hash="3" * 64,
        ),
        "datasets": (
            ValidationDatasetResult(
                dataset=dataset_ref(VAL_DATASET_HASH),
                mapping_hash=content_hash(mapping_for(VAL_DATASET_HASH)),
                independence=IndependenceReport(status="declared_only"),
                metrics={"rmse": 0.1},
                agreement="evaluated",
            ),
        ),
        "agreement_status": "evaluated",
        "acceptance_status": "not_specified",
        "independence_status": "declared_only",
        "evaluations_requested": 2,
        "evaluations_completed": 1,
        "evaluations_failed": 0,
        "wall_seconds": 0.1,
        "provenance": ValidationProvenance(
            experiment_id="exp-000000000000",
            model_id="model",
            model_hash=MODEL_HASH,
            calibration_result_hash=CAL_RESULT_HASH,
            calibration_hash="1" * 64,
            calibration_dataset_content_hash=CAL_DATASET_HASH,
            calibration_dataset_science_hash="2" * 64,
            calibration_mapping_hash="3" * 64,
            validation_dataset_content_hashes=(VAL_DATASET_HASH,),
            mapping_hashes=(content_hash(mapping_for(VAL_DATASET_HASH)),),
            evaluation_config_hash=content_hash(config.evaluation),
            environment_hash=ENV_HASH,
        ),
    }
    payload.update(over)
    result = ValidationResult(**payload)
    return result.model_copy(update={"result_hash": compute_validation_result_hash(result)})


# ---------------------------------------------------------------------------
# Store.
# ---------------------------------------------------------------------------


def test_save_load_round_trip(tmp_path):
    store = ValidationStore(tmp_path)
    result = make_result()
    ref = store.save(result)
    assert ref.validation_id == short_validation_id(result.result_hash)
    assert store.exists(ref.validation_id)
    loaded = store.load(ref.validation_id)
    assert loaded.result_hash == result.result_hash
    assert loaded.datasets[0].metrics == {"rmse": 0.1}
    assert loaded.agreement_status == "evaluated"


def test_save_is_idempotent(tmp_path):
    store = ValidationStore(tmp_path)
    result = make_result()
    first = store.save(result)
    second = store.save(result)
    assert first.validation_id == second.validation_id
    assert len(store.list()) == 1


def test_list_and_ref(tmp_path):
    store = ValidationStore(tmp_path)
    result = make_result()
    store.save(result)
    refs = store.list()
    assert len(refs) == 1
    assert refs[0].agreement_status == "evaluated"
    assert refs[0].experiment_id == "exp-000000000000"


def test_verify_ok(tmp_path):
    store = ValidationStore(tmp_path)
    result = make_result()
    ref = store.save(result)
    report = store.verify(ref.validation_id)
    assert report.ok is True
    assert any(check.name == "result_hash" for check in report.checks)


def test_verify_detects_tampering(tmp_path):
    store = ValidationStore(tmp_path)
    result = make_result()
    ref = store.save(result)
    target = store.directory(ref.validation_id) / "provenance.json"
    target.write_text("{}\n", encoding="utf-8")
    report = store.verify(ref.validation_id)
    assert report.ok is False
    assert report.errors >= 1


def test_conflicting_payload_rejected(tmp_path):
    store = ValidationStore(tmp_path)
    result = make_result()
    validation_id = short_validation_id(result.result_hash)
    directory = store.directory(validation_id)
    directory.mkdir(parents=True)
    (directory / "manifest.json").write_text(
        json.dumps(
            {
                "result_hash": "0" * 64,
                "experiment_id": "x",
                "model_id": "y",
                "agreement_status": "failed",
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValidationExistsError):
        store.save(result)


def test_missing_and_invalid_ids(tmp_path):
    store = ValidationStore(tmp_path)
    with pytest.raises(ValidationNotFoundError):
        store.load("val-" + "0" * 12)
    with pytest.raises(InvalidValidationId):
        store.load("../escape")


# ---------------------------------------------------------------------------
# Staleness.
# ---------------------------------------------------------------------------


class _CalibrationStore:
    def __init__(self, result_hash: str) -> None:
        self._result_hash = result_hash

    def load(self, calibration_id: str):
        return type("Calibration", (), {"result_hash": self._result_hash})()


class _DatasetStore:
    def __init__(self, available: bool) -> None:
        self._available = available

    def resolve(self, content_hash: str):
        return object() if self._available else None


def test_staleness_fresh():
    result = make_result()
    report = check_validation_staleness(
        result,
        calibration_store=_CalibrationStore(CAL_RESULT_HASH),
        dataset_store=_DatasetStore(True),
        current_model_hash=MODEL_HASH,
        current_environment_hash=ENV_HASH,
    )
    assert report.fresh is True
    assert report.reasons == []


def test_staleness_when_calibration_result_changed():
    result = make_result()
    report = check_validation_staleness(
        result,
        calibration_store=_CalibrationStore("9" * 64),
        dataset_store=_DatasetStore(True),
    )
    assert report.fresh is False
    assert "calibration_result_changed" in report.reasons


def test_staleness_when_datasets_missing():
    result = make_result()
    report = check_validation_staleness(
        result,
        calibration_store=_CalibrationStore(CAL_RESULT_HASH),
        dataset_store=_DatasetStore(False),
    )
    assert report.fresh is False
    assert "calibration_dataset_missing" in report.reasons
    assert "validation_dataset_missing" in report.reasons


def test_staleness_when_model_changed():
    result = make_result()
    report = check_validation_staleness(result, current_model_hash="9" * 64)
    assert report.fresh is False
    assert "model_changed" in report.reasons


def test_staleness_when_evaluation_config_changed():
    result = make_result()
    broken = result.model_copy(
        update={
            "provenance": result.provenance.model_copy(
                update={"evaluation_config_hash": "0" * 64}
            )
        }
    )
    report = check_validation_staleness(broken)
    assert report.fresh is False
    assert "evaluation_config_changed" in report.reasons


def test_staleness_when_environment_changed():
    result = make_result()
    report = check_validation_staleness(result, current_environment_hash="9" * 64)
    assert report.fresh is False
    assert "environment_changed" in report.reasons
