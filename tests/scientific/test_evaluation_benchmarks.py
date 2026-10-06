"""Scientific benchmark tests for M12A evaluation (deterministic expected math)."""

from __future__ import annotations

import numpy as np
import pytest

from drw.evaluation import evaluate, evaluate_run
from drw.observations import build_dataset
from drw.schema.evaluation import EvaluationConfig, compute_evaluation_hash
from drw.schema.model import ModelRef, ModelSchema, OutputSpec, ParameterSpec
from drw.schema.observation import (
    MappingPair,
    ObservationMapping,
    ObservationSet,
    Provenance,
    UncertaintySpec,
    Variable,
)
from drw.schema.result import ModelResult, OutputValue, RunRecord, RunStatus

pytestmark = pytest.mark.scientific


def _provenance() -> Provenance:
    return Provenance(
        source_kind="synthetic",
        imported_at="2026-01-01T00:00:00+00:00",
        dataset_version="1.0.0",
    )


def _dataset(observed, coordinates, *, unit="K", uncertainty=None) -> object:
    variables = [
        Variable(name="time", kind="float", role="coordinate", unit="s"),
        Variable(
            name="y", kind="float", role="measurement", unit=unit, depends_on=("time",),
            uncertainty=uncertainty,
        ),
    ]
    return build_dataset(
        "bench",
        ObservationSet(coordinates=("time",), variables=tuple(variables), columns={"time": list(coordinates), "y": list(observed)}),
        _provenance(),
    )


def _output(values, axis, *, unit="K", kind="timeseries") -> OutputValue:
    return OutputValue(name="y", kind=kind, unit=unit, values=values, shape=(), axis=axis, axis_unit="s")


def _schema(output: OutputValue) -> ModelSchema:
    return ModelSchema(
        model_id="m",
        parameters=(ParameterSpec(name="k", type="float", nominal=1.0, lower=0.0, upper=2.0),),
        outputs=(OutputSpec(name="y", kind=output.kind, unit=output.unit, axis_unit=output.axis_unit),),
    )


def _mapping(ds, *, coordinates=("time",), model_id="m", conversion=None):
    pair = MappingPair(observation="y", output="y", coordinates=coordinates, unit_conversion=conversion)
    return ObservationMapping(dataset=ds.ref(), model_ref=ModelRef(model_id=model_id), pairs=(pair,))


def _eval(ds, output, config=None, *, mapping=None):
    return evaluate(
        ModelResult(status=RunStatus.SUCCEEDED, outputs={"y": output}),
        schema=_schema(output),
        dataset=ds,
        mapping=mapping or _mapping(ds),
        config=config or EvaluationConfig(),
        experiment_id="exp-000000000000",
        run_id="r0",
    )


# 1. Perfect model.
def test_benchmark_perfect_model():
    x = [0.0, 1.0, 2.0, 3.0]
    observed = [2 * v for v in x]
    ds = _dataset(observed, x)
    result = _eval(ds, _output(list(observed), x))
    assert result.ok is True
    metrics = result.pairs[0].metrics
    assert metrics == {
        "mean_residual": pytest.approx(0.0),
        "mae": pytest.approx(0.0),
        "rmse": pytest.approx(0.0),
        "max_abs_error": pytest.approx(0.0),
    }


# 2. Known offset.
def test_benchmark_known_offset():
    x = [0.0, 1.0, 2.0, 3.0]
    ds = _dataset([2 * v for v in x], x)
    result = _eval(ds, _output([2 * v + 1.0 for v in x], x))
    metrics = result.pairs[0].metrics
    assert metrics["mean_residual"] == pytest.approx(1.0)
    assert metrics["mae"] == pytest.approx(1.0)
    assert metrics["rmse"] == pytest.approx(1.0)
    assert metrics["max_abs_error"] == pytest.approx(1.0)


# 3. Known deterministic perturbation.
def test_benchmark_known_perturbation():
    x = [0.0, 1.0, 2.0, 3.0]
    epsilon = 0.25
    ds = _dataset([1.0, 2.0, 3.0, 4.0], x)
    result = _eval(ds, _output([1.0 + epsilon, 2.0 + epsilon, 3.0 + epsilon, 4.0 + epsilon], x))
    metrics = result.pairs[0].metrics
    assert metrics["mean_residual"] == pytest.approx(epsilon)
    assert metrics["mae"] == pytest.approx(epsilon)
    assert metrics["rmse"] == pytest.approx(epsilon)
    assert metrics["max_abs_error"] == pytest.approx(epsilon)


# 4. Timeseries analytic (controlled amplitude difference).
def test_benchmark_timeseries_amplitude_difference():
    import math

    x = [v * math.pi / 8 for v in range(16)]
    observed = [2.0 * math.sin(v) for v in x]
    predicted = [1.5 * math.sin(v) for v in x]
    ds = _dataset(observed, x)
    result = _eval(ds, _output(predicted, x))
    residual = np.array(predicted) - np.array(observed)
    expected_rmse = float(np.sqrt(np.mean(residual**2)))
    assert result.pairs[0].metrics["rmse"] == pytest.approx(expected_rmse)
    assert result.pairs[0].metrics["mae"] == pytest.approx(float(np.mean(np.abs(residual))))


