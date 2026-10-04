"""Unit tests for ExperimentSpec, run estimation and validation."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from drw.schema.experiment import (
    ExperimentSpec,
    FactorSpec,
    estimate_run_count,
    is_power_of_two,
    validate_experiment,
)
from drw.schema.model import ModelSchema, OutputSpec, ParameterSpec

pytestmark = pytest.mark.unit


def _schema() -> ModelSchema:
    return ModelSchema(
        model_id="demo",
        parameters=(
            ParameterSpec(name="k", type="float", nominal=1.0, lower=0.0, upper=10.0),
            ParameterSpec(name="x0", type="float", nominal=1.0, lower=-5.0, upper=5.0, role="state"),
        ),
        outputs=(OutputSpec(name="x"),),
    )


def _spec(**overrides) -> ExperimentSpec:
    data = {
        "hypothesis": "h",
        "model_ref": {"model_id": "demo"},
        "baseline": {"k": 1.0, "x0": 1.0},
        "factors": ({"parameter": "k", "values": [1.0, 2.0]},),
        "outputs": ("x",),
        "analyses": ({"method": "delta"},),
    }
    data.update(overrides)
    return ExperimentSpec.model_validate(data)


def test_factor_modes():
    assert FactorSpec(parameter="k", values=(1.0, 2.0)).mode == "list"
    ranged = FactorSpec(parameter="k", lower=0.0, upper=2.0, steps=3)
    assert ranged.mode == "range"
    assert ranged.grid_values() == (0.0, 1.0, 2.0)


def test_factor_rejects_values_with_bounds():
    with pytest.raises(ValidationError):
        FactorSpec(parameter="k", values=(1.0,), lower=0.0, upper=2.0)


def test_factor_bounds_only_is_valid_but_has_no_cardinality():
    factor = FactorSpec(parameter="k", lower=0.0, upper=2.0)
    assert factor.mode == "bounds"
    with pytest.raises(ValueError):
        factor.cardinality()


def test_factor_rejects_steps_without_bounds():
    with pytest.raises(ValidationError):
        FactorSpec(parameter="k", steps=3)


def test_estimate_grid_is_product_plus_baseline():
    estimate = estimate_run_count(_spec(factors=({"parameter": "k", "lower": 0.0, "upper": 2.0, "steps": 3},)))
    assert estimate.baseline_runs == 1
    assert estimate.variant_runs == 3
    assert estimate.total_runs == 4


def test_estimate_sobol_warns_on_non_power_of_two():
    spec = _spec(
        factors=({"parameter": "k", "lower": 0.0, "upper": 2.0},),
        sampling={"method": "sobol", "n_samples": 5},
    )
    estimate = estimate_run_count(spec)
    assert any(w.code == "sobol_non_power_of_two" for w in estimate.warnings)
    assert is_power_of_two(8) and not is_power_of_two(6)


def test_validate_flags_unknown_factor():
    diagnostics = validate_experiment(_spec(factors=({"parameter": "zzz", "values": [1.0]},)), _schema())
    assert any(d.code == "unknown_factor" for d in diagnostics)


def test_validate_flags_out_of_bounds_factor():
    diagnostics = validate_experiment(_spec(factors=({"parameter": "k", "values": [15.0]},)), _schema())
    assert any(d.code == "factor_out_of_bounds" for d in diagnostics)


def test_validate_flags_missing_initial_condition():
    diagnostics = validate_experiment(_spec(baseline={"k": 1.0}), _schema())
    assert any(d.code == "missing_initial_condition" for d in diagnostics)


def test_validate_flags_budget_exceeded():
    spec = _spec(
        factors=({"parameter": "k", "lower": 0.0, "upper": 10.0, "steps": 100},),
        execution={"max_runs": 5},
    )
    diagnostics = validate_experiment(spec, _schema())
    assert any(d.code == "run_budget_exceeded" for d in diagnostics)


def test_valid_spec_has_no_errors():
    diagnostics = validate_experiment(_spec(), _schema())
    assert not any(d.level == "error" for d in diagnostics)
