"""Scientific benchmark tests for M12B calibration (domain-neutral)."""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np
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
    UncertaintySpec,
    Variable,
)
from drw.schema.result import ModelResult, OutputValue, RunRecord, RunStatus, ValidationReport

pytestmark = pytest.mark.scientific

AXIS = [float(index) for index in range(10)]


def provenance() -> Provenance:
    return Provenance(
        source_kind="synthetic", imported_at="2026-01-01T00:00:00+00:00", dataset_version="1.0.0"
    )


class _Adapter:
    """A domain-neutral model adapter whose outputs come from ``_outputs``."""

    def __init__(self, schema: ModelSchema) -> None:
        self._schema = schema

    def describe(self) -> ModelSchema:
        return self._schema

    def validate(self, inputs):
        return ValidationReport()

    def run(self, inputs, context):
        return ModelResult(status=RunStatus.SUCCEEDED, outputs=self._outputs(inputs))

    def _outputs(self, inputs):
        raise NotImplementedError


def scalar_schema(nominal=1.0, lower=0.0, upper=10.0) -> ModelSchema:
    return ModelSchema(
        model_id="scalar",
        parameters=(ParameterSpec(name="a", type="float", nominal=nominal, lower=lower, upper=upper),),
        outputs=(OutputSpec(name="y", kind="scalar", unit="u"),),
    )


def linear_schema() -> ModelSchema:
    return ModelSchema(
        model_id="linear",
        parameters=(
            ParameterSpec(name="a", type="float", nominal=1.0, lower=0.0, upper=10.0),
            ParameterSpec(name="b", type="float", nominal=0.0, lower=-10.0, upper=10.0),
        ),
        outputs=(OutputSpec(name="y", kind="timeseries", unit="u"),),
    )


def well_schema() -> ModelSchema:
    return ModelSchema(
        model_id="well",
        parameters=(ParameterSpec(name="a", type="float", nominal=2.5, lower=-3.0, upper=3.0),),
        outputs=(OutputSpec(name="y", kind="scalar", unit="u"),),
    )


def product_schema() -> ModelSchema:
    return ModelSchema(
        model_id="product",
        parameters=(
            ParameterSpec(name="a", type="float", nominal=2.0, lower=0.1, upper=10.0),
            ParameterSpec(name="b", type="float", nominal=3.0, lower=0.1, upper=10.0),
        ),
        outputs=(OutputSpec(name="y", kind="scalar", unit="u"),),
    )


class ScalarAdapter(_Adapter):
    def _outputs(self, inputs):
        return {"y": OutputValue(name="y", kind="scalar", unit="u", values=float(inputs["a"]))}


class LinearAdapter(_Adapter):
    def _outputs(self, inputs):
        a, b = float(inputs["a"]), float(inputs["b"])
        return {
            "y": OutputValue(
                name="y", kind="timeseries", unit="u",
                values=[a * x + b for x in AXIS], axis=tuple(AXIS),
            )
        }


class FailingLinearAdapter(LinearAdapter):
    """Fails whenever ``a`` is below ``threshold`` (a partial-failure model)."""

    def __init__(self, schema, threshold):
        super().__init__(schema)
        self.threshold = threshold

    def _outputs(self, inputs):
        if float(inputs["a"]) < self.threshold:
            raise RuntimeError("model is undefined for a below the threshold")
        return super()._outputs(inputs)


class WellAdapter(_Adapter):
    def _outputs(self, inputs):
        a = float(inputs["a"])
        return {"y": OutputValue(name="y", kind="scalar", unit="u", values=(a * a - 1.0) ** 2)}


class ProductAdapter(_Adapter):
    def _outputs(self, inputs):
        return {"y": OutputValue(name="y", kind="scalar", unit="u", values=float(inputs["a"]) * float(inputs["b"]))}


def scalar_dataset(value: float) -> object:
    return build_dataset(
        "scalar obs",
        ObservationSet(
            variables=(Variable(name="y", kind="float", role="measurement", unit="u"),),
            columns={"y": [value]},
        ),
        provenance(),
    )


