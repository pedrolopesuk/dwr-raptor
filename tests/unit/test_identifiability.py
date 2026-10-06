"""Unit tests for local parameter identifiability (finite-difference SVD)."""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest

from drw.identifiability import (
    ABSOLUTE_STEP,
    CONDITION_THRESHOLD,
    DEFAULT_STEP_SCALE,
    IdentifiabilityError,
    analyze_sensitivity_matrix,
    default_factors,
    default_targets,
    estimate_evaluations,
    identifiability,
    identifiability_for_experiment,
)
from drw.schema.experiment import ExperimentSpec
from drw.schema.model import ModelRef, ModelSchema, OutputSpec, ParameterSpec
from drw.schema.result import RunStatus

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Test doubles.
# ---------------------------------------------------------------------------


def _output(value, unit="u"):
    if isinstance(value, (list, tuple, np.ndarray)):
        values = np.asarray(value, dtype=float)
        return SimpleNamespace(
            kind="timeseries", unit=unit, values=values, axis=np.arange(values.size, dtype=float)
        )
    return SimpleNamespace(kind="scalar", unit=unit, values=float(value), axis=None)


class FakeRunner:
    """Runner stand-in: evaluates a callable on the baseline inputs, one run per point."""

    def __init__(self, fn, *, fail_at=(), timeout_at=(), missing_at=(), axis=None):
        self.fn = fn
        self.calls = 0
        self.points: list[dict] = []
        self._fail = set(fail_at)
        self._timeout = set(timeout_at)
        self._missing = set(missing_at)
        self._axis = axis

    def _record(self, index, *, status=RunStatus.SUCCEEDED, timed_out=False, metrics=None, outputs=None):
        return SimpleNamespace(
            succeeded=status == RunStatus.SUCCEEDED,
            timed_out=timed_out,
            status=status,
            metrics=metrics or {},
            result=SimpleNamespace(outputs=outputs or {}),
        )

    def run(self, spec, **_kwargs):
        index = self.calls
        self.calls += 1
        self.points.append(dict(spec.baseline))
        if index in self._fail:
            return SimpleNamespace(runs=[self._record(index, status=RunStatus.FAILED)])
        if index in self._timeout:
            return SimpleNamespace(
                runs=[self._record(index, status=RunStatus.FAILED, timed_out=True)]
            )
        if index in self._missing:
            return SimpleNamespace(runs=[self._record(index)])
        values = self.fn(dict(spec.baseline))
        outputs = {}
        metrics = {}
        for name, value in values.items():
            output = _output(value)
            if self._axis is not None and output.kind == "timeseries":
                output.axis = self._axis
            outputs[name] = output
            if output.kind == "scalar":
                metrics[name] = float(value)
        return SimpleNamespace(runs=[self._record(index, metrics=metrics, outputs=outputs)])


def _param(name, lower, upper, *, nominal=None, type_="float"):
    return ParameterSpec(
        name=name, type=type_, nominal=nominal if nominal is not None else (lower + upper) / 2,
        lower=lower if type_ == "float" else None, upper=upper if type_ == "float" else None,
    )


def _schema(params, outputs):
    return ModelSchema(model_id="m", parameters=tuple(params), outputs=tuple(outputs))


# ---------------------------------------------------------------------------
# Pure matrix analysis.
# ---------------------------------------------------------------------------


def test_identity_matrix_is_well_conditioned():
    result = analyze_sensitivity_matrix([[1.0, 0.0], [0.0, 1.0]], factor_names=["a", "b"])
    assert result.verdict == "well-conditioned"
    assert result.numerical_rank == 2
    assert result.condition_number == pytest.approx(1.0)
    assert result.singular_values == pytest.approx([1.0, 1.0])


def test_singular_values_match_numpy():
    matrix = [[1.0, 2.0], [3.0, 4.0]]
    result = analyze_sensitivity_matrix(matrix, factor_names=["a", "b"])
    assert result.singular_values == pytest.approx(np.linalg.svd(matrix, compute_uv=False).tolist())


