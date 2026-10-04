"""Scientific tests: determinism and perturbation growth in the Lorenz system."""

from __future__ import annotations

import numpy as np
import pytest

from drw.execution.context import RunContext
from drw.models.lorenz import build

pytestmark = pytest.mark.scientific


def _run(x0: float):
    model = build()
    inputs = {"sigma": 10.0, "rho": 28.0, "beta": 8.0 / 3.0, "x0": x0, "y0": 1.0, "z0": 1.0}
    return model.run(inputs, RunContext(run_id="r", experiment_id="e", rtol=1e-10, atol=1e-13))


def test_fixed_configuration_is_deterministic():
    first = _run(1.0)
    second = _run(1.0)
    assert np.array_equal(
        np.asarray(first.output("x").values), np.asarray(second.output("x").values)
    )


def test_nearby_initial_conditions_are_amplified():
    baseline = np.asarray(_run(1.0).output("x").values, dtype=float)
    perturbed = np.asarray(_run(1.0 + 1e-6).output("x").values, dtype=float)

    separation = np.abs(baseline - perturbed)
    assert separation[0] == pytest.approx(1e-6, rel=1e-3)

    # A pure-x perturbation can contract at first (the leading Lyapunov direction
    # is not aligned with x), so measure amplification against the early minimum
    # rather than the initial gap. Over this 20 time-unit window the perturbation
    # grows by orders of magnitude but does not yet saturate the attractor.
    early_min = separation[:50].min()
    assert early_min < separation[0]
    assert separation[-1] > 1e-4
    assert separation[-1] / early_min > 100.0
