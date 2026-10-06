"""Unit tests for M12A observation <-> model evaluation."""

from __future__ import annotations

import math

import pytest
from pydantic import ValidationError

from drw.evaluation import evaluate, evaluate_run
from drw.observations import build_dataset, science_hash
from drw.schema.evaluation import EvaluationConfig, compute_evaluation_hash
from drw.schema.model import ModelRef, ModelSchema, OutputSpec, ParameterSpec
from drw.schema.observation import (
    Dataset,
    MappingPair,
    ObservationMapping,
    ObservationSet,
    Provenance,
    QualitySpec,
    UncertaintySpec,
    Variable,
)
from drw.schema.result import ModelResult, OutputValue, RunRecord, RunStatus

pytestmark = pytest.mark.unit


def provenance(**overrides) -> Provenance:
    payload = {
        "source_kind": "synthetic",
        "imported_at": "2026-01-01T00:00:00+00:00",
        "dataset_version": "1.0.0",
    }
    payload.update(overrides)
    return Provenance(**payload)


def dataset(variables, columns, coordinates=(), *, name="ds", **prov) -> Dataset:
    observation_set = ObservationSet(
        coordinates=tuple(coordinates), variables=tuple(variables), columns=columns
    )
    return build_dataset(name, observation_set, provenance(**prov))


def timeseries_dataset(
    observed, coordinates, *, unit="K", coord_unit="s", uncertainty=None, quality=None, **prov
) -> Dataset:
    variables = [
        Variable(name="time", kind="float", role="coordinate", unit=coord_unit),
        Variable(
            name="y", kind="float", role="measurement", unit=unit, depends_on=("time",),
            uncertainty=uncertainty, quality=quality,
        ),
    ]
    return dataset(variables, {"time": list(coordinates), "y": list(observed)}, ("time",), **prov)


def out(name, kind, unit, values, *, axis=None, axis_unit=None) -> OutputValue:
    return OutputValue(
        name=name, kind=kind, unit=unit, values=values, shape=(), axis=axis, axis_unit=axis_unit
    )


def schema_for(output: OutputValue) -> ModelSchema:
    return ModelSchema(
        model_id="m",
        parameters=(ParameterSpec(name="k", type="float", nominal=1.0, lower=0.0, upper=2.0),),
        outputs=(OutputSpec(name=output.name, kind=output.kind, unit=output.unit, axis_unit=output.axis_unit),),
    )


def mapping_for(ds: Dataset, pairs) -> ObservationMapping:
    return ObservationMapping(dataset=ds.ref(), model_ref=ModelRef(model_id="m"), pairs=tuple(pairs))


def run_eval(ds, output, pairs, config=None, result=None):
    result = result or ModelResult(status=RunStatus.SUCCEEDED, outputs={output.name: output})
    return evaluate(
        result,
        schema=schema_for(output),
        dataset=ds,
        mapping=mapping_for(ds, pairs),
        config=config or EvaluationConfig(),
        experiment_id="exp-000000000000",
        run_id="r0",
        parameter_snapshot={"k": 1.0},
    )


def ts_pair(*, observation="y", output="y", coordinates=("time",)) -> MappingPair:
    return MappingPair(observation=observation, output=output, coordinates=coordinates)


# ---------------------------------------------------------------------------
# Config validation.
# ---------------------------------------------------------------------------


def test_config_rejects_missing_raw_mode():
    with pytest.raises(ValidationError):
        EvaluationConfig(residual_modes=("relative",))


def test_config_relative_metric_requires_relative_mode():
    with pytest.raises(ValidationError, match="relative"):
        EvaluationConfig(metrics=("relative_rmse",))


def test_config_weighted_metric_requires_normalized_mode():
    with pytest.raises(ValidationError, match="normalized"):
        EvaluationConfig(metrics=("chi_square",))


def test_config_reduced_chi_square_requires_dof():
    with pytest.raises(ValidationError, match="degrees_of_freedom"):
        EvaluationConfig(metrics=("reduced_chi_square",), residual_modes=("raw", "normalized"))


