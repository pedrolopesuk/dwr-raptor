"""Unit tests for the descriptive uncertainty summary."""

from __future__ import annotations

import numpy as np
import pytest

from drw.schema.experiment import AnalysisSpec, ExperimentSpec, SamplingSpec
from drw.schema.model import ModelRef, ModelSchema, OutputSpec, ParameterSpec
from drw.schema.result import RunRecord, RunStatus
from drw.uncertainty import (
    GRID_NOTE,
    QUANTILE_METHOD,
    QUANTILES,
    compute_uncertainty,
)

pytestmark = pytest.mark.unit


def _schema(scalar: bool = True) -> ModelSchema:
    outputs = [OutputSpec(name="series", kind="timeseries", unit="dimensionless")]
    if scalar:
        outputs.insert(0, OutputSpec(name="peak", kind="scalar", unit="count"))
    return ModelSchema(
        model_id="m",
        parameters=(ParameterSpec(name="a", type="float", nominal=0.5, lower=0.0, upper=1.0),),
        outputs=tuple(outputs),
    )


def _spec(*, method: str = "latin_hypercube", n_samples: int | None = 4, seed: int = 7) -> ExperimentSpec:
    return ExperimentSpec(
        hypothesis="h",
        model_ref=ModelRef(model_id="m"),
        baseline={"a": 0.5},
        sampling=SamplingSpec(method=method, n_samples=n_samples, seed=seed),
        analyses=(AnalysisSpec(method="uncertainty"),),
    )


def _vrun(index: int, *, metrics=None, status=RunStatus.SUCCEEDED, timed_out: bool = False) -> RunRecord:
    return RunRecord(
        run_id=f"exp-x-r{index:04d}",
        experiment_id="exp-x",
        label="variant",
        status=status,
        model_ref=ModelRef(model_id="m"),
        metrics=metrics or {},
        timed_out=timed_out,
    )


def _summary(values: list[float]):
    runs = [_vrun(i, metrics={"peak": value}) for i, value in enumerate(values)]
    summary = compute_uncertainty(_schema(), _spec(n_samples=len(values)), runs)
    assert len(summary.outputs) == 1
    return summary.outputs[0]


def test_statistics_and_declared_quantile_method():
    output = _summary([1.0, 2.0, 3.0, 4.0])
    assert output.valid_samples == 4 and output.excluded_samples == 0
    assert output.sufficient is True
    assert output.mean == pytest.approx(2.5)
    assert output.std == pytest.approx(np.sqrt(5.0 / 3.0))  # ddof=1
    assert output.minimum == 1.0 and output.maximum == 4.0
    # numpy.percentile(method="linear"): p05 = 1.15, p50 = 2.5, p95 = 3.85
    assert (output.p05, output.p50, output.p95) == pytest.approx((1.15, 2.5, 3.85))
    assert QUANTILES == (5.0, 50.0, 95.0) and QUANTILE_METHOD == "linear"


def test_one_valid_sample_has_undefined_std_but_a_mean():
    output = _summary([5.0])
    assert output.valid_samples == 1 and output.sufficient is False
    assert output.mean == 5.0 and output.minimum == output.maximum == 5.0
    assert (output.p05, output.p50, output.p95) == (5.0, 5.0, 5.0)
    assert output.std is None
    assert output.note is not None and "standard deviation" in output.note


def test_no_valid_samples_reports_undefined_statistics():
    runs = [_vrun(0, status=RunStatus.FAILED), _vrun(1, status=RunStatus.FAILED, timed_out=True)]
    summary = compute_uncertainty(_schema(), _spec(n_samples=2), runs)
    output = summary.outputs[0]
    assert output.valid_samples == 0 and output.excluded_samples == 2
    assert output.sufficient is False
    assert output.mean is None and output.std is None and output.p50 is None
    assert output.exclusions == {"run_failed": 1, "run_timed_out": 1}
    assert output.note is not None and "no valid samples" in output.note


def test_exclusions_are_counted_and_never_substituted_with_zero():
    runs = [
        _vrun(0, metrics={"peak": 1.0}),
        _vrun(1, metrics={}),  # output_missing
        _vrun(2, status=RunStatus.FAILED),  # run_failed
        _vrun(3, metrics={"peak": float("nan")}),  # non_finite
    ]
    summary = compute_uncertainty(_schema(), _spec(n_samples=4), runs)
    output = summary.outputs[0]
    assert output.requested_variants == 4
    assert output.valid_samples == 1 and output.excluded_samples == 3
    assert output.exclusions == {"output_missing": 1, "run_failed": 1, "non_finite": 1}
    assert output.mean == 1.0  # only the valid sample; failures never become zero


def test_summary_level_counts_and_determinism():
    runs = [_vrun(i, metrics={"peak": float(i)}) for i in range(4)]
    schema, spec = _schema(), _spec(n_samples=4)
    first = compute_uncertainty(schema, spec, runs)
    second = compute_uncertainty(schema, spec, runs)
    assert first.model_dump() == second.model_dump()
    assert first.requested_variants == 4 and first.valid_output_samples == 4
    assert first.excluded_output_samples == 0
    assert first.quantile_method == "linear" and first.quantiles == [5.0, 50.0, 95.0]
    assert first.descriptive_only is True


def test_grid_design_is_flagged_as_not_a_sampling_distribution():
    runs = [_vrun(i, metrics={"peak": float(i)}) for i in range(3)]
    summary = compute_uncertainty(_schema(), _spec(method="grid", n_samples=None), runs)
    assert summary.note == GRID_NOTE


def test_no_scalar_outputs_produces_an_empty_summary_with_a_note():
    runs = [_vrun(0, metrics={})]
    summary = compute_uncertainty(_schema(scalar=False), _spec(n_samples=1), runs)
    assert summary.outputs == []
    assert summary.valid_output_samples == 0 and summary.excluded_output_samples == 0
    assert summary.requested_variants == 1
    assert summary.note is not None and "no scalar outputs" in summary.note


def test_summary_totals_sum_across_outputs_and_per_output_counts_are_authoritative():
    """F1: with two scalar outputs, the summary totals are output-sample sums and
    may exceed the variant count; per-output counts reconcile independently."""
    schema = ModelSchema(
        model_id="m",
        parameters=(ParameterSpec(name="a", type="float", nominal=0.5, lower=0.0, upper=1.0),),
        outputs=(
            OutputSpec(name="peak", kind="scalar", unit="count"),
            OutputSpec(name="final", kind="scalar", unit="count"),
        ),
    )
    runs = [_vrun(i, metrics={"peak": float(i), "final": float(i) + 0.5}) for i in range(4)]
    summary = compute_uncertainty(schema, _spec(n_samples=4), runs)

    assert summary.requested_variants == 4
    assert summary.valid_output_samples == 8  # 2 outputs x 4 variants
    assert summary.excluded_output_samples == 0
    for output in summary.outputs:
        assert output.valid_samples == 4 and output.requested_variants == 4
        assert output.excluded_samples == output.requested_variants - output.valid_samples
    assert summary.valid_output_samples != summary.requested_variants  # totals are output-samples
