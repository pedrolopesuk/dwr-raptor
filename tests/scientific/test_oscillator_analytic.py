"""Scientific test: the integrator reproduces the closed-form oscillator trajectory.

This is the strongest form of numerical check in the suite: an analytic reference,
not a previously recorded value.
"""

from __future__ import annotations

import numpy as np
import pytest

from drw.execution.context import RunContext
from drw.models.oscillator import analytic_displacement, build

pytestmark = pytest.mark.scientific


def test_numeric_displacement_matches_closed_form():
    model = build()
    inputs = {"m": 1.0, "k": 4.0, "c": 0.2, "x0": 1.0, "v0": 0.0}
    context = RunContext(run_id="r", experiment_id="e", rtol=1e-10, atol=1e-13)
    result = model.run(inputs, context)
    assert result.ok

    output = result.output("x")
    numeric = np.asarray(output.values, dtype=float)
    axis = np.asarray(output.axis, dtype=float)
    reference = analytic_displacement(axis, **inputs)

    assert np.max(np.abs(numeric - reference)) < 1e-6


def test_undamped_oscillator_conserves_energy():
    # With c = 0 the mechanical energy 0.5*k*x^2 + 0.5*m*v^2 is invariant.
    model = build()
    inputs = {"m": 2.0, "k": 5.0, "c": 0.0, "x0": 1.0, "v0": 0.0}
    context = RunContext(run_id="r", experiment_id="e", rtol=1e-11, atol=1e-13)
    result = model.run(inputs, context)

    x = np.asarray(result.output("x").values, dtype=float)
    v = np.asarray(result.output("v").values, dtype=float)
    energy = 0.5 * inputs["k"] * x**2 + 0.5 * inputs["m"] * v**2
    assert (energy.max() - energy.min()) / energy.mean() < 1e-6
