"""Scientific tests: numerical convergence and method agreement.

These compare against an analytical reference and against a *different* solver
method, rather than only against previously recorded values.
"""

from __future__ import annotations

import numpy as np
import pytest

from drw.execution.context import RunContext
from drw.models.oscillator import analytic_displacement
from drw.models.oscillator import build as build_oscillator
from drw.models.predator_prey import build as build_predator_prey

pytestmark = pytest.mark.scientific


def _oscillator_error(rtol: float) -> float:
    model = build_oscillator()
    inputs = {"m": 1.0, "k": 4.0, "c": 0.2, "x0": 1.0, "v0": 0.0}
    context = RunContext(run_id="r", experiment_id="e", rtol=rtol, atol=1e-14)
    result = model.run(inputs, context)
    axis = np.asarray(result.output("x").axis, dtype=float)
    numeric = np.asarray(result.output("x").values, dtype=float)
    reference = analytic_displacement(axis, **inputs)
    return float(np.max(np.abs(numeric - reference)))


def test_tighter_tolerance_reduces_error_against_analytic_reference():
    errors = [_oscillator_error(rtol) for rtol in (1e-6, 1e-8, 1e-10)]
    # Error must not increase as tolerance tightens, and must improve overall.
    assert errors == sorted(errors, reverse=True)
    assert errors[-1] < errors[0]
    assert errors[-1] < 1e-6


def test_two_solver_methods_agree_on_a_non_stiff_problem():
    model = build_oscillator()
    inputs = {"m": 1.0, "k": 4.0, "c": 0.2, "x0": 1.0, "v0": 0.0}
    explicit = model.run(
        inputs, RunContext(run_id="r", experiment_id="e", solver="explicit", rtol=1e-10, atol=1e-13)
    )
    stiff = model.run(
        inputs, RunContext(run_id="r", experiment_id="e", solver="stiff", rtol=1e-10, atol=1e-13)
    )
    x_explicit = np.asarray(explicit.output("x").values, dtype=float)
    x_stiff = np.asarray(stiff.output("x").values, dtype=float)
    assert np.max(np.abs(x_explicit - x_stiff)) < 1e-5


def test_predator_prey_equilibrium_is_stationary():
    """At (prey*, predator*) = (gamma/delta, alpha/beta) the system is at rest."""
    model = build_predator_prey()
    inputs = {
        "alpha": 1.1,
        "beta": 0.4,
        "delta": 0.1,
        "gamma": 0.4,
        "prey0": 0.4 / 0.1,  # gamma / delta = 4
        "predator0": 1.1 / 0.4,  # alpha / beta = 2.75
    }
    result = model.run(inputs, RunContext(run_id="r", experiment_id="e", rtol=1e-11, atol=1e-13))
    prey = np.asarray(result.output("prey").values, dtype=float)
    predator = np.asarray(result.output("predator").values, dtype=float)
    assert np.max(np.abs(prey - inputs["prey0"])) < 1e-6
    assert np.max(np.abs(predator - inputs["predator0"])) < 1e-6
