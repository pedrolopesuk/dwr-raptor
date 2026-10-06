"""Unit tests for the global (Sobol) sensitivity design and estimators."""

from __future__ import annotations

import warnings
from types import SimpleNamespace

import numpy as np
import pytest
from scipy.stats import qmc

from drw.global_sensitivity import (
    MAX_EVALUATIONS,
    GlobalSensitivityError,
    _bootstrap,
    _estimate,
    _variance,
    default_factors,
    saltelli_design,
    sobol_indices,
    sobol_indices_for_experiment,
)
from drw.schema.experiment import ExperimentSpec
from drw.schema.model import ModelRef, ModelSchema, OutputSpec, ParameterSpec
from drw.schema.result import RunRecord, RunStatus

pytestmark = pytest.mark.unit


class CallableRunner:
    """Runner stand-in that evaluates a callable on the factor values."""

    def __init__(self, fn, names, *, output="y", fail_at=frozenset(),
                 timeout_at=frozenset(), missing_at=frozenset()):
        self._fn = fn
        self._names = names
        self._output = output
        self._fail = set(fail_at)
        self._timeout = set(timeout_at)
        self._missing = set(missing_at)
        self.calls = 0

    def run(self, spec, **kwargs):
        index = self.calls
        self.calls += 1
        model_ref = ModelRef(model_id=spec.model_ref.model_id)
        if index in self._fail:
            record = RunRecord(
                run_id=f"r{index}", experiment_id="e", status=RunStatus.FAILED,
                model_ref=model_ref, metrics={}, result=None,
            )
        elif index in self._timeout:
            record = RunRecord(
                run_id=f"r{index}", experiment_id="e", status=RunStatus.FAILED,
                model_ref=model_ref, metrics={}, result=None, timed_out=True,
            )
        elif index in self._missing:
            record = RunRecord(
                run_id=f"r{index}", experiment_id="e", status=RunStatus.SUCCEEDED,
                model_ref=model_ref, metrics={}, result=None,
            )
        else:
            x = np.array([float(spec.baseline[name]) for name in self._names])
            record = RunRecord(
                run_id=f"r{index}", experiment_id="e", status=RunStatus.SUCCEEDED,
                model_ref=model_ref, metrics={self._output: float(self._fn(x))}, result=None,
            )
        return SimpleNamespace(runs=[record])


def _schema(names, bounds, *, output="y", kind="scalar"):
    params = tuple(
        ParameterSpec(name=n, type="float", nominal=0.5, lower=lo, upper=hi)
        for n, (lo, hi) in zip(names, bounds, strict=True)
    )
    return ModelSchema(
        model_id="m", parameters=params, outputs=(OutputSpec(name=output, kind=kind, unit="u"),)
    )


def _run(fn, names, bounds, *, n=256, seed=1, factors=None, output="y",
         fail_at=frozenset(), timeout_at=frozenset(), missing_at=frozenset(), bootstrap=50):
    schema = _schema(names, bounds, output=output)
    runner = CallableRunner(
        fn, names, output=output, fail_at=fail_at, timeout_at=timeout_at, missing_at=missing_at
    )
    report = sobol_indices(
        schema,
        baseline={name: (lo + hi) / 2 for name, (lo, hi) in zip(names, bounds, strict=True)},
        output=output,
        factors=factors or names,
        sample_count=n,
        seed=seed,
        runner=runner,
        bootstrap_resamples=bootstrap,
    )
    return report, runner


def _by_name(report):
    return {row.name: row for row in report.results}


def test_additive_model_has_first_order_equal_total_order():
    fn = lambda x: x[0] + 2.0 * x[1]  # noqa: E731
    report, _ = _run(fn, ["x0", "x1"], [(0.0, 1.0), (0.0, 1.0)], n=512, seed=1)
    rows = _by_name(report)
    assert rows["x0"].s1 == pytest.approx(0.2, abs=0.05)
    assert rows["x1"].s1 == pytest.approx(0.8, abs=0.05)
    # Additive model: total-order equals first-order (no interactions).
    assert rows["x0"].st == pytest.approx(rows["x0"].s1, abs=0.03)
    assert rows["x1"].st == pytest.approx(rows["x1"].s1, abs=0.03)