def series_dataset(observed, sigma=None) -> object:
    variables = [
        Variable(name="x", kind="float", role="coordinate"),
        Variable(name="y", kind="float", role="measurement", unit="u", depends_on=("x",)),
    ]
    columns = {"x": list(AXIS), "y": list(observed)}
    if sigma is not None:
        variables[1] = Variable(
            name="y", kind="float", role="measurement", unit="u", depends_on=("x",),
            uncertainty=UncertaintySpec(type="std", column="sigma"),
        )
        variables.append(Variable(name="sigma", kind="float", role="uncertainty"))
        columns["sigma"] = list(sigma)
    return build_dataset(
        "series obs",
        ObservationSet(coordinates=("x",), variables=tuple(variables), columns=columns),
        provenance(),
    )


def mapping_for(dataset, schema: ModelSchema, *, coordinates=()) -> ObservationMapping:
    return ObservationMapping(
        dataset=dataset.ref(),
        model_ref=ModelRef(model_id=schema.model_id),
        pairs=(MappingPair(observation="y", output="y", coordinates=coordinates),),
    )


def config_for(
    dataset,
    schema,
    *,
    free,
    objective=None,
    optimizer=None,
    budget=None,
    evaluation=None,
    seed=0,
    identifiability="off",
    coordinates=(),
) -> CalibrationConfig:
    return CalibrationConfig(
        experiment_id="exp-000000000000",
        model_ref=ModelRef(model_id=schema.model_id),
        free=tuple(free),
        objective=objective or ObjectiveConfig(),
        optimizer=optimizer or OptimizerConfig(),
        budget=budget or BudgetSpec(),
        seed=seed,
        execution=ExecutionTemplate(),
        dataset=dataset.ref(),
        mapping=mapping_for(dataset, schema, coordinates=coordinates),
        evaluation=evaluation or EvaluationConfig(),
        identifiability=identifiability,
    )


def run_calibration(config, schema, dataset, adapter, baseline, **kwargs):
    return calibrate(
        config, schema=schema, dataset=dataset, baseline=baseline,
        runner=Runner(adapter=adapter), **kwargs,
    )


def free_a(initial=None, lower=0.0, upper=10.0):
    return [ParameterSelection(name="a", lower=lower, upper=upper, initial=initial)]


def free_ab(initial_a=None, initial_b=None):
    return [
        ParameterSelection(name="a", lower=0.0, upper=10.0, initial=initial_a),
        ParameterSelection(name="b", lower=-10.0, upper=10.0, initial=initial_b),
    ]


# 1. scalar -> scalar -----------------------------------------------------------------


def test_benchmark_scalar_recovery():
    schema = scalar_schema()
    dataset = scalar_dataset(2.0)
    config = config_for(dataset, schema, free=free_a(initial=1.0))
    result = run_calibration(config, schema, dataset, ScalarAdapter(schema), {"a": 1.0})
    assert result.best is not None
    assert result.best.parameters["a"] == pytest.approx(2.0, abs=1e-3)
    assert result.best.objective == pytest.approx(0.0, abs=1e-6)


# 2. known analytic optimum -----------------------------------------------------------


def test_benchmark_known_analytic_optimum():
    schema = linear_schema()
    dataset = series_dataset([2.0 * x for x in AXIS])
    config = config_for(dataset, schema, free=free_ab(1.0, 1.0), coordinates=("x",))
    result = run_calibration(config, schema, dataset, LinearAdapter(schema), {"a": 1.0, "b": 1.0})
    assert result.best is not None
    assert result.best.parameters["a"] == pytest.approx(2.0, abs=1e-4)
    assert result.best.parameters["b"] == pytest.approx(0.0, abs=1e-4)


# 3. bounded optimum outside range ----------------------------------------------------