def test_config_rejects_bad_tolerance_and_origin():
    with pytest.raises(ValidationError):
        EvaluationConfig(alignment_tolerance=-1)
    with pytest.raises(ValidationError):
        EvaluationConfig(time_origin="not-a-date")


# ---------------------------------------------------------------------------
# Core math.
# ---------------------------------------------------------------------------


def test_perfect_model():
    ds = timeseries_dataset([0.0, 2.0, 4.0], [0.0, 1.0, 2.0])
    result = run_eval(ds, out("y", "timeseries", "K", [0.0, 2.0, 4.0], axis=(0.0, 1.0, 2.0), axis_unit="s"), [ts_pair()])
    assert result.ok is True
    metrics = result.pairs[0].metrics
    assert metrics["mean_residual"] == pytest.approx(0.0)
    assert metrics["mae"] == pytest.approx(0.0)
    assert metrics["rmse"] == pytest.approx(0.0)
    assert metrics["max_abs_error"] == pytest.approx(0.0)


def test_known_offset():
    ds = timeseries_dataset([0.0, 2.0, 4.0], [0.0, 1.0, 2.0])
    result = run_eval(ds, out("y", "timeseries", "K", [1.0, 3.0, 5.0], axis=(0.0, 1.0, 2.0), axis_unit="s"), [ts_pair()])
    metrics = result.pairs[0].metrics
    assert metrics["mean_residual"] == pytest.approx(1.0)
    assert metrics["mae"] == pytest.approx(1.0)
    assert metrics["rmse"] == pytest.approx(1.0)
    assert metrics["max_abs_error"] == pytest.approx(1.0)


def test_scalar_pair_broadcasts_to_rows():
    ds = dataset([Variable(name="y", kind="float", role="measurement", unit="K")], {"y": [4.0, 5.0, 6.0]})
    result = run_eval(ds, out("y", "scalar", "K", 5.0), [MappingPair(observation="y", output="y")])
    assert result.ok is True
    pair = result.pairs[0]
    assert pair.kind == "scalar" and pair.usable_count == 3
    assert [point.residual for point in pair.points] == [1.0, 0.0, -1.0]
    assert pair.metrics["max_abs_error"] == pytest.approx(1.0)


def test_relative_residuals_and_metrics():
    ds = timeseries_dataset([1.0, 2.0, 0.0], [0.0, 1.0, 2.0])
    output = out("y", "timeseries", "K", [1.1, 1.8, 5.0], axis=(0.0, 1.0, 2.0), axis_unit="s")
    config = EvaluationConfig(
        metrics=("mae", "relative_mae", "max_abs_relative_error"),
        residual_modes=("raw", "relative"),
    )
    result = run_eval(ds, output, [ts_pair()], config)
    pair = result.pairs[0]
    # observed 0 has |y| <= eps -> relative undefined there (flagged), still usable for raw.
    assert pair.metrics["mae"] == pytest.approx((0.1 + 0.2 + 5.0) / 3, abs=1e-9)
    assert pair.metrics["relative_mae"] == pytest.approx((0.1 + 0.1) / 2, abs=1e-9)
    assert any(d.code == "unsafe_relative_denominator" for d in pair.diagnostics)
    assert pair.points[2].relative_residual is None


def test_weighted_metrics_with_sigma():
    ds = timeseries_dataset(
        [1.0, 2.0], [0.0, 1.0], uncertainty=UncertaintySpec(type="std", value=0.5)
    )
    output = out("y", "timeseries", "K", [1.5, 2.5], axis=(0.0, 1.0), axis_unit="s")
    config = EvaluationConfig(
        metrics=("weighted_rmse", "chi_square", "reduced_chi_square"),
        residual_modes=("raw", "normalized"),
        degrees_of_freedom=2,
    )
    pair = run_eval(ds, output, [ts_pair()], config).pairs[0]
    # residuals 0.5, 0.5 -> normalized 1,1
    assert pair.metrics["weighted_rmse"] == pytest.approx(1.0)
    assert pair.metrics["chi_square"] == pytest.approx(2.0)
    assert pair.metrics["reduced_chi_square"] == pytest.approx(1.0)


