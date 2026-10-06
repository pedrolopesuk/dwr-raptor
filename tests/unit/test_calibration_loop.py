"""Unit tests for the M12B execution loop mechanics (Phase C)."""

from __future__ import annotations

import threading

import pytest

from drw.calibration import calibrate
from drw.execution.runner import Runner
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
from drw.schema.model import ModelRef, ModelSchema, OutputSpec, ParameterSpec
from drw.schema.observation import (
    MappingPair,
    ObservationMapping,
    ObservationSet,
    Provenance,
    Variable,
)
from drw.schema.result import ModelResult, OutputValue, RunStatus, ValidationReport

pytestmark = pytest.mark.unit

AXIS = [float(index) for index in range(10)]

SCHEMA = ModelSchema(
    model_id="linear",
    parameters=(
        ParameterSpec(name="a", type="float", nominal=1.0, lower=0.0, upper=10.0),
        ParameterSpec(name="b", type="float", nominal=0.0, lower=-10.0, upper=10.0),
    ),
    outputs=(OutputSpec(name="y", kind="timeseries", unit="u"),),
)


def make_dataset() -> object:
    return build_dataset(
        "obs",
        ObservationSet(
            coordinates=("x",),
            variables=(
                Variable(name="x", kind="float", role="coordinate"),
                Variable(name="y", kind="float", role="measurement", unit="u", depends_on=("x",)),
            ),
            columns={"x": list(AXIS), "y": [2.0 * x - 1.0 for x in AXIS]},
        ),
        Provenance(source_kind="synthetic", imported_at="2026-01-01T00:00:00+00:00", dataset_version="1.0.0"),
    )


def make_config(dataset, **over) -> CalibrationConfig:
    payload = {
        "experiment_id": "exp-000000000000",
        "model_ref": ModelRef(model_id="linear"),
        "free": (
            ParameterSelection(name="a", lower=0.0, upper=10.0, initial=9.0),
            ParameterSelection(name="b", lower=-10.0, upper=10.0, initial=9.0),
        ),
        "objective": ObjectiveConfig(),
        "optimizer": OptimizerConfig(),
        "budget": BudgetSpec(),
        "execution": ExecutionTemplate(),
        "dataset": dataset.ref(),
        "mapping": ObservationMapping(
            dataset=dataset.ref(),
            model_ref=ModelRef(model_id="linear"),
            pairs=(MappingPair(observation="y", output="y", coordinates=("x",)),),
        ),
        "evaluation": EvaluationConfig(),
        "identifiability": "off",
    }
    payload.update(over)
    return CalibrationConfig(**payload)


class LinearAdapter:
    def __init__(self) -> None:
        self.calls = 0

    def describe(self) -> ModelSchema:
        return SCHEMA

    def validate(self, inputs):
        return ValidationReport()

    def run(self, inputs, context):
        self.calls += 1
        a, b = float(inputs["a"]), float(inputs["b"])
        return ModelResult(
            status=RunStatus.SUCCEEDED,
            outputs={
                "y": OutputValue(
                    name="y", kind="timeseries", unit="u",
                    values=[a * x + b for x in AXIS], axis=tuple(AXIS),
                )
            },
        )


class FailingAdapter(LinearAdapter):
    def run(self, inputs, context):
        self.calls += 1
        raise RuntimeError("model always fails")


def run(config, adapter, dataset, **kwargs):
    return calibrate(
        config, schema=SCHEMA, dataset=dataset, baseline={"a": 9.0, "b": 9.0},
        runner=Runner(adapter=adapter), **kwargs,
    )


def test_hard_evaluation_cap_never_exceeded():
    dataset = make_dataset()
    config = make_config(dataset, budget=BudgetSpec(max_evaluations=4))
    adapter = LinearAdapter()
    result = run(config, adapter, dataset)
    assert adapter.calls <= 4
    assert result.evaluations_completed <= 4
    assert len(result.history) <= 4
    assert result.status == "budget_exhausted"
    assert result.stop_reason == "max_evaluations"


def test_differential_evolution_cannot_exceed_cap():
    dataset = make_dataset()
    config = make_config(
        dataset,
        optimizer=OptimizerConfig(name="differential_evolution", population_size=8),
        budget=BudgetSpec(max_evaluations=5),
    )
    adapter = LinearAdapter()
    result = run(config, adapter, dataset)
    # DE wants popsize*dim evaluations up-front; the loop's hard cap forbids them.
    assert adapter.calls <= 5
    assert result.evaluations_completed <= 5


def test_cancellation_stops_before_execution():
    dataset = make_dataset()
    config = make_config(dataset, budget=BudgetSpec(max_evaluations=50))
    adapter = LinearAdapter()
    cancel = threading.Event()
    cancel.set()
    result = run(config, adapter, dataset, cancel_event=cancel)
    assert result.status == "cancelled"
    assert result.stop_reason == "cancelled"
    assert adapter.calls == 0
    assert result.history == []


def test_all_candidates_fail_produces_no_best():
    dataset = make_dataset()
    config = make_config(dataset, budget=BudgetSpec(max_evaluations=6))
    result = run(config, FailingAdapter(), dataset)
    assert result.best is None
    assert result.status == "failed"
    assert result.evaluations_invalid == len(result.history) > 0


def test_max_failed_stops_search():
    dataset = make_dataset()
    config = make_config(dataset, budget=BudgetSpec(max_evaluations=50, max_failed=2))
    result = run(config, FailingAdapter(), dataset)
    assert result.stop_reason == "max_failed"
    assert result.status == "failed"
    assert result.evaluations_invalid >= 2
    assert len(result.history) <= 3


def test_sentinel_disclosed_and_never_a_scientific_value():
    dataset = make_dataset()
    config = make_config(dataset, budget=BudgetSpec(max_evaluations=4))
    result = run(config, FailingAdapter(), dataset)
    assert result.objective.invalid_objective_sentinel == "+inf"
    assert result.objective.value is None
    assert all(candidate.objective is None for candidate in result.history)


def test_result_hash_is_deterministic_and_ignores_wall_clock():
    dataset = make_dataset()
    config = make_config(dataset, budget=BudgetSpec(max_evaluations=8))
    first = run(config, LinearAdapter(), dataset)
    second = run(config, LinearAdapter(), dataset)
    assert first.result_hash == second.result_hash
    assert [c.objective for c in first.history] == [c.objective for c in second.history]


def test_calibration_hash_matches_config_identity():
    dataset = make_dataset()
    config = make_config(dataset)
    result = run(config, LinearAdapter(), dataset)
    assert result.calibration_hash == config.content_hash()
    assert result.provenance.scipy_version
    assert result.provenance.dataset_content_hash == dataset.content_hash