def test_interaction_model_has_total_order_greater_than_first_order():
    fn = lambda x: x[0] * x[1]  # noqa: E731
    report, _ = _run(fn, ["x0", "x1"], [(0.0, 1.0), (0.0, 1.0)], n=1024, seed=2)
    rows = _by_name(report)
    assert rows["x0"].s1 == pytest.approx(3.0 / 7.0, abs=0.05)
    assert rows["x1"].s1 == pytest.approx(3.0 / 7.0, abs=0.05)
    assert rows["x0"].st == pytest.approx(4.0 / 7.0, abs=0.05)
    assert rows["x0"].st > rows["x0"].s1  # interaction share > 0


def test_constant_output_is_inconclusive():
    report, _ = _run(lambda x: 5.0, ["x0"], [(0.0, 1.0)], n=8)
    assert report.inconclusive is True
    assert report.variance is None
    assert report.reasons
    assert report.results[0].s1 is None and report.results[0].st is None


def test_factor_with_no_effect_has_near_zero_indices():
    fn = lambda x: x[0] + 0.0 * x[1]  # noqa: E731
    report, _ = _run(fn, ["x0", "x1"], [(0.0, 1.0), (0.0, 1.0)], n=512, seed=3)
    rows = _by_name(report)
    assert abs(rows["x1"].s1) < 0.05 and abs(rows["x1"].st) < 0.05
    assert rows["x0"].s1 == pytest.approx(1.0, abs=0.05)


def test_same_seed_is_deterministic():
    fn = lambda x: x[0] * x[1]  # noqa: E731
    first, _ = _run(fn, ["x0", "x1"], [(0.0, 1.0), (0.0, 1.0)], n=128, seed=7)
    second, _ = _run(fn, ["x0", "x1"], [(0.0, 1.0), (0.0, 1.0)], n=128, seed=7)
    assert first.model_dump() == second.model_dump()


def test_different_seeds_agree_statistically():
    fn = lambda x: x[0] * x[1]  # noqa: E731
    for seed in (11, 12, 13):
        report, _ = _run(fn, ["x0", "x1"], [(0.0, 1.0), (0.0, 1.0)], n=1024, seed=seed)
        rows = _by_name(report)
        assert rows["x0"].s1 == pytest.approx(3.0 / 7.0, abs=0.06)
        assert rows["x0"].st == pytest.approx(4.0 / 7.0, abs=0.06)


def test_evaluation_count_is_n_times_d_plus_two():
    fn = lambda x: float(x[0])  # noqa: E731
    names = ["x0", "x1", "x2"]
    bounds = [(0.0, 1.0)] * 3
    report, runner = _run(fn, names, bounds, n=16, seed=1)
    assert report.evaluations_requested == 16 * (3 + 2)
    assert runner.calls == 16 * (3 + 2)
    assert report.evaluations_completed == 16 * (3 + 2)


def test_a_failed_evaluation_makes_the_study_inconclusive():
    fn = lambda x: float(x[0])  # noqa: E731
    report, _ = _run(fn, ["x0"], [(0.0, 1.0)], n=8, fail_at={3})
    assert report.inconclusive is True
    assert report.evaluations_completed == 8 * 3 - 1
    assert any("run_failed" in reason for reason in report.reasons)
    assert all(row.s1 is None for row in report.results)


def test_estimates_are_not_clipped_to_theoretical_bounds():
    # Crafted arrays produce a first-order estimate below 0; it must be preserved.
    variance, results, reasons = _estimate(
        np.array([0.0, 0.0, 0.0, 0.0]),
        np.array([1.0, -1.0, 1.0, -1.0]),
        [np.array([-2.0, 2.0, -2.0, 2.0])],
        ["x0"],
        bootstrap_resamples=10,
        seed=1,
    )
    assert variance is not None and variance > 0
    assert reasons == []
    assert results[0].s1 == pytest.approx(-3.5)  # negative estimate preserved, not clamped


def test_design_shapes_and_coupling():
    a, b, ab = saltelli_design(3, 16, seed=5)
    assert a.shape == b.shape == (16, 3)
    assert len(ab) == 3
    for index, hybrid in enumerate(ab):
        assert np.array_equal(hybrid[:, index], b[:, index])
        others = [c for c in range(3) if c != index]
        assert np.array_equal(hybrid[:, others], a[:, others])