def test_weighted_without_sigma_is_null_and_warned():
    ds = timeseries_dataset([1.0, 2.0], [0.0, 1.0])  # no uncertainty
    output = out("y", "timeseries", "K", [1.5, 2.5], axis=(0.0, 1.0), axis_unit="s")
    config = EvaluationConfig(metrics=("chi_square",), residual_modes=("raw", "normalized"))
    result = run_eval(ds, output, [ts_pair()], config)
    pair = result.pairs[0]
    assert pair.metrics["chi_square"] is None
    assert any(d.code == "uncertainty_not_usable" for d in pair.diagnostics)


def test_invalid_sigma_fails_closed():
    ds = timeseries_dataset(
        [1.0, 2.0], [0.0, 1.0], uncertainty=UncertaintySpec(type="std", value=0.0)
    )
    # value=0.0 passes M11 (>=0); evaluation must fail closed when used as a weight
    output = out("y", "timeseries", "K", [1.5, 2.5], axis=(0.0, 1.0), axis_unit="s")
    config = EvaluationConfig(metrics=("chi_square",), residual_modes=("raw", "normalized"))
    result = run_eval(ds, output, [ts_pair()], config)
    assert result.ok is False
    assert any(d.code == "invalid_uncertainty" for d in result.diagnostics)


def test_asymmetric_uncertainty_is_not_used_as_sigma():
    ds = timeseries_dataset(
        [1.0, 2.0], [0.0, 1.0],
        uncertainty=UncertaintySpec(type="asymmetric", lower=0.1, upper=0.2),
    )
    output = out("y", "timeseries", "K", [1.5, 2.5], axis=(0.0, 1.0), axis_unit="s")
    config = EvaluationConfig(metrics=("chi_square",), residual_modes=("raw", "normalized"))
    pair = run_eval(ds, output, [ts_pair()], config).pairs[0]
    assert pair.metrics["chi_square"] is None
    assert all(point.sigma is None for point in pair.points)


# ---------------------------------------------------------------------------
# Units.
# ---------------------------------------------------------------------------


def test_explicit_unit_conversion():
    ds = timeseries_dataset([1.0, 2.0], [0.0, 1.0], unit="km")
    output = out("y", "timeseries", "m", [1000.0, 2000.0], axis=(0.0, 1.0), axis_unit="s")
    pair = MappingPair(
        observation="y", output="y", coordinates=("time",),
        unit_conversion={"from_unit": "km", "to_unit": "m"},
    )
    result = run_eval(ds, output, [pair])
    assert result.ok is True
    assert result.pairs[0].metrics["mae"] == pytest.approx(0.0)


def test_units_differ_without_conversion_fails():
    ds = timeseries_dataset([1.0, 2.0], [0.0, 1.0], unit="km")
    output = out("y", "timeseries", "m", [1000.0, 2000.0], axis=(0.0, 1.0), axis_unit="s")
    result = run_eval(ds, output, [ts_pair()])
    assert result.ok is False
    assert any(d.code == "invalid_unit_conversion" for d in result.diagnostics)


def test_incompatible_units_fail():
    ds = timeseries_dataset([1.0, 2.0], [0.0, 1.0], unit="m")
    output = out("y", "timeseries", "K", [1.0, 2.0], axis=(0.0, 1.0), axis_unit="s")
    result = run_eval(ds, output, [ts_pair()])
    assert result.ok is False
    assert any(d.code == "incompatible_units" for d in result.diagnostics)


def test_unspecified_unit_fails():
    ds = timeseries_dataset([1.0, 2.0], [0.0, 1.0], unit=None)
    output = out("y", "timeseries", "K", [1.0, 2.0], axis=(0.0, 1.0), axis_unit="s")
    result = run_eval(ds, output, [ts_pair()])
    assert result.ok is False
    assert any(d.code == "unspecified_unit" for d in result.diagnostics)