def test_benchmark_bounded_optimum_at_bound():
    schema = scalar_schema()
    dataset = scalar_dataset(5.0)
    config = config_for(dataset, schema, free=free_a(initial=1.0, lower=0.0, upper=2.0))
    result = run_calibration(config, schema, dataset, ScalarAdapter(schema), {"a": 1.0})
    assert result.best is not None
    assert result.best.parameters["a"] == pytest.approx(2.0, abs=1e-6)


# 4. parameter scaling ----------------------------------------------------------------


def test_benchmark_parameter_scaling():
    schema = ModelSchema(
        model_id="scalar",
        parameters=(ParameterSpec(name="a", type="float", nominal=1.0, lower=0.0, upper=1e6),),
        outputs=(OutputSpec(name="y", kind="scalar", unit="u"),),
    )
    dataset = scalar_dataset(1000.0)
    config = config_for(dataset, schema, free=free_a(initial=1.0, lower=0.0, upper=1e6))
    result = run_calibration(config, schema, dataset, ScalarAdapter(schema), {"a": 1.0})
    assert result.best is not None
    assert result.best.parameters["a"] == pytest.approx(1000.0, rel=1e-2)


# 5. deterministic repeated calibration -----------------------------------------------


def test_benchmark_deterministic_repeat():
    schema = linear_schema()
    dataset = series_dataset([2.0 * x - 1.0 for x in AXIS])
    config = config_for(dataset, schema, free=free_ab(0.5, 0.5), coordinates=("x",))
    first = run_calibration(config, schema, dataset, LinearAdapter(schema), {"a": 1.0, "b": 0.0})
    second = run_calibration(config, schema, dataset, LinearAdapter(schema), {"a": 1.0, "b": 0.0})
    assert first.result_hash == second.result_hash
    assert [c.parameters for c in first.history] == [c.parameters for c in second.history]
    assert [c.objective for c in first.history] == [c.objective for c in second.history]


# 6. multi-parameter ------------------------------------------------------------------


def test_benchmark_multi_parameter():
    schema = linear_schema()
    dataset = series_dataset([2.0 * x - 1.0 for x in AXIS])
    config = config_for(dataset, schema, free=free_ab(1.5, 0.0), coordinates=("x",))
    result = run_calibration(config, schema, dataset, LinearAdapter(schema), {"a": 1.0, "b": 0.0})
    assert result.best is not None
    assert result.best.parameters["a"] == pytest.approx(2.0, abs=1e-3)
    assert result.best.parameters["b"] == pytest.approx(-1.0, abs=1e-2)


# 7. noisy observations ---------------------------------------------------------------


def test_benchmark_noisy_observations_match_least_squares():
    schema = linear_schema()
    axis = np.array(AXIS)
    observed = 2.0 * axis - 1.0 + 0.1 * np.array([(-1) ** i for i in range(len(axis))])
    dataset = series_dataset(list(observed))
    config = config_for(dataset, schema, free=free_ab(1.0, 0.0), coordinates=("x",))
    result = run_calibration(config, schema, dataset, LinearAdapter(schema), {"a": 1.0, "b": 0.0})
    expected_a, expected_b = np.polyfit(axis, observed, 1)
    assert result.best is not None
    assert result.best.parameters["a"] == pytest.approx(float(expected_a), abs=1e-3)
    assert result.best.parameters["b"] == pytest.approx(float(expected_b), abs=1e-3)
    assert result.best.objective is not None and result.best.objective > 0


# 8. weighted observations ------------------------------------------------------------


