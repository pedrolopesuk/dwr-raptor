"""Unit tests: a run never succeeds with non-finite output."""

from __future__ import annotations

import types

import numpy as np
import pytest

from drw.execution.context import RunContext
from drw.numerics.ode import OdeModel
from drw.schema.model import ModelSchema, OutputSpec, ParameterSpec
from drw.schema.result import RunStatus

pytestmark = pytest.mark.unit


def _schema() -> ModelSchema:
    return ModelSchema(
        model_id="probe",
        parameters=(ParameterSpec(name="y0", type="float", nominal=1.0, role="state"),),
        outputs=(OutputSpec(name="y"),),
    )


def _context() -> RunContext:
    return RunContext(run_id="r", experiment_id="e")


def test_guard_rejects_a_successful_solve_with_non_finite_values(monkeypatch):
    """Directly exercise the finite guard with a fake 'successful' solve."""

    def fake_solve_ivp(fun, t_span, y0, *, method, t_eval, rtol, atol):
        n = len(t_eval)
        return types.SimpleNamespace(
            success=True,
            message="fake success",
            nfev=1,
            t=np.asarray(t_eval, dtype=float),
            y=np.full((1, n), np.nan),
        )

    monkeypatch.setattr("drw.numerics.ode.solve_ivp", fake_solve_ivp)
    model = OdeModel(
        _schema(),
        lambda t, y, p: [-y[0]],
        t_span=(0.0, 1.0),
        n_points=5,
        output_names=("y",),
    )
    result = model.run({"y0": 1.0}, _context())
    assert result.status == RunStatus.FAILED
    assert any(d.code == "non_finite_output" for d in result.diagnostics)
    assert result.outputs == {}


def test_nan_rhs_never_yields_a_successful_run():
    def nan_rhs(t, y, p):
        return [float("nan") if t > 0.5 else -y[0]]

    model = OdeModel(_schema(), nan_rhs, t_span=(0.0, 1.0), n_points=11, output_names=("y",))
    result = model.run({"y0": 1.0}, _context())
    assert result.status == RunStatus.FAILED
    codes = {d.code for d in result.diagnostics}
    assert codes & {"non_finite_output", "solver_failed", "solver_exception"}
    # No non-finite output can ever be reported as a successful result.
    assert result.outputs == {}


def test_non_finite_input_is_rejected_before_integration():
    model = OdeModel(
        _schema(), lambda t, y, p: [-y[0]], t_span=(0.0, 1.0), n_points=5, output_names=("y",)
    )
    result = model.run({"y0": float("inf")}, _context())
    assert result.status == RunStatus.FAILED
    assert any(d.code == "non_finite_input" for d in result.diagnostics)
