"""Unit tests for the M12B calibration contract (Phase A)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from drw.schema.calibration import (
    BudgetSpec,
    CalibrationCandidateSummary,
    CalibrationConfig,
    CalibrationConfigError,
    CalibrationObjective,
    CalibrationProvenance,
    CalibrationRef,
    CalibrationResult,
    ExecutionTemplate,
    FixedParameter,
    ObjectiveConfig,
    OptimizerConfig,
    ParameterSelection,
    calibration_identity_payload,
    compute_calibration_hash,
    compute_result_hash,
    resolve_calibration,
    short_calibration_id,
    validate_calibration_config,
)
from drw.schema.evaluation import EvaluationConfig
from drw.schema.model import ModelRef, ModelSchema, OutputSpec, ParameterSpec
from drw.schema.observation import DatasetRef, MappingPair, ObservationMapping, short_dataset_id

pytestmark = pytest.mark.unit

HASH = "a" * 64
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


def make_ref() -> DatasetRef:
    return DatasetRef(dataset_id=short_dataset_id(HASH), content_hash=HASH, name="d")


def make_mapping(pairs=(("y", "y"),)) -> ObservationMapping:
    return ObservationMapping(
        dataset=make_ref(),
        model_ref=ModelRef(model_id="model"),
        pairs=tuple(MappingPair(observation=o, output=m) for o, m in pairs),
    )


def make_config(**over) -> CalibrationConfig:
    payload = {
        "experiment_id": "exp-000000000000",
        "model_ref": ModelRef(model_id="model"),
        "free": (ParameterSelection(name="a", lower=0.0, upper=10.0),),
        "objective": ObjectiveConfig(),
        "budget": BudgetSpec(),
        "execution": ExecutionTemplate(),
        "dataset": make_ref(),
        "mapping": make_mapping(),
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
    payload = {
        "calibration_hash": compute_calibration_hash(config),
        "result_hash": "",
        "experiment_id": "exp-000000000000",
        "model_ref": ModelRef(model_id="model"),
        "config": config,
        "status": "converged",
        "stop_reason": "optimizer_converged",
        "converged": True,
        "objective": CalibrationObjective(metric="rmse", observation="y", output="y", value=0.0),
        "evaluations_requested": 1,
        "evaluations_completed": 1,
        "evaluations_invalid": 0,
        "iterations": 1,
        "wall_seconds": 0.1,
        "provenance": make_provenance(),
    }
    payload.update(over)
    result = CalibrationResult(**payload)
    return result.model_copy(update={"result_hash": compute_result_hash(result)})


# ---------------------------------------------------------------------------
# Construction and identity.
# ---------------------------------------------------------------------------


def test_config_constructs_and_hashes_deterministically():
    a = make_config()
    b = make_config()
    assert a.content_hash() == b.content_hash()
    assert len(a.content_hash()) == 64
    assert compute_calibration_hash(a) == a.content_hash()


def test_hash_is_independent_of_free_declaration_order():
    forwards = make_config(
        free=(
            ParameterSelection(name="a", lower=0.0, upper=10.0),
            ParameterSelection(name="b", lower=-5.0, upper=5.0),
        )
    )
    backwards = make_config(
        free=(
            ParameterSelection(name="b", lower=-5.0, upper=5.0),
            ParameterSelection(name="a", lower=0.0, upper=10.0),
        )
    )
    assert forwards.content_hash() == backwards.content_hash()


def test_hash_ignores_notes():
    assert make_config(notes="one").content_hash() == make_config(notes="two").content_hash()


@pytest.mark.parametrize(
    "change",
    [
        {"free": (ParameterSelection(name="a", lower=0.1, upper=10.0),)},
        {"objective": ObjectiveConfig(metric="mae")},
        {"optimizer": OptimizerConfig(name="random_search")},
        {"budget": BudgetSpec(max_evaluations=7)},
        {"seed": 42},
        {"identifiability": "require"},
        {"evaluation": EvaluationConfig(metrics=("mae", "rmse"))},
    ],
)
def test_hash_changes_with_scientific_configuration(change):
    assert make_config().content_hash() != make_config(**change).content_hash()


def test_identity_payload_excludes_notes():
    payload = calibration_identity_payload(make_config(notes="x"))
    assert "notes" not in payload


# ---------------------------------------------------------------------------
# Structural validation.
# ---------------------------------------------------------------------------


def test_free_duplicates_rejected():
    with pytest.raises(ValidationError):
        make_config(
            free=(
                ParameterSelection(name="a", lower=0.0, upper=1.0),
                ParameterSelection(name="a", lower=0.0, upper=1.0),
            )
        )


def test_free_and_fixed_overlap_rejected():
    with pytest.raises(ValidationError, match="both free and fixed"):
        make_config(fixed=(FixedParameter(name="a", value=1.0),))


def test_objective_metric_must_be_in_evaluation_metrics():
    with pytest.raises(ValidationError, match=r"not requested in evaluation\.metrics"):
        make_config(
            objective=ObjectiveConfig(metric="weighted_rmse"),
            evaluation=EvaluationConfig(
                metrics=("rmse",), residual_modes=("raw", "normalized")
            ),
        )


def test_multi_pair_requires_pair_selector():
    mapping = make_mapping(pairs=(("y", "y"), ("p", "p")))
    with pytest.raises(ValidationError, match="multiple pairs"):
        make_config(
            mapping=mapping,
            objective=ObjectiveConfig(),
        )


def test_pair_selector_must_exist_in_mapping():
    with pytest.raises(ValidationError, match="not declared in the mapping"):
        make_config(objective=ObjectiveConfig(observation="nope", output="nope"))


def test_mapping_model_mismatch_rejected():
    mapping = ObservationMapping(
        dataset=make_ref(), model_ref=ModelRef(model_id="other"),
        pairs=(MappingPair(observation="y", output="y"),),
    )
    with pytest.raises(ValidationError, match=r"mapping\.model_ref"):
        make_config(mapping=mapping)


def test_execution_template_requires_single_run():
    with pytest.raises(ValidationError):
        ExecutionTemplate(max_runs=2)


def test_optimizer_de_options_only_for_de():
    with pytest.raises(ValidationError, match="differential_evolution"):
        OptimizerConfig(name="powell", population_size=10)


def test_parameter_selection_requires_lower_lt_upper():
    with pytest.raises(ValidationError):
        ParameterSelection(name="a", lower=1.0, upper=1.0)


def test_parameter_selection_initial_bounds():
    with pytest.raises(ValidationError):
        ParameterSelection(name="a", lower=0.0, upper=1.0, initial=2.0)


def test_pair_selector_requires_both_fields():
    with pytest.raises(ValidationError, match="both 'observation' and 'output'"):
        ObjectiveConfig(observation="y")


# ---------------------------------------------------------------------------
# Model-aware resolution.
# ---------------------------------------------------------------------------


def test_resolve_uses_explicit_initial():
    config = make_config(free=(ParameterSelection(name="a", lower=0.0, upper=10.0, initial=4.0),))
    resolved = resolve_calibration(config, SCHEMA, BASELINE)
    assert resolved.initial == [4.0]
    assert resolved.names == ["a"]


def test_resolve_uses_nominal_when_no_initial():
    resolved = resolve_calibration(make_config(), SCHEMA, BASELINE)
    assert resolved.initial == [2.0]


def test_resolve_requires_initial_when_no_nominal():
    # parameter `c` has a nominal, so strip it via a schema without one.
    schema = ModelSchema(
        model_id="model",
        parameters=(ParameterSpec(name="c", type="float"),),
        outputs=SCHEMA.outputs,
    )
    config = make_config(free=(ParameterSelection(name="c", lower=0.0, upper=10.0),))
    with pytest.raises(CalibrationConfigError, match="explicit initial is required"):
        resolve_calibration(config, schema, {})


def test_resolve_rejects_widening_model_bounds():
    config = make_config(free=(ParameterSelection(name="a", lower=-1.0, upper=10.0),))
    diagnostics = validate_calibration_config(config, SCHEMA, BASELINE)
    assert any(d.code == "bounds_widen_model_lower" for d in diagnostics)
    with pytest.raises(CalibrationConfigError):
        resolve_calibration(config, SCHEMA, BASELINE)


def test_resolve_rejects_non_float():
    schema = ModelSchema(
        model_id="model",
        parameters=(ParameterSpec(name="n", type="int", nominal=1, lower=0, upper=5),),
        outputs=SCHEMA.outputs,
    )
    config = make_config(free=(ParameterSelection(name="n", lower=0.0, upper=5.0),))
    with pytest.raises(CalibrationConfigError):
        resolve_calibration(config, schema, {"n": 1})


def test_resolve_rejects_unknown_free():
    config = make_config(free=(ParameterSelection(name="zzz", lower=0.0, upper=1.0),))
    with pytest.raises(CalibrationConfigError):
        resolve_calibration(config, SCHEMA, BASELINE)


def test_resolve_derives_fixed_from_baseline_then_nominal():
    resolved = resolve_calibration(make_config(), SCHEMA, BASELINE)
    assert resolved.fixed == {"b": 1.0, "c": 3.0}


def test_resolve_fixed_override():
    config = make_config(fixed=(FixedParameter(name="b", value=9.0),))
    resolved = resolve_calibration(config, SCHEMA, BASELINE)
    assert resolved.fixed["b"] == 9.0


def test_resolve_canonical_order():
    config = make_config(
        free=(
            ParameterSelection(name="b", lower=-5.0, upper=5.0),
            ParameterSelection(name="a", lower=0.0, upper=10.0),
        )
    )
    assert resolve_calibration(config, SCHEMA, BASELINE).names == ["a", "b"]


def test_validate_returns_empty_when_executable():
    assert validate_calibration_config(make_config(), SCHEMA, BASELINE) == ()


# ---------------------------------------------------------------------------
# Result identity.
# ---------------------------------------------------------------------------


def test_result_hash_is_deterministic_and_excludes_itself():
    a = make_result()
    b = make_result()
    assert a.result_hash == b.result_hash
    assert compute_result_hash(a) == a.result_hash
    assert len(a.result_hash) == 64


def test_result_hash_changes_with_outcome():
    base = make_result()
    changed = make_result(
        best=CalibrationCandidateSummary(index=0, parameters={"a": 2.0}, objective=0.5)
    )
    assert base.result_hash != changed.result_hash


def test_calibration_ref_identity():
    result = make_result()
    ref = CalibrationRef(
        calibration_id=short_calibration_id(result.result_hash),
        result_hash=result.result_hash,
        experiment_id=result.experiment_id,
        model_id="model",
        status=result.status,
    )
    assert ref.calibration_id == short_calibration_id(result.result_hash)
    with pytest.raises(ValidationError):
        CalibrationRef(
            calibration_id="cal-" + "0" * 12,
            result_hash=result.result_hash,
            experiment_id=result.experiment_id,
            model_id="model",
            status="converged",
        )