def test_rank_deficient_matrix_reports_rank_deficiency():
    result = analyze_sensitivity_matrix([[1.0, 1.0], [1.0, 1.0]], factor_names=["a", "b"])
    assert result.verdict == "rank-deficient"
    assert result.numerical_rank == 1
    assert result.condition_number is None
    assert result.singular_values[-1] == pytest.approx(0.0)


def test_near_collinear_matrix_is_ill_conditioned():
    # Four informative targets; the second column is a tiny orthogonal perturbation
    # of the first, so the system is full-rank but very poorly conditioned.
    base = np.array([1.0, 2.0, 3.0, 4.0])
    orthogonal = np.array([4.0, -3.0, 2.0, -1.0])  # orthogonal to base
    orthogonal = orthogonal / np.linalg.norm(orthogonal)
    matrix = np.column_stack([base, base + 1e-6 * orthogonal])
    result = analyze_sensitivity_matrix(matrix, factor_names=["a", "b"])
    assert result.verdict == "ill-conditioned"
    assert result.numerical_rank == 2
    assert result.condition_number is not None
    assert result.condition_number > CONDITION_THRESHOLD
    assert result.factor_correlations
    assert result.factor_correlations[0].correlation == pytest.approx(1.0, abs=1e-3)


def test_underdetermined_matrix_exposes_null_directions():
    result = analyze_sensitivity_matrix([[1.0, 0.0, 0.0]], factor_names=["a", "b", "c"])
    assert result.verdict == "rank-deficient"
    assert result.numerical_rank == 1
    problematic = [d for d in result.directions if d.problematic]
    assert len(problematic) == 2
    # The two null directions span the b/c plane.
    covered = {name for direction in problematic for name in direction.weights if direction.weights[name] > 0}
    assert covered == {"b", "c"}


def test_correlations_are_not_reported_for_too_few_targets():
    # Two points make |correlation| trivially 1; it must not be reported.
    result = analyze_sensitivity_matrix([[1.0, 0.0], [0.0, 2.0]], factor_names=["a", "b"])
    assert result.factor_correlations == []


def test_non_finite_matrix_is_inconclusive():
    result = analyze_sensitivity_matrix([[1.0, float("nan")], [0.0, 1.0]], factor_names=["a", "b"])
    assert result.inconclusive is True
    assert result.verdict == "inconclusive"
    assert result.reasons


def test_empty_matrix_is_inconclusive():
    result = analyze_sensitivity_matrix([], factor_names=["a", "b"])
    assert result.inconclusive is True
    assert result.verdict == "inconclusive"


def test_matrix_with_wrong_column_count_raises():
    with pytest.raises(IdentifiabilityError, match="one column per factor"):
        analyze_sensitivity_matrix([[1.0, 2.0]], factor_names=["a"])


# ---------------------------------------------------------------------------
# Step calculation, bounds, validation.
# ---------------------------------------------------------------------------


def _linear_schema():
    return _schema(
        [_param("a", 0.0, 10.0), _param("b", 0.0, 10.0)],
        [OutputSpec(name="y0", kind="scalar"), OutputSpec(name="y1", kind="scalar")],
    )


def test_step_calculation_and_perturbation():
    runner = FakeRunner(lambda x: {"y0": x["a"], "y1": 2.0 * x["b"]})
    report = identifiability(
        _linear_schema(), baseline={"a": 4.0, "b": 1.0}, factors=["a", "b"], runner=runner
    )
    detail = {d.name: d for d in report.factors_detail}
    assert detail["a"].step == pytest.approx(DEFAULT_STEP_SCALE * 4.0)
    assert detail["a"].plus_value == pytest.approx(4.0 + DEFAULT_STEP_SCALE * 4.0)
    assert detail["a"].minus_value == pytest.approx(4.0 - DEFAULT_STEP_SCALE * 4.0)
    assert detail["b"].step == pytest.approx(DEFAULT_STEP_SCALE * 1.0)