def test_benchmark_weighted_observations_use_sigma():
    schema = linear_schema()
    observed = [2.0 * x for x in AXIS]
    observed[9] = 2.0 * 9 + 5.0  # a large outlier, strongly down-weighted by a large sigma
    sigma = [0.1] * 9 + [5.0]
    dataset = series_dataset(observed, sigma=sigma)
    evaluation = EvaluationConfig(
        metrics=("rmse", "weighted_rmse"), residual_modes=("raw", "normalized")
    )
    weighted = config_for(
        dataset, schema, free=free_ab(1.0, 0.0),
        objective=ObjectiveConfig(metric="weighted_rmse"), evaluation=evaluation, coordinates=("x",),
    )
    unweighted = config_for(
        dataset, schema, free=free_ab(1.0, 0.0),
        objective=ObjectiveConfig(metric="rmse"), evaluation=evaluation, coordinates=("x",),
    )
    weighted_result = run_calibration(weighted, schema, dataset, LinearAdapter(schema), {"a": 1.0, "b": 0.0})
    plain_result = run_calibration(unweighted, schema, dataset, LinearAdapter(schema), {"a": 1.0, "b": 0.0})
    assert weighted_result.best is not None and plain_result.best is not None
    assert weighted_result.best.parameters["a"] == pytest.approx(2.0, abs=0.05)
    assert weighted_result.best.parameters["a"] < plain_result.best.parameters["a"]


# 9. model failures in part of parameter space ----------------------------------------


def test_benchmark_partial_model_failures_are_recorded():
    schema = linear_schema()
    dataset = series_dataset([2.0 * x for x in AXIS])
    # The model is undefined for a < 1.0; start there so failures are guaranteed.
    adapter = FailingLinearAdapter(schema, threshold=1.0)
    config = config_for(
        dataset, schema,
        free=[ParameterSelection(name="a", lower=0.0, upper=10.0, initial=0.5),
              ParameterSelection(name="b", lower=-10.0, upper=10.0, initial=0.0)],
        coordinates=("x",),
    )
    result = run_calibration(config, schema, dataset, adapter, {"a": 0.5, "b": 0.0})
    assert result.evaluations_invalid >= 1
    assert any(candidate.failure is not None for candidate in result.history)
    assert result.best is not None and result.best.parameters["a"] == pytest.approx(2.0, abs=1e-2)


# 10. timeout -------------------------------------------------------------------------


class _TimeoutRunner:
    def run(self, spec, *, cancel_event=None):
        run = RunRecord(
            run_id="r0", experiment_id="exp-000000000000", status=RunStatus.FAILED,
            model_ref=spec.model_ref, inputs=dict(spec.baseline), timed_out=True,
            error="timed out",
        )
        return SimpleNamespace(runs=[run], spec_hash="s" * 64, model_hash="m" * 64, environment={})


def test_benchmark_timeout_candidate_rejected():
    schema = linear_schema()
    dataset = series_dataset([2.0 * x for x in AXIS])
    config = config_for(dataset, schema, free=free_ab(1.0, 0.0), coordinates=("x",))
    result = calibrate(config, schema=schema, dataset=dataset, baseline={"a": 1.0, "b": 0.0}, runner=_TimeoutRunner())
    assert result.best is None
    assert result.status == "failed"
    assert all(candidate.failure == "run_timed_out" for candidate in result.history)


# 11. invalid parameter state ---------------------------------------------------------


def test_benchmark_invalid_parameter_state_rejected():
    from drw.calibration.loop import _Driver
    from drw.execution.environment import environment_fingerprint

    schema = linear_schema()
    dataset = series_dataset([2.0 * x for x in AXIS])
    config = config_for(dataset, schema, free=free_ab(1.0, 0.0), coordinates=("x",))
    driver = _Driver(
        config=config, schema=schema, dataset=dataset, baseline={"a": 1.0, "b": 0.0},
        runner=Runner(adapter=LinearAdapter(schema)), spec_hash="", environment=environment_fingerprint(),
        cancel_event=None, journal=None,
    )
    candidate = driver._evaluate([99.0, 0.0])  # a is far outside [0, 10]
    assert candidate.failure == "invalid_parameter_state"
    assert candidate.objective is None


# 12. non-identifiable params ---------------------------------------------------------


def test_benchmark_non_identifiable_warns_without_refusing():
    schema = product_schema()
    dataset = scalar_dataset(6.0)
    config = config_for(
        dataset, schema,
        free=[ParameterSelection(name="a", lower=0.1, upper=10.0, initial=2.0),
              ParameterSelection(name="b", lower=0.1, upper=10.0, initial=3.0)],
        identifiability="warn",
    )
    result = run_calibration(config, schema, dataset, ProductAdapter(schema), {"a": 2.0, "b": 3.0})
    assert result.identifiability is not None
    assert result.identifiability["verdict"] in ("rank-deficient", "ill-conditioned", "inconclusive")
    assert result.best is not None  # warn mode does not refuse


