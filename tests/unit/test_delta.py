"""Unit tests for differential analysis."""

from __future__ import annotations

import math

import pytest

from drw.numerics.alignment import AlignmentError
from drw.numerics.delta import compare_run
from drw.schema.model import ModelRef
from drw.schema.result import ModelResult, OutputValue, RunRecord, RunStatus

pytestmark = pytest.mark.unit


def _run(run_id: str, values, axis=None, label: str = "variant") -> RunRecord:
    output = OutputValue(
        name="y",
        kind="timeseries",
        unit="dimensionless",
        values=list(values),
        axis=list(axis) if axis is not None else None,
        labels=("y",),
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


def test_identical_runs_have_zero_delta():
    reference = _run("r0", [1.0, 2.0, 3.0], label="baseline")
    variant = _run("r1", [1.0, 2.0, 3.0])
    comparisons = compare_run(reference, variant)
    assert len(comparisons) == 1
    comparison = comparisons[0]
    assert comparison.metrics["max_abs_delta"] == 0.0
    assert all(delta == 0.0 for delta in comparison.delta)
    assert comparison.alignment == "exact"


def test_relative_delta_flags_near_zero_denominator():
    reference = _run("r0", [0.0, 1.0, 2.0], label="baseline")
    variant = _run("r1", [0.0, 2.0, 4.0])
    comparison = compare_run(reference, variant, relative_epsilon=1e-12)[0]
    assert any(w.code == "unsafe_relative_denominator" for w in comparison.warnings)
    assert math.isnan(comparison.relative_delta[0])
    assert comparison.relative_delta[1] == pytest.approx(1.0)


def test_alignment_falls_back_and_discloses_when_axes_differ():
    reference = _run("r0", [0.0, 1.0, 2.0], axis=[0.0, 1.0, 2.0], label="baseline")
    variant = _run("r1", [0.0, 0.5, 1.0], axis=[0.0, 0.5, 1.0])
    comparison = compare_run(reference, variant)[0]
    assert comparison.interpolated is True
    assert any(w.code == "alignment_fallback" for w in comparison.warnings)


def test_shape_mismatch_raises():
    reference = _run("r0", [0.0, 1.0, 2.0], label="baseline")
    variant = _run("r1", [0.0, 1.0])
    with pytest.raises(AlignmentError):
        compare_run(reference, variant)


def test_missing_result_raises():
    reference = _run("r0", [0.0, 1.0], label="baseline")
    empty = RunRecord(
        run_id="r1",
        experiment_id="e",
        status=RunStatus.FAILED,
        model_ref=ModelRef(model_id="m"),
    )
    with pytest.raises(ValueError):
        compare_run(reference, empty)
