"""Scientific benchmark: Sobol' indices against the analytic Ishigami function.

Ishigami (a=7, b=0.1), x_i in [-pi, pi], f = sin(x1) + a sin^2(x2) + b x3^4 sin(x1).
Analytic indices (independently derived; Sobol'/Saltelli references):
  V = a^2/8 + b pi^4/5 + b^2 pi^8/18 + 1/2
  S1 = (1/2 + b pi^4/5 + b^2 pi^8/50)/V,  S2 = (a^2/8)/V,  S3 = 0
  ST1 = (1/2)(1 + 2 b pi^4/5 + b^2 pi^8/9)/V,  ST2 = S2,  ST3 = (8 b^2 pi^8/225)/V
"""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest

from drw.global_sensitivity import sobol_indices
from drw.schema.model import ModelRef, ModelSchema, OutputSpec, ParameterSpec
from drw.schema.result import RunRecord, RunStatus

pytestmark = pytest.mark.scientific

A_PARAM = 7.0
B_PARAM = 0.1
PI = float(np.pi)

V = A_PARAM**2 / 8 + B_PARAM * PI**4 / 5 + B_PARAM**2 * PI**8 / 18 + 0.5
S1 = (0.5 + B_PARAM * PI**4 / 5 + B_PARAM**2 * PI**8 / 50) / V
S2 = (A_PARAM**2 / 8) / V
ST1 = 0.5 * (1 + 2 * B_PARAM * PI**4 / 5 + B_PARAM**2 * PI**8 / 9) / V
ST3 = (8 * B_PARAM**2 * PI**8 / 225) / V

NAMES = ["x0", "x1", "x2"]


def _ishigami(x: np.ndarray) -> float:
    return float(
        np.sin(x[0]) + A_PARAM * np.sin(x[1]) ** 2 + B_PARAM * x[2] ** 4 * np.sin(x[0])
    )


class _CallableRunner:
    def __init__(self, names):
        self._names = names

    def run(self, spec, **kwargs):
        x = np.array([float(spec.baseline[name]) for name in self._names])
        record = RunRecord(
            run_id="r", experiment_id="e", status=RunStatus.SUCCEEDED,
            model_ref=ModelRef(model_id=spec.model_ref.model_id),
            metrics={"y": _ishigami(x)}, result=None,
        )
        return SimpleNamespace(runs=[record])


def _schema():
    return ModelSchema(
        model_id="ishigami",
        parameters=tuple(
            ParameterSpec(name=name, type="float", nominal=0.0, lower=-PI, upper=PI)
            for name in NAMES
        ),
        outputs=(OutputSpec(name="y", kind="scalar", unit="dimensionless"),),
    )


def _estimate(n, seed):
    report = sobol_indices(
        _schema(),
        baseline={name: 0.0 for name in NAMES},
        output="y",
        factors=NAMES,
        sample_count=n,
        seed=seed,
        runner=_CallableRunner(NAMES),
        bootstrap_resamples=50,
        max_evaluations=1_000_000,
    )
    return {row.name: row for row in report.results}, report


@pytest.mark.parametrize("n,tol", [(256, 0.06), (1024, 0.025)])
def test_ishigami_matches_analytic_indices(n, tol):
    rows, report = _estimate(n, seed=20240607)
    assert report.inconclusive is False
    assert report.variance is not None and report.variance == pytest.approx(V, rel=0.25)
    errors = {
        "S1": abs(rows["x0"].s1 - S1),
        "S2": abs(rows["x1"].s1 - S2),
        "S3": abs(rows["x2"].s1 - 0.0),
        "ST1": abs(rows["x0"].st - ST1),
        "ST2": abs(rows["x1"].st - S2),
        "ST3": abs(rows["x2"].st - ST3),
    }
    assert errors["S1"] < tol, errors
    assert errors["S2"] < tol, errors
    assert errors["S3"] < tol, errors
    assert errors["ST1"] < tol, errors
    assert errors["ST2"] < tol, errors
    assert errors["ST3"] < tol, errors


def test_ishigami_reports_interaction_for_the_third_factor():
    rows, _ = _estimate(1024, seed=99)
    # x3 has zero first-order effect but a positive total-order effect (interaction).
    assert rows["x2"].s1 == pytest.approx(0.0, abs=0.03)
    assert rows["x2"].st == pytest.approx(ST3, abs=0.05)
    assert rows["x2"].st > rows["x2"].s1


def test_ishigami_is_repeatable_for_a_fixed_seed():
    first, _ = _estimate(256, seed=123)
    second, _ = _estimate(256, seed=123)
    for name in NAMES:
        assert first[name].s1 == second[name].s1
        assert first[name].st == second[name].st
