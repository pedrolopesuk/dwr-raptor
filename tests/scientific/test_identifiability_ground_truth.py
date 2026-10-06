"""Scientific ground-truth tests for local parameter identifiability.

These are analytic/synthetic benchmarks, not empirical validation. They assert
that the finite-difference SVD detects a *known* local degeneracy (and does not
invent one), using the reference models and hand-constructed matrices with known
singular-value structure.
"""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest

from drw.execution.context import RunContext
from drw.identifiability import analyze_sensitivity_matrix, identifiability
from drw.models.registry import build_model
from drw.schema.model import ModelSchema, OutputSpec, ParameterSpec
from drw.schema.result import RunStatus

pytestmark = pytest.mark.scientific


class ModelRunner:
    """In-process runner: executes the real registered model for a single point."""

    def __init__(self, model_id: str) -> None:
        self.model = build_model(model_id)
        self.context = RunContext(run_id="r", experiment_id="e", rtol=1e-11, atol=1e-13)

    def run(self, spec, **_kwargs):
        result = self.model.run(dict(spec.baseline), self.context)
        record = SimpleNamespace(
            succeeded=result.ok,
            timed_out=False,
            status=RunStatus.SUCCEEDED if result.ok else RunStatus.FAILED,
            metrics={},
            result=result,
        )
        return SimpleNamespace(runs=[record])


def _smallest_problematic_direction(report):
    problematic = [direction for direction in report.directions if direction.problematic]
    assert problematic, "expected at least one poorly distinguishable direction"
    return min(problematic, key=lambda direction: direction.singular_value)


def _pair(report, first, second):
    for pair in report.factor_correlations:
        if {pair.first, pair.second} == {first, second}:
            return pair
    return None


# ---------------------------------------------------------------------------
# Benchmark A - oscillator: displacement depends only on sqrt(k/m) when undamped.
# ---------------------------------------------------------------------------


def test_oscillator_mass_and_stiffness_are_locally_indistinguishable():
    # With c = 0 and v0 != 0 the whole displacement trajectory is a function of
    # w = sqrt(k/m) alone, so m and k are locally non-identifiable from x(t).
    schema = build_model("oscillator").describe()
    report = identifiability(
        schema,
        baseline={"m": 1.0, "k": 4.0, "c": 0.0, "x0": 1.0, "v0": 1.0},
        factors=["m", "k"],
        outputs=["x"],
        runner=ModelRunner("oscillator"),
    )

    assert report.verdict == "rank-deficient"
    assert report.numerical_rank == 1

    direction = _smallest_problematic_direction(report)
    assert direction.weights["m"] > 0.1
    assert direction.weights["k"] > 0.1

    pair = _pair(report, "m", "k")
    assert pair is not None
    assert abs(pair.correlation) > 0.9

    # The result must be described as local, never as an absolute statement.
    assert "not global identifiability" in (report.note or "")


def test_oscillator_damping_breaks_the_degeneracy():
    # With c fixed and non-zero, x(t) depends on m and k through two independent
    # combinations (a = c/2m and b = k/m - a^2), so m and k become distinguishable.
    schema = build_model("oscillator").describe()
    report = identifiability(
        schema,
        baseline={"m": 1.0, "k": 4.0, "c": 0.2, "x0": 1.0, "v0": 1.0},
        factors=["m", "k"],
        outputs=["x"],
        runner=ModelRunner("oscillator"),
    )
    assert report.verdict != "rank-deficient"
    assert report.numerical_rank == 2


# ---------------------------------------------------------------------------
# Benchmark B - predator-prey: the early prey peak depends on beta * predator0.
# ---------------------------------------------------------------------------


def test_predator_prey_beta_and_predator0_are_locally_collinear():
    schema = build_model("predator-prey").describe()
    report = identifiability(
        schema,
        baseline={
            "alpha": 1.1, "beta": 0.4, "delta": 0.1, "gamma": 0.4,
            "prey0": 10.0, "predator0": 5.0,
        },
        factors=["beta", "predator0"],
        outputs=["prey"],
        runner=ModelRunner("predator-prey"),
    )

    assert report.verdict == "rank-deficient"
    assert report.numerical_rank == 1

    direction = _smallest_problematic_direction(report)
    assert direction.weights["beta"] > 0.1
    assert direction.weights["predator0"] > 0.1

    pair = _pair(report, "beta", "predator0")
    assert pair is not None
    assert abs(pair.correlation) > 0.9


# ---------------------------------------------------------------------------
# Benchmark C - a full-rank control must not be misclassified.
# ---------------------------------------------------------------------------


def _control_schema() -> ModelSchema:
    return ModelSchema(
        model_id="control",
        parameters=(
            ParameterSpec(name="x0", type="float", nominal=0.5, lower=0.0, upper=1.0),
            ParameterSpec(name="x1", type="float", nominal=0.5, lower=0.0, upper=1.0),
        ),
        outputs=(OutputSpec(name="y0", kind="scalar"), OutputSpec(name="y1", kind="scalar")),
    )


class _ControlRunner:
    def run(self, spec, **_kwargs):
        x0 = float(spec.baseline["x0"])
        x1 = float(spec.baseline["x1"])
        outputs = {
            "y0": SimpleNamespace(kind="scalar", unit="u", values=x0, axis=None),
            "y1": SimpleNamespace(kind="scalar", unit="u", values=2.0 * x1, axis=None),
        }
        record = SimpleNamespace(
            succeeded=True, timed_out=False, status=RunStatus.SUCCEEDED,
            metrics={"y0": x0, "y1": 2.0 * x1}, result=SimpleNamespace(outputs=outputs),
        )
        return SimpleNamespace(runs=[record])


def test_full_rank_control_is_not_classified_as_degenerate():
    report = identifiability(
        _control_schema(),
        baseline={"x0": 0.5, "x1": 0.5},
        factors=["x0", "x1"],
        runner=_ControlRunner(),
    )
    assert report.verdict == "well-conditioned"
    assert report.numerical_rank == 2
    assert not [direction for direction in report.directions if direction.problematic]
    assert report.condition_number is not None and report.condition_number < 10.0


# ---------------------------------------------------------------------------
# Mathematical benchmark - known singular-value structure.
# ---------------------------------------------------------------------------


def test_scaled_orthogonal_matrix_has_known_singular_values():
    result = analyze_sensitivity_matrix([[3.0, 0.0], [0.0, 4.0]], factor_names=["a", "b"])
    assert result.singular_values == pytest.approx([4.0, 3.0])
    assert result.numerical_rank == 2
    assert result.condition_number == pytest.approx(4.0 / 3.0)
    assert result.verdict == "well-conditioned"


def test_exact_rank_one_matrix_exposes_the_null_direction():
    matrix = [[1.0, 2.0], [2.0, 4.0]]  # second column = 2 x first
    result = analyze_sensitivity_matrix(matrix, factor_names=["a", "b"])
    assert result.numerical_rank == 1
    assert result.condition_number is None
    assert result.verdict == "rank-deficient"
    null_direction = min(result.directions, key=lambda direction: direction.singular_value)
    assert null_direction.weights["a"] > 0.1
    assert null_direction.weights["b"] > 0.1


def test_reported_singular_values_match_a_direct_svd():
    matrix = [[2.0, 1.0, 0.0], [0.0, 1.0, 3.0]]
    result = analyze_sensitivity_matrix(matrix, factor_names=["a", "b", "c"])
    expected = np.linalg.svd(matrix, compute_uv=False)
    assert result.singular_values[: expected.size] == pytest.approx(expected.tolist())
    assert all(value == pytest.approx(0.0) for value in result.singular_values[expected.size :])