# ---------------------------------------------------------------------------
# Missing / exclusions.
# ---------------------------------------------------------------------------


def test_missing_observation_is_counted_and_indexed():
    ds = timeseries_dataset([1.0, None, 3.0], [0.0, 1.0, 2.0])
    output = out("y", "timeseries", "K", [1.0, 2.0, 3.0], axis=(0.0, 1.0, 2.0), axis_unit="s")
    pair = run_eval(ds, output, [ts_pair()]).pairs[0]
    assert pair.usable_count == 2
    assert pair.excluded_count == 1
    assert pair.exclusion_counts == {"missing": 1}
    assert pair.exclusions[0].observation_index == 1


def test_unmatched_observation_is_a_warning_when_others_match():
    ds = timeseries_dataset([1.0, 2.0], [0.0, 5.0])
    output = out("y", "timeseries", "K", [1.0, 2.0], axis=(0.0, 1.0), axis_unit="s")
    result = run_eval(ds, output, [ts_pair()])
    assert result.ok is True
    pair = result.pairs[0]
    assert pair.usable_count == 1
    assert pair.exclusion_counts == {"unmatched": 1}


def test_all_unmatched_fails_closed():
    ds = timeseries_dataset([1.0, 2.0], [10.0, 20.0])
    output = out("y", "timeseries", "K", [1.0, 2.0], axis=(0.0, 1.0), axis_unit="s")
    result = run_eval(ds, output, [ts_pair()])
    assert result.ok is False
    assert any(d.code == "no_usable_observations" for d in result.diagnostics)


def test_quality_rejected_rows_are_excluded():
    quality = QualitySpec(flag_column="flag", rejected_flags=("bad",))
    ds = dataset(
        [
            Variable(name="time", kind="float", role="coordinate", unit="s"),
            Variable(name="y", kind="float", role="measurement", unit="K", depends_on=("time",), quality=quality),
            Variable(name="flag", kind="categorical", role="quality"),
        ],
        {"time": [0.0, 1.0], "y": [1.0, 2.0], "flag": ["good", "bad"]},
        ("time",),
    )
    output = out("y", "timeseries", "K", [1.0, 2.0], axis=(0.0, 1.0), axis_unit="s")
    pair = run_eval(ds, output, [ts_pair()]).pairs[0]
    assert pair.usable_count == 1
    assert pair.exclusion_counts == {"rejected": 1}


# ---------------------------------------------------------------------------
# Alignment.
# ---------------------------------------------------------------------------


def test_exact_alignment_tolerance():
    ds = timeseries_dataset([1.0, 2.0], [0.0, 1.0])
    output = out("y", "timeseries", "K", [1.0, 2.0], axis=(0.0, 1.0000001), axis_unit="s")
    tight = run_eval(ds, output, [ts_pair()], EvaluationConfig())
    assert tight.pairs[0].usable_count == 1  # second point unmatched without tolerance
    tolerant = run_eval(ds, output, [ts_pair()], EvaluationConfig(alignment_tolerance=1e-5))
    assert tolerant.pairs[0].usable_count == 2


def test_interpolation_is_opt_in_and_disclosed():
    ds = timeseries_dataset([1.0, 2.0, 3.0], [0.0, 1.0, 2.0])
    output = out("y", "timeseries", "K", [1.0, 3.0], axis=(0.0, 2.0), axis_unit="s")
    exact = run_eval(ds, output, [ts_pair()], EvaluationConfig())
    assert exact.pairs[0].usable_count == 2  # only 0 and 2 match exactly
    assert exact.pairs[0].interpolated is False

    interp = run_eval(ds, output, [ts_pair()], EvaluationConfig(alignment="interpolate"))
    pair = interp.pairs[0]
    assert pair.interpolated is True
    assert pair.usable_count == 3
    # midpoint observed 2.0 interpolates to 2.0
    assert pair.points[1].predicted == pytest.approx(2.0)
    assert any(d.code == "interpolated_alignment" for d in pair.diagnostics)


