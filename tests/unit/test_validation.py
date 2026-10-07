"""Unit tests for the M12C validation contract (Phase A)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError as PydanticValidationError

from drw.schema.calibration import (
    CalibrationCandidateSummary,
    CalibrationObjective,
    CalibrationProvenance,
    CalibrationRef,
    CalibrationResult,
    ExecutionTemplate,
    FixedParameter,
    short_calibration_id,
)
from drw.schema.calibration import (
    compute_result_hash as compute_calibration_result_hash,
)
from drw.schema.evaluation import EvaluationConfig
from drw.schema.model import ModelRef, ModelSchema, OutputSpec, ParameterSpec
from drw.schema.observation import (
    DatasetRef,
    MappingPair,
    ObservationMapping,
    short_dataset_id,
)
from drw.schema.validation import (
    DEFAULT_VALIDATION_DISCLOSURE,
    AcceptanceCriterion,
    CoordinateWindow,
    IndependenceSpec,
    ValidationBudget,
    ValidationCalibrationSnapshot,
    ValidationConfig,
    ValidationConfigError,
    ValidationDataset,
    ValidationDatasetResult,
    ValidationProvenance,
    ValidationRef,
    ValidationResult,
    build_frozen_vector,
    compute_validation_hash,
    compute_validation_result_hash,
    resolve_validation,
    short_validation_id,
    validate_validation_config,
    validation_identity_payload,
)

pytestmark = pytest.mark.unit

CAL_HASH = "a" * 64
VAL_HASH = "b" * 64
VAL_HASH_2 = "c" * 64

SCHEMA = ModelSchema(
    model_id="model",
    parameters=(
        ParameterSpec(name="a", type="float", unit="u", nominal=2.0, lower=0.0, upper=10.0),
        ParameterSpec(name="b", type="float", nominal=1.0, lower=-5.0, upper=5.0),
        ParameterSpec(name="c", type="float", nominal=3.0),
    ),
    outputs=(OutputSpec(name="y", kind="scalar", unit="u"),),
)
BASELINE = {"a": 2.0, "b": 1.0, "c": 3.0}


def dataset_ref(content_hash: str) -> DatasetRef:
    return DatasetRef(
        dataset_id=short_dataset_id(content_hash), content_hash=content_hash, name="d"
    )


def mapping_for(content_hash: str, pairs=(("y", "y"),)) -> ObservationMapping:
    return ObservationMapping(
        dataset=dataset_ref(content_hash),
        model_ref=ModelRef(model_id="model"),
        pairs=tuple(MappingPair(observation=o, output=m) for o, m in pairs),
    )


def calibration_result(**over) -> CalibrationResult:
    """A converged calibration whose free parameter is ``a`` → 4.0."""
    ref = dataset_ref(CAL_HASH)
    from drw.schema.calibration import CalibrationConfig, ObjectiveConfig, ParameterSelection

    config = CalibrationConfig(
        experiment_id="exp-000000000000",
        model_ref=ModelRef(model_id="model"),
        free=(ParameterSelection(name="a", lower=0.0, upper=10.0),),
        objective=ObjectiveConfig(),
        execution=ExecutionTemplate(),
        dataset=ref,
        mapping=mapping_for(CAL_HASH),
        evaluation=EvaluationConfig(),
    )
    candidate = CalibrationCandidateSummary(
        index=0, parameters={"a": 4.0}, run_id="r0", run_status="succeeded", objective=0.0
    )
    payload = {
        "calibration_hash": CAL_HASH,
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
        "provenance": CalibrationProvenance(
            experiment_id="exp-000000000000",
            model_id="model",
            model_hash="b" * 64,
            environment_hash="c" * 64,
            scipy_version="1.11.0",
            dataset_content_hash=CAL_HASH,
            dataset_science_hash="d" * 64,
            mapping_hash="e" * 64,
            evaluation_config_hash="f" * 64,
        ),
    }
    payload.update(over)
    result = CalibrationResult(**payload)
    return result.model_copy(
        update={"result_hash": compute_calibration_result_hash(result)}
    )


def calibration_ref(result: CalibrationResult | None = None) -> CalibrationRef:
    result = result or calibration_result()
    return CalibrationRef(
        calibration_id=short_calibration_id(result.result_hash),
        result_hash=result.result_hash,
        experiment_id=result.experiment_id,
        model_id="model",
        status=result.status,
    )


def make_dataset(content_hash: str = VAL_HASH, **over) -> ValidationDataset:
    payload = {
        "dataset": dataset_ref(content_hash),
        "mapping": mapping_for(content_hash),
        "independence": IndependenceSpec(vs_dataset=dataset_ref(CAL_HASH)),
    }
    payload.update(over)
    return ValidationDataset(**payload)


def make_config(**over) -> ValidationConfig:
    payload = {
        "experiment_id": "exp-000000000000",
        "model_ref": ModelRef(model_id="model"),
        "calibration": calibration_ref(),
        "datasets": (make_dataset(),),
        "evaluation": EvaluationConfig(),
    }
    payload.update(over)
    return ValidationConfig(**payload)


def make_dataset_result(**over) -> ValidationDatasetResult:
    from drw.schema.validation import IndependenceReport, ValidationContext

    payload = {
        "dataset": dataset_ref(VAL_HASH),
        "mapping_hash": "1" * 64,
        "independence": IndependenceReport(status="declared_only"),
        "context": ValidationContext(),
        "metrics": {"rmse": 0.1},
        "agreement": "evaluated",
    }
    payload.update(over)
    return ValidationDatasetResult(**payload)


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
            result_hash=config.calibration.result_hash,
            calibration_hash="a" * 64,
            model_id="model",
            model_hash="b" * 64,
            parameters={"a": 4.0},
            dataset_content_hash=CAL_HASH,
            dataset_science_hash="d" * 64,
            mapping_hash="e" * 64,
        ),
        "datasets": (make_dataset_result(),),
        "agreement_status": "evaluated",
        "acceptance_status": "not_specified",
        "independence_status": "declared_only",
        "evaluations_requested": 1,
        "evaluations_completed": 1,
        "evaluations_failed": 0,
        "wall_seconds": 0.1,
        "provenance": ValidationProvenance(
            experiment_id="exp-000000000000",
            model_id="model",
            model_hash="b" * 64,
            calibration_result_hash=config.calibration.result_hash,
            calibration_hash="a" * 64,
            calibration_dataset_content_hash=CAL_HASH,
            calibration_dataset_science_hash="d" * 64,
            calibration_mapping_hash="e" * 64,
            evaluation_config_hash="f" * 64,
            environment_hash="0" * 64,
        ),
    }
    payload.update(over)
    result = ValidationResult(**payload)
    return result.model_copy(update={"result_hash": compute_validation_result_hash(result)})


# ---------------------------------------------------------------------------
# Construction and identity.
# ---------------------------------------------------------------------------


def test_config_constructs_and_hashes_deterministically():
    a = make_config()
    b = make_config()
    assert a.content_hash() == b.content_hash()
    assert len(a.content_hash()) == 64
    assert compute_validation_hash(a) == a.content_hash()
    assert a.data_role == "validation"
    assert a.report_gap is True
    assert a.allow_non_independent is False


def test_hash_is_independent_of_dataset_declaration_order():
    forwards = make_config(datasets=(make_dataset(VAL_HASH), make_dataset(VAL_HASH_2)))
    backwards = make_config(datasets=(make_dataset(VAL_HASH_2), make_dataset(VAL_HASH)))
    assert forwards.content_hash() == backwards.content_hash()


def test_hash_ignores_notes_and_calibration_created_at():
    base = make_config()
    annotated = make_config(notes="hello")
    assert base.content_hash() == annotated.content_hash()
    ref = calibration_ref()
    stamped = ref.model_copy(update={"created_at": "2026-01-01T00:00:00+00:00"})
    assert base.content_hash() == make_config(calibration=stamped).content_hash()


@pytest.mark.parametrize(
    "change",
    [
        {"budget": ValidationBudget(max_evaluations=3)},
        {"execution": ExecutionTemplate(timeout_s=5.0)},
        {"report_gap": False},
        {"allow_non_independent": True},
        {"evaluation": EvaluationConfig(metrics=("mae", "rmse"))},
        {"acceptance": (AcceptanceCriterion(metric="rmse", op="<=", threshold=0.5),)},
        {
            "datasets": (
                make_dataset(
                    independence=IndependenceSpec(
                        vs_dataset=dataset_ref(CAL_HASH),
                        claimed_dimensions=("dataset",),
                    )
                ),
            )
        },
    ],
)
def test_hash_changes_with_scientific_configuration(change):
    assert make_config().content_hash() != make_config(**change).content_hash()


def test_identity_payload_excludes_notes_and_created_at():
    payload = validation_identity_payload(make_config(notes="x"))
    assert "notes" not in payload
    assert "created_at" not in payload["calibration"]
    assert set(payload["calibration"]) == {
        "calibration_id",
        "result_hash",
        "experiment_id",
        "model_id",
        "status",
    }


# ---------------------------------------------------------------------------
# Structural validation.
# ---------------------------------------------------------------------------


def test_empty_datasets_rejected():
    with pytest.raises(PydanticValidationError, match="at least one validation dataset"):
        make_config(datasets=())


def test_duplicate_dataset_rejected():
    with pytest.raises(PydanticValidationError, match="duplicate validation datasets"):
        make_config(datasets=(make_dataset(), make_dataset()))


def test_mapping_model_mismatch_rejected():
    bad = ObservationMapping(
        dataset=dataset_ref(VAL_HASH),
        model_ref=ModelRef(model_id="other"),
        pairs=(MappingPair(observation="y", output="y"),),
    )
    with pytest.raises(PydanticValidationError, match=r"mapping does not match model_ref"):
        make_config(
            datasets=(
                ValidationDataset(
                    dataset=dataset_ref(VAL_HASH),
                    mapping=bad,
                    independence=IndependenceSpec(vs_dataset=dataset_ref(CAL_HASH)),
                ),
            )
        )


def test_mapping_dataset_mismatch_rejected():
    with pytest.raises(PydanticValidationError, match=r"mapping\.dataset"):
        ValidationDataset(
            dataset=dataset_ref(VAL_HASH),
            mapping=mapping_for(VAL_HASH_2),
            independence=IndependenceSpec(vs_dataset=dataset_ref(CAL_HASH)),
        )


def test_calibration_model_mismatch_rejected():
    ref = calibration_ref().model_copy(update={"model_id": "other"})
    with pytest.raises(PydanticValidationError, match=r"calibration\.model_id"):
        make_config(calibration=ref)


def test_acceptance_metric_must_be_requested():
    with pytest.raises(PydanticValidationError, match=r"not requested in evaluation\.metrics"):
        make_config(
            acceptance=(AcceptanceCriterion(metric="weighted_rmse", op="<=", threshold=0.5),)
        )


def test_multi_pair_acceptance_requires_selector():
    mapping = mapping_for(VAL_HASH, pairs=(("y", "y"), ("p", "p")))
    dataset = ValidationDataset(
        dataset=dataset_ref(VAL_HASH),
        mapping=mapping,
        independence=IndependenceSpec(vs_dataset=dataset_ref(CAL_HASH)),
        acceptance=(AcceptanceCriterion(metric="rmse", op="<=", threshold=0.5),),
    )
    with pytest.raises(PydanticValidationError, match="select a pair"):
        make_config(datasets=(dataset,))


def test_acceptance_pair_selector_both_or_neither():
    with pytest.raises(PydanticValidationError, match="both observation and output"):
        AcceptanceCriterion(metric="rmse", observation="y", op="<=", threshold=0.5)


def test_acceptance_threshold_must_be_finite():
    with pytest.raises(PydanticValidationError, match="finite"):
        AcceptanceCriterion(metric="rmse", op="<=", threshold=float("inf"))


def test_coordinate_window_requires_a_bound():
    with pytest.raises(PydanticValidationError, match="at least one bound"):
        CoordinateWindow(coordinate="time")


def test_coordinate_window_ordering():
    with pytest.raises(PydanticValidationError, match="lower must be <= upper"):
        CoordinateWindow(coordinate="time", lower=2.0, upper=1.0)


def test_independence_spec_rejects_duplicate_claimed_dimensions():
    with pytest.raises(PydanticValidationError, match="duplicate claimed dimensions"):
        IndependenceSpec(vs_dataset=dataset_ref(CAL_HASH), claimed_dimensions=("entity", "entity"))


def test_independence_spec_rejects_duplicate_windows():
    with pytest.raises(PydanticValidationError, match="duplicate coordinate windows"):
        IndependenceSpec(
            vs_dataset=dataset_ref(CAL_HASH),
            coordinate_windows=(
                CoordinateWindow(coordinate="t", lower=0.0, upper=1.0),
                CoordinateWindow(coordinate="t", lower=0.0, upper=1.0),
            ),
        )


def test_execution_template_requires_single_run():
    with pytest.raises(PydanticValidationError):
        ExecutionTemplate(max_runs=2)


def test_budget_validation():
    with pytest.raises(PydanticValidationError):
        ValidationBudget(max_evaluations=0)
    with pytest.raises(PydanticValidationError):
        ValidationBudget(max_wall_seconds=0.0)
    with pytest.raises(PydanticValidationError):
        ValidationBudget(max_failed=0)


# ---------------------------------------------------------------------------
# Frozen parameter vector.
# ---------------------------------------------------------------------------


def test_frozen_vector_uses_best_then_fixed_then_baseline_then_nominal():
    result = calibration_result()
    frozen = build_frozen_vector(result, SCHEMA, BASELINE)
    assert frozen == {"a": 4.0, "b": 1.0, "c": 3.0}


def test_frozen_vector_uses_nominal_when_no_baseline():
    frozen = build_frozen_vector(calibration_result(), SCHEMA, {})
    assert frozen == {"a": 4.0, "b": 1.0, "c": 3.0}


def test_frozen_vector_applies_explicit_fixed_override():
    from drw.schema.calibration import CalibrationConfig, ObjectiveConfig, ParameterSelection

    config = CalibrationConfig(
        experiment_id="exp-000000000000",
        model_ref=ModelRef(model_id="model"),
        free=(ParameterSelection(name="a", lower=0.0, upper=10.0),),
        fixed=(FixedParameter(name="b", value=4.0),),
        objective=ObjectiveConfig(),
        execution=ExecutionTemplate(),
        dataset=dataset_ref(CAL_HASH),
        mapping=mapping_for(CAL_HASH),
        evaluation=EvaluationConfig(),
    )
    result = calibration_result(config=config)
    frozen = build_frozen_vector(result, SCHEMA, {})
    assert frozen["b"] == 4.0


def test_frozen_vector_rejects_out_of_bounds():
    result = calibration_result()
    result = result.model_copy(
        update={
            "best": CalibrationCandidateSummary(index=0, parameters={"a": 99.0}, objective=0.0)
        }
    )
    with pytest.raises(ValidationConfigError, match="above the model bound"):
        build_frozen_vector(result, SCHEMA, {})


def test_frozen_vector_rejects_non_finite():
    result = calibration_result()
    result = result.model_copy(
        update={
            "best": CalibrationCandidateSummary(
                index=0, parameters={"a": float("nan")}, objective=0.0
            )
        }
    )
    with pytest.raises(ValidationConfigError, match="not a finite number"):
        build_frozen_vector(result, SCHEMA, {})


def test_frozen_vector_rejects_unknown_calibrated_parameter():
    result = calibration_result()
    result = result.model_copy(
        update={
            "best": CalibrationCandidateSummary(
                index=0, parameters={"a": 4.0, "zzz": 1.0}, objective=0.0
            )
        }
    )
    with pytest.raises(ValidationConfigError, match="not a parameter of model"):
        build_frozen_vector(result, SCHEMA, {})


def test_frozen_vector_requires_a_best():
    result = calibration_result(best=None)
    with pytest.raises(ValidationConfigError, match="no best candidate"):
        build_frozen_vector(result, SCHEMA, {})


# ---------------------------------------------------------------------------
# Model-aware resolution.
# ---------------------------------------------------------------------------


def test_validate_config_ok_when_executable():
    assert validate_validation_config(make_config(), SCHEMA, calibration_result(), BASELINE) == ()


def test_resolve_validation_returns_frozen_vector():
    frozen = resolve_validation(make_config(), SCHEMA, calibration_result(), BASELINE)
    assert frozen["a"] == 4.0


def test_resolve_rejects_model_mismatch():
    schema = ModelSchema(
        model_id="other", parameters=SCHEMA.parameters, outputs=SCHEMA.outputs
    )
    diagnostics = validate_validation_config(make_config(), schema, calibration_result(), BASELINE)
    assert any(d.code == "model_mismatch" for d in diagnostics)


def test_resolve_rejects_independence_target_mismatch():
    wrong = IndependenceSpec(vs_dataset=dataset_ref(VAL_HASH))
    config = make_config(datasets=(make_dataset(independence=wrong),))
    diagnostics = validate_validation_config(config, SCHEMA, calibration_result(), BASELINE)
    assert any(d.code == "independence_target_mismatch" for d in diagnostics)
    with pytest.raises(ValidationConfigError, match="independence"):
        resolve_validation(config, SCHEMA, calibration_result(), BASELINE)


# ---------------------------------------------------------------------------
# Result identity.
# ---------------------------------------------------------------------------


def test_result_hash_is_deterministic_and_excludes_itself():
    a = make_result()
    b = make_result()
    assert a.result_hash == b.result_hash
    assert compute_validation_result_hash(a) == a.result_hash
    assert len(a.result_hash) == 64


def test_result_hash_excludes_wall_seconds():
    a = make_result()
    b = make_result(wall_seconds=999.0)
    assert a.result_hash == b.result_hash


def test_result_hash_changes_with_metrics():
    a = make_result()
    b = make_result(datasets=(make_dataset_result(metrics={"rmse": 0.2}),))
    assert a.result_hash != b.result_hash


def test_validation_ref_identity():
    result = make_result()
    ref = ValidationRef(
        validation_id=short_validation_id(result.result_hash),
        result_hash=result.result_hash,
        experiment_id=result.experiment_id,
        model_id="model",
        agreement_status=result.agreement_status,
    )
    assert ref.validation_id == short_validation_id(result.result_hash)
    with pytest.raises(PydanticValidationError):
        ValidationRef(
            validation_id="val-" + "0" * 12,
            result_hash=result.result_hash,
            experiment_id=result.experiment_id,
            model_id="model",
            agreement_status="evaluated",
        )


def test_default_disclosure_is_honest():
    assert "does not establish that the model is correct" in DEFAULT_VALIDATION_DISCLOSURE
    assert make_result().note == DEFAULT_VALIDATION_DISCLOSURE