@pytest.mark.parametrize(
    "kwargs, message",
    [
        ({"factors": ["nope"]}, "unknown factor"),
        ({"factors": ["x0", "x0"]}, "duplicate"),
        ({"sample_count": 1}, "at least 2"),
        ({"output": "nope"}, "unknown output"),
    ],
)
def test_invalid_requests_raise(kwargs, message):
    schema = _schema(["x0", "x1"], [(0.0, 1.0), (0.0, 1.0)])
    params = dict(sample_count=8, output="y", factors=["x0"], seed=1)
    params.update(kwargs)
    with pytest.raises(GlobalSensitivityError, match=message):
        sobol_indices(schema, baseline={"x0": 0.5, "x1": 0.5}, runner=CallableRunner(lambda x: float(x[0]), ["x0", "x1"]), **params)


def test_unbounded_and_non_scalar_are_rejected():
    unbounded = ModelSchema(
        model_id="m",
        parameters=(ParameterSpec(name="x0", type="float", nominal=1.0, role="state"),),
        outputs=(OutputSpec(name="y", kind="scalar"),),
    )
    with pytest.raises(GlobalSensitivityError, match="no declared bounds"):
        sobol_indices(
            unbounded, baseline={"x0": 1.0}, output="y", factors=["x0"],
            sample_count=8, runner=CallableRunner(lambda x: float(x[0]), ["x0"]),
        )

    series = _schema(["x0"], [(0.0, 1.0)], output="y", kind="timeseries")
    with pytest.raises(GlobalSensitivityError, match="only scalar outputs"):
        sobol_indices(
            series, baseline={"x0": 0.5}, output="y", factors=["x0"],
            sample_count=8, runner=CallableRunner(lambda x: float(x[0]), ["x0"]),
        )


def test_evaluation_budget_is_enforced():
    schema = _schema(["x0", "x1", "x2"], [(0.0, 1.0)] * 3)
    with pytest.raises(GlobalSensitivityError, match="evaluations"):
        sobol_indices(
            schema, baseline={"x0": 0.5, "x1": 0.5, "x2": 0.5}, output="y",
            factors=["x0", "x1", "x2"], sample_count=MAX_EVALUATIONS,
            runner=CallableRunner(lambda x: float(x[0]), ["x0", "x1", "x2"]),
        )


# --- design regression: independence, determinism, ordering (audit F3) -------


@pytest.mark.parametrize("seed", [1, 2, 3, 20240607])
def test_design_columns_are_not_collinear(seed):
    # The rejected prototype split a d-dimensional sequence into two consecutive
    # blocks, giving |corr(A[:, i], B[:, i])| ~ 0.9999. The 2d split must not.
    a, b, _ = saltelli_design(3, 256, seed=seed)
    for index in range(3):
        correlation = float(np.corrcoef(a[:, index], b[:, index])[0, 1])
        assert abs(correlation) < 0.1


def test_design_is_deterministic_for_a_fixed_seed():
    a1, b1, ab1 = saltelli_design(4, 32, seed=7)
    a2, b2, ab2 = saltelli_design(4, 32, seed=7)
    assert np.array_equal(a1, a2)
    assert np.array_equal(b1, b2)
    for left, right in zip(ab1, ab2, strict=True):
        assert np.array_equal(left, right)
    a3, _, _ = saltelli_design(4, 32, seed=8)
    assert not np.array_equal(a1, a3)


class RecordingRunner:
    """Captures the exact order of evaluated points (one run per point)."""

    def __init__(self, fn, names, output="y"):
        self._fn = fn
        self._names = names
        self._output = output
        self.points = []

    def run(self, spec, **kwargs):
        self.points.append({name: float(spec.baseline[name]) for name in self._names})
        x = np.array([float(spec.baseline[name]) for name in self._names])
        record = RunRecord(
            run_id=f"r{len(self.points)}", experiment_id="e", status=RunStatus.SUCCEEDED,
            model_ref=ModelRef(model_id=spec.model_ref.model_id),
            metrics={self._output: float(self._fn(x))}, result=None,
        )
        return SimpleNamespace(runs=[record])


