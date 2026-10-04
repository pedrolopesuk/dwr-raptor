"""Unit tests for the ODE model adapter."""

from __future__ import annotations

import numpy as np
import pytest

from drw.execution.context import RunContext
from drw.numerics.ode import OdeModel
from drw.schema.model import ModelSchema, OutputSpec, ParameterSpec
from drw.schema.result import RunStatus

pytestmark = pytest.mark.unit


def _schema() -> ModelSchema:
    return ModelSchema(
        model_id="exponential",
        parameters=(
            ParameterSpec(name="a", type="float", unit="1/s", nominal=1.0, lower=0.0, upper=5.0),
            ParameterSpec(name="y0", type="float", nominal=1.0, lower=-10.0, upper=10.0, role="state"),
        ),
        outputs=(OutputSpec(name="y", unit="dimensionless", axis_unit="s"),),
    )


def _model(rhs=None, **kwargs) -> OdeModel:
    def default_rhs(t, y, params):
        return [params["a"] * y[0]]

    return OdeModel(
        _schema(),
        rhs or default_rhs,
        t_span=(0.0, 1.0),
        n_points=11,
        output_names=("y",),
        **kwargs,
    )


def _context(**overrides) -> RunContext:
    data = {"run_id": "r", "experiment_id": "e", "rtol": 1e-10, "atol": 1e-12}
    data.update(overrides)
    return RunContext(**data)


def test_validate_accepts_known_inputs():
    report = _model().validate({"a": 1.0, "y0": 1.0})
    assert report.ok


def test_validate_flags_out_of_bounds_and_unknown():
    report = _model().validate({"a": -1.0, "y0": 1.0, "extra": 2.0})
    codes = {d.code for d in report.diagnostics}
    assert "below_lower_bound" in codes
    assert "unknown_parameter" in codes
    assert not report.ok


def test_run_is_deterministic():
    model = _model()
    first = model.run({"a": 1.0, "y0": 1.0}, _context())
    second = model.run({"a": 1.0, "y0": 1.0}, _context())
    assert first.ok and second.ok
    assert np.allclose(first.output("y").values, second.output("y").values)


def test_run_records_solver_diagnostics():
    result = _model().run({"a": 1.0, "y0": 1.0}, _context(solver="stiff"))
    assert any(d.code == "solver" and "BDF" in d.message for d in result.diagnostics)


def test_unknown_solver_rejected():
    with pytest.raises(ValueError):
        _model(solver="nonsense")


def test_output_names_must_match_state_count():
    with pytest.raises(ValueError):
        OdeModel(
            _schema(),
            lambda t, y, p: [y[0]],
            t_span=(0.0, 1.0),
            output_names=("y", "z"),
        )


def test_output_names_must_be_declared():
    with pytest.raises(ValueError):
        OdeModel(
            _schema(),
            lambda t, y, p: [y[0]],
            t_span=(0.0, 1.0),
            output_names=("not_declared",),
        )


def test_rhs_exception_becomes_failed_run():
    def exploding_rhs(t, y, params):
        raise RuntimeError("boom")

    result = _model(rhs=exploding_rhs).run({"a": 1.0, "y0": 1.0}, _context())
    assert result.status == RunStatus.FAILED
    assert any(d.code == "solver_exception" for d in result.diagnostics)


def test_invalid_inputs_do_not_execute():
    result = _model().run({"a": -5.0, "y0": 1.0}, _context())
    assert result.status == RunStatus.FAILED