# 5. Interpolation.
def test_benchmark_interpolation():
    ds = _dataset([1.0, 2.0, 3.0], [0.0, 1.0, 2.0])
    output = _output([1.0, 3.0], [0.0, 2.0])
    exact = _eval(ds, output, EvaluationConfig())
    assert exact.pairs[0].usable_count == 2 and exact.pairs[0].interpolated is False

    interp = _eval(ds, output, EvaluationConfig(alignment="interpolate"))
    pair = interp.pairs[0]
    assert pair.interpolated is True
    assert pair.usable_count == 3
    assert pair.points[1].predicted == pytest.approx(2.0)
    assert any(d.code == "interpolated_alignment" for d in pair.diagnostics)


# 6. Unit conversion.
def test_benchmark_unit_conversion_factor():
    ds = _dataset([1.0, 2.0], [0.0, 1.0], unit="km")
    output = _output([1000.0, 2000.0], [0.0, 1.0], unit="m")
    mapping = _mapping(ds, conversion={"from_unit": "km", "to_unit": "m"})
    result = _eval(ds, output, mapping=mapping)
    assert result.ok is True
    assert result.pairs[0].unit == "m"
    assert result.pairs[0].metrics["mae"] == pytest.approx(0.0)


def test_benchmark_unit_conversion_required_when_units_differ():
    ds = _dataset([1.0, 2.0], [0.0, 1.0], unit="km")
    output = _output([1000.0, 2000.0], [0.0, 1.0], unit="m")
    result = _eval(ds, output)
    assert result.ok is False
    assert any(d.code == "invalid_unit_conversion" for d in result.diagnostics)


# 7. Incompatible units.
def test_benchmark_incompatible_units_fail():
    ds = _dataset([1.0, 2.0], [0.0, 1.0], unit="m")
    output = _output([1.0, 2.0], [0.0, 1.0], unit="K")
    result = _eval(ds, output)
    assert result.ok is False
    assert any(d.code == "incompatible_units" for d in result.diagnostics)


# 8. Missing observations.
def test_benchmark_missing_observation_accounting():
    ds = _dataset([1.0, None, 3.0], [0.0, 1.0, 2.0])
    output = _output([1.0, 2.0, 3.0], [0.0, 1.0, 2.0])
    pair = _eval(ds, output).pairs[0]
    assert pair.usable_count == 2
    assert pair.excluded_count == 1
    assert pair.exclusion_counts == {"missing": 1}
    assert pair.exclusions[0].observation_index == 1


# 9. Uncertainty.
def test_benchmark_weighted_metrics_with_known_sigma():
    ds = _dataset([1.0, 2.0], [0.0, 1.0], uncertainty=UncertaintySpec(type="std", value=0.5))
    output = _output([1.5, 2.5], [0.0, 1.0])
    config = EvaluationConfig(
        metrics=("chi_square", "reduced_chi_square"),
        residual_modes=("raw", "normalized"),
        degrees_of_freedom=2,
    )
    pair = _eval(ds, output, config).pairs[0]
    assert pair.metrics["chi_square"] == pytest.approx(2.0)
    assert pair.metrics["reduced_chi_square"] == pytest.approx(1.0)


def test_benchmark_asymmetric_uncertainty_never_becomes_sigma():
    ds = _dataset([1.0, 2.0], [0.0, 1.0], uncertainty=UncertaintySpec(type="asymmetric", lower=0.1, upper=0.2))
    output = _output([1.5, 2.5], [0.0, 1.0])
    config = EvaluationConfig(metrics=("chi_square",), residual_modes=("raw", "normalized"))
    pair = _eval(ds, output, config).pairs[0]
    assert pair.metrics["chi_square"] is None
    assert all(point.sigma is None for point in pair.points)


# 10. Repeated coordinates.
def test_benchmark_repeated_coordinates_preserved():
    ds = _dataset([1.0, 2.0, 3.0], [0.0, 0.0, 1.0])
    output = _output([5.0, 6.0], [0.0, 1.0])
    pair = _eval(ds, output).pairs[0]
    assert pair.usable_count == 3
    assert sum(1 for point in pair.points if point.coordinate == 0.0) == 2


# 11. Datetime.
def test_benchmark_datetime_bridge():
    ds = build_dataset(
        "dt",
        ObservationSet(
            coordinates=("when",),
            variables=(
                Variable(name="when", kind="datetime", role="coordinate"),
                Variable(name="y", kind="float", role="measurement", unit="K", depends_on=("when",)),
            ),
            columns={
                "when": ["2026-01-01T00:00:00Z", "2026-01-01T00:01:00Z"],
                "y": [1.0, 2.0],
            },
        ),
        _provenance(),
    )
    output = OutputValue(name="y", kind="timeseries", unit="K", values=[1.0, 2.0], shape=(), axis=(0.0, 60.0), axis_unit="s")
    pair = MappingPair(observation="y", output="y", coordinates=("when",))
    mapping = ObservationMapping(dataset=ds.ref(), model_ref=ModelRef(model_id="m"), pairs=(pair,))
    result = _eval(ds, output, EvaluationConfig(time_origin="2026-01-01T00:00:00Z"), mapping=mapping)
    assert result.ok is True and result.pairs[0].usable_count == 2


