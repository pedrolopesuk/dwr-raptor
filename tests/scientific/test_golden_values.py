"""Numerical regression corpus for the reference models.

These assertions guard against unintended changes in numerical behaviour. They
are *not* an external correctness proof; the analytic and invariant tests provide
that. See ``tests/fixtures/README.md``.
"""

from __future__ import annotations

import json

import numpy as np
import pytest

from drw.execution.context import RunContext
from drw.models.registry import build_model

pytestmark = pytest.mark.scientific

# Chaotic trajectories amplify tiny solver differences, so the Lorenz regression
# tolerance is deliberately looser than for the non-chaotic models. Determinism
# for a *fixed* configuration is asserted separately in test_lorenz.py.
TOLERANCE = {"oscillator": 1e-6, "predator-prey": 1e-6, "lorenz": 1e-3}


@pytest.mark.parametrize("model_id", ["oscillator", "predator-prey", "lorenz"])
def test_golden_regression_values(model_id, fixtures_dir):
    golden = json.loads((fixtures_dir / "golden_values.json").read_text(encoding="utf-8"))[model_id]
    model = build_model(model_id)
    # Match the defaults used to generate the corpus (RunContext rtol/atol).
    context = RunContext(run_id="g", experiment_id="g")
    result = model.run(golden["inputs"], context)
    assert result.ok

    relative = TOLERANCE[model_id]
    for name, value in result.outputs.items():
        values = np.asarray(value.values, dtype=float)
        if value.kind == "scalar":
            assert float(values) == pytest.approx(golden[name], rel=relative)
        else:
            assert float(values[-1]) == pytest.approx(golden[f"{name}_final"], rel=relative)
            assert float(values.max()) == pytest.approx(golden[f"{name}_max"], rel=relative)
            assert float(values.min()) == pytest.approx(golden[f"{name}_min"], rel=relative)