def test_zero_baseline_falls_back_to_the_absolute_step():
    schema = _schema([_param("a", -1.0, 1.0), _param("b", -1.0, 1.0)], [OutputSpec(name="y0", kind="scalar")])
    runner = FakeRunner(lambda x: {"y0": x["a"] + x["b"]})
    report = identifiability(schema, baseline={"a": 0.0, "b": 0.5}, factors=["a", "b"], runner=runner)
    detail = {d.name: d for d in report.factors_detail}
    assert detail["a"].step == pytest.approx(ABSOLUTE_STEP)


def test_parameter_at_bound_fails_closed_before_execution():
    schema = _schema([_param("a", 0.1, 10.0), _param("b", 0.0, 10.0)], [OutputSpec(name="y0", kind="scalar")])
    runner = FakeRunner(lambda x: {"y0": x["a"] + x["b"]})
    report = identifiability(schema, baseline={"a": 0.1, "b": 1.0}, factors=["a", "b"], runner=runner)
    assert report.inconclusive is True
    assert report.verdict == "inconclusive"
    assert report.evaluations_completed == 0
    assert runner.calls == 0  # rejected before any execution
    assert any("cannot be perturbed" in reason for reason in report.reasons)
    assert any(not d.valid for d in report.factors_detail)


def test_unknown_duplicate_and_empty_factors_raise():
    schema = _linear_schema()
    runner = FakeRunner(lambda x: {"y0": x["a"], "y1": x["b"]})
    with pytest.raises(IdentifiabilityError, match="unknown factor"):
        identifiability(schema, baseline={"a": 1.0, "b": 1.0}, factors=["nope"], runner=runner)
    with pytest.raises(IdentifiabilityError, match="duplicate"):
        identifiability(schema, baseline={"a": 1.0, "b": 1.0}, factors=["a", "a"], runner=runner)
    with pytest.raises(IdentifiabilityError, match="at least one factor"):
        identifiability(schema, baseline={"a": 1.0, "b": 1.0}, factors=[], runner=runner)


def test_non_continuous_and_unbounded_parameters_are_rejected():
    integer = _schema([_param("k", 0.0, 5.0, type_="int")], [OutputSpec(name="y0", kind="scalar")])
    with pytest.raises(IdentifiabilityError, match="continuous"):
        identifiability(integer, baseline={"k": 1.0}, factors=["k"], runner=FakeRunner(lambda x: {"y0": 1.0}))

    unbounded = _schema(
        [ParameterSpec(name="u", type="float", nominal=1.0, role="state")],
        [OutputSpec(name="y0", kind="scalar")],
    )
    with pytest.raises(IdentifiabilityError, match="bounds"):
        identifiability(unbounded, baseline={"u": 1.0}, factors=["u"], runner=FakeRunner(lambda x: {"y0": 1.0}))


def test_invalid_step_scale_raises():
    schema = _linear_schema()
    with pytest.raises(IdentifiabilityError, match="step_scale"):
        identifiability(
            schema, baseline={"a": 1.0, "b": 1.0}, factors=["a"], step_scale=0.0,
            runner=FakeRunner(lambda x: {"y0": x["a"], "y1": x["b"]}),
        )


def test_default_factors_are_bounded_float_parameters():
    schema = ModelSchema(
        model_id="m",
        parameters=(
            _param("a", 0.0, 1.0),
            _param("b", 0.0, 1.0, type_="int"),
            ParameterSpec(name="c", type="float", nominal=1.0, role="state"),
            ParameterSpec(name="d", type="float", nominal=1.0, lower=0.0, upper=2.0),
        ),
        outputs=(OutputSpec(name="y0", kind="scalar"),),
    )
    assert default_factors(schema) == ["a", "d"]


