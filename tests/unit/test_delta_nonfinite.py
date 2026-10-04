"""Unit tests: differential analysis with missing / non-finite data."""

from __future__ import annotations

import math

import pytest

from drw.numerics.delta import compare_run
from drw.schema.model import ModelRef
from drw.schema.result import ModelResult, OutputValue, RunRecord, RunStatus

pytestmark = pytest.mark.unit


def _run(run_id: str, values, label: str = "variant") -> RunRecord:
    output = OutputValue(
        name="y", kind="timeseries", unit="dimensionless", values=list(values), labels=("y",)
    )
    result = ModelResult(status=RunStatus.SUCCEEDED, outputs={"y": output})
    return RunRecord(
        run_id=run_id,
        experiment_id="e",
        label=label,
        status=RunStatus.SUCCEEDED,
        model_ref=ModelRef(model_id="m"),
        result=result,
    )


def test_non_finite_points_are_masked_and_counted():
    reference = _run("r0", [0.0, 1.0, float("nan"), 3.0], label="baseline")
    variant = _run("r1", [0.0, 2.0, 2.0, 3.0])
    comparison = compare_run(reference, variant)[0]
    codes = {w.code for w in comparison.warnings}
    assert "non_finite_series" in codes
    assert comparison.metrics["non_finite_points"] == 1.0
    assert comparison.metrics["valid_points"] == 3.0
    # Metrics are finite because they use only the valid pairs.
    assert math.isfinite(comparison.metrics["mae"])
    assert comparison.metrics["mae"] == pytest.approx(1.0 / 3.0)


def test_all_non_finite_yields_undefined_metrics():
    reference = _run("r0", [float("nan"), float("nan")], label="baseline")
    variant = _run("r1", [1.0, 2.0])
    comparison = compare_run(reference, variant)[0]
    assert comparison.metrics["valid_points"] == 0.0
    assert any(w.code == "no_finite_pairs" for w in comparison.warnings)
    assert math.isnan(comparison.metrics["max_abs_delta"])


def test_infinite_values_are_also_masked():
    reference = _run("r0", [1.0, float("inf"), 3.0], label="baseline")
    variant = _run("r1", [1.0, 2.0, 3.0])
    comparison = compare_run(reference, variant)[0]
    assert comparison.metrics["valid_points"] == 2.0
    assert any(w.code == "non_finite_series" for w in comparison.warnings)