def test_benchmark_datetime_without_origin_fails():
    ds = build_dataset(
        "dt",
        ObservationSet(
            coordinates=("when",),
            variables=(
                Variable(name="when", kind="datetime", role="coordinate"),
                Variable(name="y", kind="float", role="measurement", unit="K", depends_on=("when",)),
            ),
            columns={"when": ["2026-01-01T00:00:00Z"], "y": [1.0]},
        ),
        _provenance(),
    )
    output = OutputValue(name="y", kind="timeseries", unit="K", values=[1.0], shape=(), axis=(0.0,), axis_unit="s")
    pair = MappingPair(observation="y", output="y", coordinates=("when",))
    mapping = ObservationMapping(dataset=ds.ref(), model_ref=ModelRef(model_id="m"), pairs=(pair,))
    result = _eval(ds, output, EvaluationConfig(), mapping=mapping)
    assert result.ok is False
    assert any(d.code == "datetime_axis_mismatch" for d in result.diagnostics)


# 12. Execution failure.
def test_benchmark_execution_failure_fails_closed():
    ds = _dataset([1.0, 2.0], [0.0, 1.0])
    output = _output([1.0, 2.0], [0.0, 1.0])
    run = RunRecord(
        run_id="r0", experiment_id="exp-000000000000", status=RunStatus.FAILED,
        model_ref=ModelRef(model_id="m"), result=None,
    )
    result = evaluate_run(run, schema=_schema(output), dataset=ds, mapping=_mapping(ds), config=EvaluationConfig())
    assert result.ok is False
    assert any(d.code == "run_not_succeeded" for d in result.diagnostics)


# 13. Non-finite model output.
def test_benchmark_non_finite_model_output_fails_closed():
    ds = _dataset([1.0, 2.0], [0.0, 1.0])
    output = _output([1.0, float("nan")], [0.0, 1.0])
    result = _eval(ds, output)
    assert result.ok is False
    assert any(d.code == "non_finite_model_output" for d in result.diagnostics)


# 14. Unsupported output kind.
def test_benchmark_unsupported_output_kind_fails_closed():
    ds = build_dataset(
        "scalar",
        ObservationSet(
            variables=(Variable(name="y", kind="float", role="measurement", unit="K"),),
            columns={"y": [1.0]},
        ),
        _provenance(),
    )
    output = OutputValue(name="y", kind="matrix", unit="K", values=[[1.0]], shape=(1, 1))
    pair = MappingPair(observation="y", output="y")
    mapping = ObservationMapping(dataset=ds.ref(), model_ref=ModelRef(model_id="m"), pairs=(pair,))
    result = _eval(ds, output, mapping=mapping)
    assert result.ok is False
    assert any(d.code == "output_kind_unsupported" for d in result.diagnostics)


# 15. Mapping mismatch.
def test_benchmark_model_mismatch_fails_closed():
    ds = _dataset([1.0, 2.0], [0.0, 1.0])
    output = _output([1.0, 2.0], [0.0, 1.0])
    mapping = _mapping(ds, model_id="other")
    result = _eval(ds, output, mapping=mapping)
    assert result.ok is False
    assert any(d.code == "model_mismatch" for d in result.diagnostics)


def test_benchmark_dataset_mismatch_fails_closed():
    ds = _dataset([1.0, 2.0], [0.0, 1.0])
    other = build_dataset(
        "other",
        ObservationSet(
            variables=(Variable(name="y", kind="float", role="measurement", unit="K"),),
            columns={"y": [1.0]},
        ),
        _provenance(),
    )
    output = _output([1.0, 2.0], [0.0, 1.0])
    mapping = ObservationMapping(
        dataset=other.ref(), model_ref=ModelRef(model_id="m"),
        pairs=(MappingPair(observation="y", output="y", coordinates=("time",)),),
    )
    result = _eval(ds, output, mapping=mapping)
    assert result.ok is False
    assert any(d.code == "dataset_mismatch" for d in result.diagnostics)


# 16. Determinism.
def test_benchmark_determinism():
    ds = _dataset([1.0, 2.0, 3.0], [0.0, 1.0, 2.0])
    output = _output([1.1, 2.2, 3.3], [0.0, 1.0, 2.0])
    first = _eval(ds, output)
    second = _eval(ds, output)
    assert first.model_dump() == second.model_dump()
    assert first.evaluation_hash == second.evaluation_hash
    assert compute_evaluation_hash(first) == first.evaluation_hash