def test_invalid_and_unsupported_outputs_raise():
    schema = _schema(
        [_param("a", 0.0, 1.0)],
        [OutputSpec(name="y0", kind="scalar"), OutputSpec(name="v", kind="vector")],
    )
    runner = FakeRunner(lambda x: {"y0": x["a"]})
    with pytest.raises(IdentifiabilityError, match="unknown output"):
        identifiability(schema, baseline={"a": 0.5}, factors=["a"], outputs=["nope"], runner=runner)
    with pytest.raises(IdentifiabilityError, match="only scalar and time-series"):
        identifiability(schema, baseline={"a": 0.5}, factors=["a"], outputs=["v"], runner=runner)


# ---------------------------------------------------------------------------
# Targets and time-series features.
# ---------------------------------------------------------------------------


def test_scalar_output_yields_a_single_value_target():
    schema = _schema([_param("a", 0.0, 1.0)], [OutputSpec(name="y0", kind="scalar")])
    targets = default_targets(schema)
    assert [t.feature for t in targets] == ["value"]
    assert targets[0].label == "y0"


def test_timeseries_output_expands_to_five_disclosed_features():
    schema = _schema(
        [_param("a", 0.0, 1.0)],
        [OutputSpec(name="s", kind="timeseries", axis_unit="s")],
    )
    targets = default_targets(schema)
    assert [t.feature for t in targets] == ["max", "min", "mean", "final", "argmax_t"]


def test_timeseries_feature_values_are_computed_correctly():
    schema = _schema([_param("a", 0.0, 1.0)], [OutputSpec(name="s", kind="timeseries")])
    runner = FakeRunner(lambda x: {"s": x["a"] * np.array([0.0, 1.0, 2.0, 3.0])})
    report = identifiability(schema, baseline={"a": 0.5}, factors=["a"], runner=runner)
    values = {t.feature: t.baseline_value for t in report.targets}
    assert values["max"] == pytest.approx(1.5)
    assert values["min"] == pytest.approx(0.0)
    assert values["mean"] == pytest.approx(0.75)
    assert values["final"] == pytest.approx(1.5)
    assert values["argmax_t"] == pytest.approx(3.0)


def test_argmax_feature_without_an_axis_fails_closed():
    schema = _schema([_param("a", 0.0, 1.0)], [OutputSpec(name="s", kind="timeseries")])

    class NoAxisRunner(FakeRunner):
        def run(self, spec, **kwargs):
            record = super().run(spec, **kwargs)
            for output in record.runs[0].result.outputs.values():
                output.axis = None
            return record

    report = identifiability(
        schema, baseline={"a": 0.5}, factors=["a"], outputs=["s"], runner=NoAxisRunner(lambda x: {"s": [0.0, 1.0]})
    )
    assert report.inconclusive is True
    assert any("argmax_t" in reason for reason in report.reasons)


# ---------------------------------------------------------------------------
# Failure semantics.
# ---------------------------------------------------------------------------


def _two_factor_schema():
    return _schema(
        [_param("a", 0.0, 1.0), _param("b", 0.0, 1.0)],
        [OutputSpec(name="y0", kind="scalar"), OutputSpec(name="y1", kind="scalar")],
    )


@pytest.mark.parametrize("kind, kwargs", [
    ("failed", {"fail_at": {3}}),
    ("timed_out", {"timeout_at": {3}}),
    ("missing", {"missing_at": {3}}),
])
def test_broken_evaluations_are_inconclusive(kind, kwargs):
    runner = FakeRunner(lambda x: {"y0": x["a"], "y1": x["b"]}, **kwargs)
    report = identifiability(
        _two_factor_schema(), baseline={"a": 0.5, "b": 0.5}, factors=["a", "b"], runner=runner
    )
    assert report.inconclusive is True
    assert report.verdict == "inconclusive"
    assert report.singular_values == []
    assert report.numerical_rank is None
    assert any(kind in reason for reason in report.reasons)


def test_non_finite_output_is_inconclusive():
    def fn(x):
        return {"y0": float("inf") if x["a"] > 0.5 else x["a"], "y1": x["b"]}

    report = identifiability(
        _two_factor_schema(), baseline={"a": 0.5, "b": 0.5}, factors=["a", "b"], runner=FakeRunner(fn)
    )
    assert report.inconclusive is True
    assert report.numerical_rank is None


