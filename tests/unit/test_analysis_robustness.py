"""Unit tests: one bad output must not abort the whole analysis."""

from __future__ import annotations

import pytest

from drw.execution.runner import Runner
from drw.schema.experiment import ExperimentSpec
from drw.schema.model import ModelRef
from drw.schema.result import ModelResult, OutputValue, RunRecord, RunStatus

pytestmark = pytest.mark.unit


def _run(run_id: str, outputs: dict[str, list[float]], label: str = "variant") -> RunRecord:
    values = {
        name: OutputValue(name=name, kind="timeseries", unit="dimensionless", values=data)
        for name, data in outputs.items()
    }
    return RunRecord(
        run_id=run_id,
        experiment_id="e",
        label=label,
        status=RunStatus.SUCCEEDED,
        model_ref=ModelRef(model_id="m"),
        result=ModelResult(status=RunStatus.SUCCEEDED, outputs=values),
    )


def _spec() -> ExperimentSpec:
    return ExperimentSpec(
        hypothesis="h",
        model_ref={"model_id": "m"},
        baseline={},
        outputs=("y",),
        analyses=({"method": "delta"},),
    )


def test_incompatible_grids_are_reported_not_fatal():
    baseline = _run("r0", {"y": [0.0, 1.0, 2.0]}, label="baseline")
    incompatible = _run("r1", {"y": [0.0, 1.0]})
    comparisons, diagnostics = Runner._analyse(_spec(), [baseline, incompatible])
    assert comparisons == []
    assert any(d.code == "comparison_failed" for d in diagnostics)


def test_missing_output_is_reported():
    baseline = _run("r0", {"y": [0.0, 1.0, 2.0]}, label="baseline")
    missing = _run("r1", {"other": [0.0, 1.0, 2.0]})
    comparisons, diagnostics = Runner._analyse(_spec(), [baseline, missing])
    assert comparisons == []
    assert any(d.code == "output_missing_for_comparison" for d in diagnostics)


def test_healthy_variant_is_still_compared_alongside_a_bad_one():
    baseline = _run("r0", {"y": [0.0, 1.0, 2.0]}, label="baseline")
    bad = _run("r1", {"y": [0.0, 1.0]})
    good = _run("r2", {"y": [0.0, 2.0, 4.0]})
    comparisons, diagnostics = Runner._analyse(_spec(), [baseline, bad, good])
    assert len(comparisons) == 1
    assert comparisons[0].variant_run_id == "r2"
    assert any(d.code == "comparison_failed" for d in diagnostics)