def test_evaluation_order_matches_the_coupled_design_and_slicing():
    names = ["x0", "x1", "x2"]
    bounds = [(-2.0, 3.0), (0.0, 4.0), (0.0, 5.0)]
    n, seed = 16, 11

    def model(x):
        return float(x[0] + 2.0 * x[1] - x[2])

    runner = RecordingRunner(model, names)
    report = sobol_indices(
        _schema(names, bounds),
        baseline={name: (lo + hi) / 2 for name, (lo, hi) in zip(names, bounds, strict=True)},
        output="y", factors=names, sample_count=n, seed=seed, runner=runner,
        bootstrap_resamples=10,
    )

    a, b, ab = saltelli_design(3, n, seed=seed)
    lower = np.array([lo for lo, _ in bounds])
    upper = np.array([hi for _, hi in bounds])
    expected = np.vstack(
        [qmc.scale(a, lower, upper), qmc.scale(b, lower, upper)]
        + [qmc.scale(hybrid, lower, upper) for hybrid in ab]
    )
    recorded = np.array([[point[name] for name in names] for point in runner.points])
    assert recorded.shape == (n * 5, 3)
    # The evaluation order is exactly A, B, AB_0, AB_1, AB_2.
    assert np.allclose(recorded, expected)

    # Result slicing: recompute the estimates from the recorded order, independently.
    y = np.array([model(point) for point in recorded])
    y_a, y_b = y[:n], y[n : 2 * n]
    y_ab = [y[(2 + i) * n : (3 + i) * n] for i in range(3)]
    variance = _variance(y_a, y_b)
    s1 = [float(np.sum(y_b * (hybrid - y_a)) / n / variance) for hybrid in y_ab]
    st = [float(np.sum((y_a - hybrid) ** 2) / (2 * n) / variance) for hybrid in y_ab]
    assert np.allclose([row.s1 for row in report.results], s1)
    assert np.allclose([row.st for row in report.results], st)


# --- failure semantics (audit F5) -------------------------------------------


def test_non_finite_output_makes_the_study_inconclusive():
    fn = lambda x: float("inf") if x[0] > 0.5 else float(x[0])  # noqa: E731
    report, _ = _run(fn, ["x0"], [(0.0, 1.0)], n=16, seed=1, bootstrap=10)
    assert report.inconclusive is True
    assert report.variance is None
    assert report.results == []  # no partial indices from a broken design
    assert any("non_finite" in reason for reason in report.reasons)
    assert 0 < report.evaluations_completed < report.evaluations_requested


def test_timed_out_evaluation_makes_the_study_inconclusive():
    fn = lambda x: float(x[0])  # noqa: E731
    report, _ = _run(fn, ["x0"], [(0.0, 1.0)], n=8, seed=1, timeout_at={3}, bootstrap=10)
    assert report.inconclusive is True
    assert report.evaluations_completed == 8 * 3 - 1
    assert any("run_timed_out" in reason for reason in report.reasons)
    assert report.results == []


def test_missing_output_makes_the_study_inconclusive():
    fn = lambda x: float(x[0])  # noqa: E731
    report, _ = _run(fn, ["x0"], [(0.0, 1.0)], n=8, seed=1, missing_at={3}, bootstrap=10)
    assert report.inconclusive is True
    assert any("output_missing" in reason for reason in report.reasons)
    assert report.results == []


def test_failure_counts_are_reported_without_partial_indices():
    fn = lambda x: float(x[0])  # noqa: E731
    report, _ = _run(fn, ["x0"], [(0.0, 1.0)], n=8, seed=1, fail_at={1, 2}, timeout_at={3},
                     bootstrap=10)
    assert report.inconclusive is True
    assert report.evaluations_completed == 8 * 3 - 3
    assert "2 evaluation(s) run_failed" in report.reasons
    assert "1 evaluation(s) run_timed_out" in report.reasons
    assert report.results == []


# --- bootstrap edge cases (audit F5) ----------------------------------------


def test_zero_bootstrap_yields_absent_intervals_without_crashing():
    fn = lambda x: x[0] + 2.0 * x[1]  # noqa: E731
    report, _ = _run(fn, ["x0", "x1"], [(0.0, 1.0)] * 2, n=32, seed=1, bootstrap=0)
    assert report.inconclusive is False
    assert report.results
    for row in report.results:
        assert row.s1_ci is None and row.st_ci is None


def test_bootstrap_returns_no_interval_when_replicates_are_degenerate():
    constant = np.full(8, 3.0)
    s1, st = _bootstrap(constant, constant, [constant], resamples=20, seed=1)
    assert s1 == [None]
    assert st == [None]