def test_interpolation_outside_range_is_unmatched():
    ds = timeseries_dataset([1.0, 2.0, 3.0], [0.0, 1.0, 5.0])
    output = out("y", "timeseries", "K", [1.0, 2.0, 3.0], axis=(0.0, 1.0, 2.0), axis_unit="s")
    pair = run_eval(ds, output, [ts_pair()], EvaluationConfig(alignment="interpolate")).pairs[0]
    assert pair.usable_count == 2
    assert pair.exclusion_counts == {"unmatched": 1}


# ---------------------------------------------------------------------------
# Datetime bridge.
# ---------------------------------------------------------------------------


def test_datetime_bridge():
    ds = dataset(
        [
            Variable(name="time_utc", kind="datetime", role="coordinate"),
            Variable(name="y", kind="float", role="measurement", unit="K", depends_on=("time_utc",)),
        ],
        {
            "time_utc": ["2026-01-01T00:00:00Z", "2026-01-01T00:01:00Z", "2026-01-01T00:02:00Z"],
            "y": [1.0, 2.0, 3.0],
        },
        ("time_utc",),
    )
    output = out("y", "timeseries", "K", [1.0, 2.0, 3.0], axis=(0.0, 60.0, 120.0), axis_unit="s")
    pair = MappingPair(observation="y", output="y", coordinates=("time_utc",))
    config = EvaluationConfig(time_origin="2026-01-01T00:00:00Z")
    result = run_eval(ds, output, [pair], config)
    assert result.ok is True
    assert result.pairs[0].usable_count == 3


def test_datetime_requires_time_origin():
    ds = dataset(
        [
            Variable(name="time_utc", kind="datetime", role="coordinate"),
            Variable(name="y", kind="float", role="measurement", unit="K", depends_on=("time_utc",)),
        ],
        {"time_utc": ["2026-01-01T00:00:00Z"], "y": [1.0]},
        ("time_utc",),
    )
    output = out("y", "timeseries", "K", [1.0], axis=(0.0,), axis_unit="s")
    pair = MappingPair(observation="y", output="y", coordinates=("time_utc",))
    result = run_eval(ds, output, [pair], EvaluationConfig())
    assert result.ok is False
    assert any(d.code == "datetime_axis_mismatch" for d in result.diagnostics)


# ---------------------------------------------------------------------------
# Failure semantics.
# ---------------------------------------------------------------------------


def test_unsupported_output_kind_fails():
    ds = dataset([Variable(name="y", kind="float", role="measurement", unit="K")], {"y": [1.0]})
    output = OutputValue(name="y", kind="matrix", unit="K", values=[[1.0]], shape=(1, 1))
    result = run_eval(ds, output, [MappingPair(observation="y", output="y")])
    assert result.ok is False
    assert any(d.code == "output_kind_unsupported" for d in result.diagnostics)


def test_non_finite_model_output_fails():
    ds = timeseries_dataset([1.0, 2.0], [0.0, 1.0])
    output = out("y", "timeseries", "K", [1.0, float("inf")], axis=(0.0, 1.0), axis_unit="s")
    result = run_eval(ds, output, [ts_pair()])
    assert result.ok is False
    assert any(d.code == "non_finite_model_output" for d in result.diagnostics)


def test_missing_output_fails():
    ds = timeseries_dataset([1.0, 2.0], [0.0, 1.0])
    output = out("other", "timeseries", "K", [1.0, 2.0], axis=(0.0, 1.0), axis_unit="s")
    result = run_eval(ds, output, [ts_pair()])
    assert result.ok is False
    assert any(d.code in ("output_missing", "unknown_output") for d in result.diagnostics)


def test_timeseries_requires_one_coordinate():
    ds = timeseries_dataset([1.0, 2.0], [0.0, 1.0])
    output = out("y", "timeseries", "K", [1.0, 2.0], axis=(0.0, 1.0), axis_unit="s")
    pair = MappingPair(observation="y", output="y", coordinates=())
    result = run_eval(ds, output, [pair])
    assert result.ok is False
    assert any(d.code == "coordinate_binding" for d in result.diagnostics)