# ---------------------------------------------------------------------------
# Determinism, cost, and robustness.
# ---------------------------------------------------------------------------


def test_evaluation_count_is_two_per_factor_plus_a_baseline():
    runner = FakeRunner(lambda x: {"y0": x["a"], "y1": x["b"]})
    report = identifiability(
        _two_factor_schema(), baseline={"a": 0.5, "b": 0.5}, factors=["a", "b"], runner=runner
    )
    assert estimate_evaluations(2) == 5
    assert report.evaluations_requested == 5
    assert report.evaluations_completed == 5
    assert runner.calls == 5


def test_evaluation_cap_is_enforced():
    runner = FakeRunner(lambda x: {"y0": x["a"], "y1": x["b"]})
    with pytest.raises(IdentifiabilityError, match="evaluations"):
        identifiability(
            _two_factor_schema(), baseline={"a": 0.5, "b": 0.5}, factors=["a", "b"],
            runner=runner, max_evaluations=4,
        )
    assert runner.calls == 0


def test_same_configuration_is_deterministic():
    first = identifiability(
        _two_factor_schema(), baseline={"a": 0.5, "b": 0.5}, factors=["a", "b"],
        runner=FakeRunner(lambda x: {"y0": x["a"], "y1": x["b"]}),
    )
    second = identifiability(
        _two_factor_schema(), baseline={"a": 0.5, "b": 0.5}, factors=["a", "b"],
        runner=FakeRunner(lambda x: {"y0": x["a"], "y1": x["b"]}),
    )
    assert first.model_dump() == second.model_dump()


@pytest.mark.parametrize("step_scale", [1e-2, 1e-3, 1e-4])
def test_degenerate_direction_is_detected_across_step_scales(step_scale):
    # Both targets are functions of the product a*b, so the two parameters are
    # locally indistinguishable regardless of the finite-difference step.
    schema = _schema([_param("a", 0.1, 2.0), _param("b", 0.1, 2.0)], [
        OutputSpec(name="y0", kind="scalar"), OutputSpec(name="y1", kind="scalar")
    ])
    runner = FakeRunner(lambda x: {"y0": x["a"] * x["b"], "y1": (x["a"] * x["b"]) ** 2})
    report = identifiability(
        schema, baseline={"a": 1.0, "b": 1.0}, factors=["a", "b"],
        step_scale=step_scale, runner=runner,
    )
    assert report.verdict == "rank-deficient"
    assert report.numerical_rank == 1


class _FakeStore:
    def __init__(self, spec):
        self._spec = spec

    def load(self, experiment_id):
        return {"spec": self._spec.model_dump()}


def test_for_experiment_uses_defaults_and_records_the_id():
    from drw.models.registry import build_model

    model_id = "predator-prey"
    baseline = {
        "alpha": 1.1, "beta": 0.4, "delta": 0.1, "gamma": 0.4, "prey0": 10.0, "predator0": 5.0,
    }
    spec = ExperimentSpec(
        name="identifiability defaults",
        hypothesis="which parameters are distinguishable?",
        model_ref=ModelRef(model_id=model_id, version="1.0.0"),
        baseline=baseline,
        factors=(),
        outputs=(),
        analyses=(),
    )
    schema = build_model(model_id).describe()

    def fn(inputs):
        total = sum(float(inputs[name]) for name in default_factors(schema))
        series = np.array([total, total * 1.1, total * 0.9, total * 1.2])
        return {"prey": series, "predator": series * 0.5, "peak_prey": float(total)}

    report = identifiability_for_experiment(
        "exp-000000000000", _FakeStore(spec), runner=FakeRunner(fn)
    )
    assert report.experiment_id == "exp-000000000000"
    assert report.factors == default_factors(schema)  # default bounded continuous parameters
    assert report.verdict in ("well-conditioned", "ill-conditioned", "rank-deficient")