# --- default selection and small dimensions (audit F5) ----------------------


def test_default_factors_are_the_bounded_numeric_parameters():
    mixed = ModelSchema(
        model_id="m",
        parameters=(
            ParameterSpec(name="a", type="float", nominal=1.0, lower=0.0, upper=2.0),
            ParameterSpec(name="b", type="float", nominal=1.0, role="state"),
            ParameterSpec(name="c", type="float", nominal=1.0, lower=1.0, upper=3.0),
        ),
        outputs=(OutputSpec(name="y", kind="scalar"),),
    )
    assert default_factors(mixed) == ["a", "c"]


def test_default_factors_match_the_advertised_factorable_parameters():
    # The web panel previews the default selection from
    # `capabilities.factorable_parameters`; that advertised set must equal the
    # core's actual default selection for every registered model (one source of
    # truth for eligible factors).
    from drw.capabilities import model_capabilities
    from drw.models.registry import model_schemas

    for model_id, schema in model_schemas().items():
        advertised = [
            parameter["name"]
            for parameter in model_capabilities(schema)["factorable_parameters"]
        ]
        assert default_factors(schema) == advertised, model_id


class _FakeStore:
    """Store stand-in exposing only `load` (the study is read-only)."""

    def __init__(self, spec):
        self._spec = spec

    def load(self, experiment_id):
        return {"spec": self._spec.model_dump()}


def test_for_experiment_uses_default_factors_and_primary_output():
    names = ["alpha", "beta", "delta", "gamma", "prey0", "predator0"]
    spec = ExperimentSpec(
        name="defaults",
        hypothesis="global sensitivity defaults",
        model_ref=ModelRef(model_id="predator-prey", version="1.0.0"),
        baseline={
            "alpha": 1.1, "beta": 0.4, "delta": 0.1, "gamma": 0.4,
            "prey0": 10.0, "predator0": 5.0,
        },
        factors=(),
        outputs=("prey",),
        analyses=(),
    )
    runner = CallableRunner(lambda x: float(np.sum(x)), names, output="peak_prey")
    report = sobol_indices_for_experiment(
        "exp-deadbeef0000", _FakeStore(spec), runner=runner, sample_count=8, seed=1,
        bootstrap_resamples=5,
    )
    assert report.output == "peak_prey"  # primary scalar output
    assert report.factors == names  # every bounded numeric parameter
    assert report.dimensions == len(names)


def test_one_factor_study_is_estimated():
    fn = lambda x: x[0] ** 2  # noqa: E731
    report, _ = _run(fn, ["x0"], [(0.0, 1.0)], n=64, seed=5, bootstrap=10)
    assert report.inconclusive is False
    rows = _by_name(report)
    assert rows["x0"].s1 == pytest.approx(1.0, abs=0.05)
    assert rows["x0"].st == pytest.approx(1.0, abs=0.05)


# --- request validation (audit F7) ------------------------------------------


def test_negative_seed_is_rejected():
    schema = _schema(["x0"], [(0.0, 1.0)])
    with pytest.raises(GlobalSensitivityError, match="seed"):
        sobol_indices(
            schema, baseline={"x0": 0.5}, output="y", factors=["x0"], sample_count=8, seed=-1,
            runner=CallableRunner(lambda x: float(x[0]), ["x0"]),
        )


def test_non_power_of_two_sample_count_is_flagged_in_the_note():
    fn = lambda x: float(x[0])  # noqa: E731
    balanced, _ = _run(fn, ["x0"], [(0.0, 1.0)], n=64, seed=1, bootstrap=5)
    assert "power of two" not in (balanced.note or "")
    unbalanced, _ = _run(fn, ["x0"], [(0.0, 1.0)], n=100, seed=1, bootstrap=5)
    assert "power of two" in (unbalanced.note or "")


def test_non_power_of_two_diagnostic_is_independent_of_scipy_warnings():
    # The application-level diagnostic must not depend on scipy's own warning
    # being emitted or visible (e.g. when warnings are filtered).
    fn = lambda x: float(x[0])  # noqa: E731
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        report, _ = _run(fn, ["x0"], [(0.0, 1.0)], n=100, seed=1, bootstrap=5)
    assert "power of two" in (report.note or "")