def test_failed_run_fails_closed_without_execution():
    ds = timeseries_dataset([1.0, 2.0], [0.0, 1.0])
    output = out("y", "timeseries", "K", [1.0, 2.0], axis=(0.0, 1.0), axis_unit="s")
    run = RunRecord(
        run_id="r0", experiment_id="exp-000000000000", status=RunStatus.FAILED,
        model_ref=ModelRef(model_id="m"), result=None, timed_out=True,
    )
    result = evaluate_run(
        run, schema=schema_for(output), dataset=ds, mapping=mapping_for(ds, [ts_pair()]),
        config=EvaluationConfig(),
    )
    assert result.ok is False
    assert any(d.code == "run_timed_out" for d in result.diagnostics)


# ---------------------------------------------------------------------------
# Determinism / hashing.
# ---------------------------------------------------------------------------


def test_evaluation_is_deterministic_and_hash_consistent():
    ds = timeseries_dataset([1.0, 2.0], [0.0, 1.0])
    output = out("y", "timeseries", "K", [1.1, 2.2], axis=(0.0, 1.0), axis_unit="s")
    first = run_eval(ds, output, [ts_pair()])
    second = run_eval(ds, output, [ts_pair()])
    assert first.model_dump() == second.model_dump()
    assert first.evaluation_hash == second.evaluation_hash
    assert compute_evaluation_hash(first) == first.evaluation_hash
    assert len(first.evaluation_hash) == 64


def test_evaluation_hash_changes_with_data():
    ds_a = timeseries_dataset([1.0, 2.0], [0.0, 1.0])
    ds_b = timeseries_dataset([1.0, 2.5], [0.0, 1.0])
    output = out("y", "timeseries", "K", [1.1, 2.2], axis=(0.0, 1.0), axis_unit="s")
    assert run_eval(ds_a, output, [ts_pair()]).evaluation_hash != run_eval(ds_b, output, [ts_pair()]).evaluation_hash


# ---------------------------------------------------------------------------
# Science hash.
# ---------------------------------------------------------------------------


def test_science_hash_same_science_different_provenance():
    ds_a = timeseries_dataset([1.0, 2.0], [0.0, 1.0], imported_at="2026-01-01T00:00:00+00:00")
    ds_b = timeseries_dataset([1.0, 2.0], [0.0, 1.0], imported_at="2027-06-06T12:00:00+00:00")
    assert ds_a.content_hash != ds_b.content_hash
    assert science_hash(ds_a) == science_hash(ds_b)


def test_science_hash_changes_with_value():
    ds_a = timeseries_dataset([1.0, 2.0], [0.0, 1.0])
    ds_b = timeseries_dataset([1.0, 2.5], [0.0, 1.0])
    assert science_hash(ds_a) != science_hash(ds_b)


def test_science_hash_changes_with_schema():
    ds_a = timeseries_dataset([1.0, 2.0], [0.0, 1.0], unit="K")
    ds_b = timeseries_dataset([1.0, 2.0], [0.0, 1.0], unit="m")
    assert science_hash(ds_a) != science_hash(ds_b)


def test_science_hash_independent_of_variable_order():
    columns = {"time": [0.0, 1.0], "y": [1.0, 2.0]}
    forwards = dataset(
        [
            Variable(name="time", kind="float", role="coordinate", unit="s"),
            Variable(name="y", kind="float", role="measurement", unit="K", depends_on=("time",)),
        ],
        columns,
        ("time",),
    )
    backwards = dataset(
        [
            Variable(name="y", kind="float", role="measurement", unit="K", depends_on=("time",)),
            Variable(name="time", kind="float", role="coordinate", unit="s"),
        ],
        columns,
        ("time",),
    )
    assert science_hash(forwards) == science_hash(backwards)
    assert not math.isnan(float(int(science_hash(forwards)[:2], 16)))
