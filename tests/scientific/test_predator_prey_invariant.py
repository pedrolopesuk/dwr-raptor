"""Scientific test: the Lotka-Volterra conserved quantity is preserved."""

from __future__ import annotations

import numpy as np
import pytest

from drw.execution.context import RunContext
from drw.models.predator_prey import build, conserved_quantity

pytestmark = pytest.mark.scientific


def test_conserved_quantity_is_preserved_along_the_trajectory():
    model = build()
    schema = model.describe()
    inputs = {p.name: float(p.nominal) for p in schema.parameters}
    result = model.run(inputs, RunContext(run_id="r", experiment_id="e", rtol=1e-10, atol=1e-13))
    assert result.ok

    prey = np.asarray(result.output("prey").values, dtype=float)
    predator = np.asarray(result.output("predator").values, dtype=float)
    invariant = np.array(
        [conserved_quantity([prey[i], predator[i]], inputs) for i in range(prey.size)]
    )
    assert invariant.max() - invariant.min() < 1e-5


def test_populations_remain_positive():
    model = build()
    inputs = {p.name: float(p.nominal) for p in model.describe().parameters}
    result = model.run(inputs, RunContext(run_id="r", experiment_id="e"))
    assert np.all(np.asarray(result.output("prey").values) > 0.0)
    assert np.all(np.asarray(result.output("predator").values) > 0.0)