def test_benchmark_require_mode_refuses_unidentifiable():
    schema = product_schema()
    dataset = scalar_dataset(6.0)
    config = config_for(
        dataset, schema,
        free=[ParameterSelection(name="a", lower=0.1, upper=10.0, initial=2.0),
              ParameterSelection(name="b", lower=0.1, upper=10.0, initial=3.0)],
        identifiability="require",
    )
    result = run_calibration(config, schema, dataset, ProductAdapter(schema), {"a": 2.0, "b": 3.0})
    assert result.status == "invalid"
    assert result.stop_reason == "identifiability_required"
    assert result.best is None
    assert result.history == []


# 13. multiple local minima -----------------------------------------------------------


def test_benchmark_multiple_local_minima_powell_and_de():
    schema = well_schema()
    dataset = scalar_dataset(0.0)
    free = [ParameterSelection(name="a", lower=-3.0, upper=3.0, initial=2.5)]
    powell = config_for(dataset, schema, free=free, optimizer=OptimizerConfig(name="powell"))
    de = config_for(
        dataset, schema, free=free,
        optimizer=OptimizerConfig(name="differential_evolution", population_size=8),
        budget=BudgetSpec(max_evaluations=400),
    )
    powell_result = run_calibration(powell, schema, dataset, WellAdapter(schema), {"a": 2.5})
    de_result = run_calibration(de, schema, dataset, WellAdapter(schema), {"a": 2.5})
    assert powell_result.best is not None
    assert abs(abs(powell_result.best.parameters["a"]) - 1.0) < 0.1
    assert de_result.best is not None
    assert abs(abs(de_result.best.parameters["a"]) - 1.0) < 0.1
    assert de_result.best.objective == pytest.approx(0.0, abs=1e-6)


# 14. convergence failure -------------------------------------------------------------


def test_benchmark_convergence_failure_recorded():
    schema = well_schema()
    dataset = scalar_dataset(0.0)
    free = [ParameterSelection(name="a", lower=-3.0, upper=3.0, initial=2.5)]
    config = config_for(
        dataset, schema, free=free, optimizer=OptimizerConfig(name="powell", max_iterations=1)
    )
    result = run_calibration(config, schema, dataset, WellAdapter(schema), {"a": 2.5})
    assert result.status == "not_converged"
    assert result.converged is False
    assert result.stop_reason == "max_iterations"


# 15. budget exhaustion ---------------------------------------------------------------


def test_benchmark_budget_exhaustion_is_hard_cap():
    schema = linear_schema()
    dataset = series_dataset([2.0 * x - 1.0 for x in AXIS])
    config = config_for(
        dataset, schema, free=free_ab(9.0, 9.0), budget=BudgetSpec(max_evaluations=3), coordinates=("x",),
    )
    result = run_calibration(config, schema, dataset, LinearAdapter(schema), {"a": 1.0, "b": 0.0})
    assert result.evaluations_completed <= 3
    assert len(result.history) <= 3
    assert result.status == "budget_exhausted"
    assert result.stop_reason == "max_evaluations"
    assert result.converged is False


# 16. reproducibility -----------------------------------------------------------------


def test_benchmark_reproducibility_records_scipy_version():
    schema = linear_schema()
    dataset = series_dataset([2.0 * x - 1.0 for x in AXIS])
    config = config_for(dataset, schema, free=free_ab(0.0, 0.0), coordinates=("x",))
    result = run_calibration(config, schema, dataset, LinearAdapter(schema), {"a": 1.0, "b": 0.0})
    assert result.provenance.scipy_version
    assert result.calibration_hash == config.content_hash()
    assert len(result.result_hash) == 64
    assert result.note  # mandatory disclosure
    assert "not a statement of parameter uncertainty" in result.note
