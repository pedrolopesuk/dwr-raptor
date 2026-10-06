"""Observation <-> model evaluation (M12A).

Execution-free evaluation of an already-produced deterministic model run against
a scientific :class:`~drw.schema.observation.Dataset`, under an M11
:class:`~drw.schema.observation.ObservationMapping` and an explicit
:class:`~drw.schema.evaluation.EvaluationConfig`.

The core (:func:`evaluate`) is a pure function over model ``OutputValue``s, a
Dataset, a Mapping and a Config. :func:`evaluate_run` is the canonical wrapper for
a completed :class:`~drw.schema.result.RunRecord`; it never executes the runner.

All scientifically invalid comparisons fail closed (``ok=False``, no metrics):
unknown variables/outputs, non-numeric observations, unsupported output kinds,
shape mismatches, unit problems, alignment failures, non-finite model outputs,
invalid uncertainty and no usable observations. Observations are never silently
dropped; exclusions carry explicit reasons and indices.
"""

from __future__ import annotations

import math
from datetime import datetime
from typing import Any

import numpy as np

from drw.observations import (
    ObservationError,
    convert_to_output,
    validate_mapping,
)
from drw.schema.evaluation import (
    RELATIVE_METRICS,
    WEIGHTED_METRICS,
    AlignedPoint,
    EvaluationConfig,
    EvaluationExclusion,
    EvaluationProvenance,
    EvaluationResult,
    PairEvaluation,
    compute_evaluation_hash,
)
from drw.schema.model import ModelRef, ModelSchema
from drw.schema.observation import Dataset, ObservationMapping, classify_value
from drw.schema.result import Diagnostic, ModelResult, OutputValue, RunRecord
from drw.schema.serialization import content_hash
from drw.schema.units import UnitError, convert, units_compatible

__all__ = ["evaluate", "evaluate_run"]

_SUPPORTED_OUTPUT_KINDS = ("scalar", "timeseries")


def _error(code: str, message: str) -> Diagnostic:
    return Diagnostic(level="error", code=code, message=message)


def _warning(code: str, message: str) -> Diagnostic:
    return Diagnostic(level="warning", code=code, message=message)


def _info(code: str, message: str) -> Diagnostic:
    return Diagnostic(level="info", code=code, message=message)


def _as_float_list(values: Any) -> list[float]:
    array = np.asarray(values, dtype=float).reshape(-1)
    return [float(v) for v in array]


def _parse_iso(value: str) -> datetime:
    text = value[:-1] + "+00:00" if value.endswith("Z") else value
    return datetime.fromisoformat(text)


def _resolve_axes(
    coord_kind: str,
    coord_unit: str | None,
    raw_coordinates: Any,
    output: OutputValue,
    model_axis: list[float],
    config: EvaluationConfig,
) -> tuple[list[float | None] | None, list[float] | None, list[Diagnostic]]:
    """Resolve the observation coordinate axis and the comparable model axis."""
    diagnostics: list[Diagnostic] = []
    axis_unit = output.axis_unit

    if coord_kind == "datetime":
        if config.time_origin is None:
            return None, None, [
                _error(
                    "datetime_axis_mismatch",
                    "a datetime coordinate requires an explicit time_origin in the evaluation config",
                )
            ]
        if axis_unit is None or not units_compatible(axis_unit, "s"):
            return None, None, [
                _error(
                    "datetime_axis_mismatch",
                    f"datetime observations require a time-unit model axis, got axis_unit={axis_unit!r}",
                )
            ]
        try:
            origin = _parse_iso(config.time_origin)
        except ValueError as exc:  # pragma: no cover - config validated
            return None, None, [_error("datetime_axis_mismatch", f"invalid time_origin: {exc}")]
        observed: list[float | None] = []
        mixed = False
        for value in raw_coordinates:
            if not isinstance(value, str):
                observed.append(None)
                continue
            try:
                instant = _parse_iso(value)
            except ValueError:
                observed.append(None)
                continue
            try:
                observed.append((instant - origin).total_seconds())
            except TypeError:
                observed.append(None)
                mixed = True
        if mixed:
            diagnostics.append(
                _warning(
                    "mixed_datetime_awareness",
                    "naive and timezone-aware datetimes must not be mixed; affected rows are excluded",
                )
            )
        try:
            model_axis_converted = [convert(v, axis_unit, "s") for v in model_axis]
        except UnitError as exc:  # pragma: no cover - guarded above
            return None, None, [_error("datetime_axis_mismatch", str(exc))]
        if axis_unit != "s":
            diagnostics.append(
                _info("axis_unit_converted", f"model axis converted from {axis_unit!r} to 's'")
            )
        return observed, model_axis_converted, diagnostics

    # numeric coordinate
    observed = []
    for value in raw_coordinates:
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(float(value))
        ):
            observed.append(None)
        else:
            observed.append(float(value))

    if coord_unit is None and axis_unit is None:
        return observed, list(model_axis), diagnostics
    if coord_unit is not None and axis_unit is not None and units_compatible(coord_unit, axis_unit):
        try:
            converted_axis = [convert(v, axis_unit, coord_unit) for v in model_axis]
        except UnitError as exc:  # pragma: no cover - guarded above
            return None, None, [_error("coordinate_axis_mismatch", str(exc))]
        if axis_unit != coord_unit:
            diagnostics.append(
                _info(
                    "axis_unit_converted",
                    f"model axis converted from {axis_unit!r} to coordinate unit {coord_unit!r}",
                )
            )
        return observed, converted_axis, diagnostics
    return None, None, [
        _error(
            "coordinate_axis_mismatch",
            f"coordinate unit {coord_unit!r} and model axis unit {axis_unit!r} are "
            "incompatible or partially unspecified",
        )
    ]


def _sigma_value(variable: Any, observation_set: Dataset, index: int) -> tuple[float | None, bool]:
    """Return ``(sigma, invalid)`` for one row. ``invalid`` means present but unusable."""
    uncertainty = variable.uncertainty
    if uncertainty is None or uncertainty.type not in ("std", "precision"):
        return None, False
    raw: float | None
    if uncertainty.value is not None:
        raw = float(uncertainty.value)
    elif uncertainty.column is not None:
        column = observation_set.observation_set.columns.get(uncertainty.column)
        if column is None or index >= len(column):  # pragma: no cover - M11 validates
            return None, False
        value = column[index]
        if value is None:
            return None, False  # missing sigma
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return None, False
        raw = float(value)
    else:  # pragma: no cover - M11 validates
        return None, False
    if not math.isfinite(raw) or raw <= 0:
        return None, True
    return raw, False


def _evaluate_pair(
    pair: Any,
    *,
    schema: ModelSchema,
    dataset: Dataset,
    model_result: ModelResult,
    config: EvaluationConfig,
) -> tuple[PairEvaluation | None, list[Diagnostic]]:
    diagnostics: list[Diagnostic] = []
    observation_set = dataset.observation_set
    by_name = {variable.name: variable for variable in observation_set.variables}

    variable = by_name.get(pair.observation)
    if variable is None:
        return None, [_error("unknown_observation", f"dataset has no variable {pair.observation!r}")]
    if variable.role != "measurement":
        return None, [
            _error(
                "observation_not_measurement",
                f"variable {pair.observation!r} has role {variable.role!r}, not 'measurement'",
            )
        ]
    if variable.kind not in ("float", "int"):
        return None, [
            _error(
                "observation_not_numeric",
                f"variable {pair.observation!r} has kind {variable.kind!r}; only numeric "
                "measurements can be evaluated",
            )
        ]

    output = model_result.outputs.get(pair.output)
    if output is None:
        return None, [_error("output_missing", f"model run has no output {pair.output!r}")]
    if output.kind not in _SUPPORTED_OUTPUT_KINDS:
        return None, [
            _error(
                "output_kind_unsupported",
                f"output {pair.output!r} has kind {output.kind!r}; only 'scalar' and "
                "'timeseries' are supported (a vector must be several component outputs)",
            )
        ]

    kind = "timeseries" if output.kind == "timeseries" else "scalar"

    # Units (validate_mapping already checked compatibility/direction). Re-check
    # here so the evaluator is self-contained and can hard-fail explicitly.
    observation_unit = variable.unit
    if observation_unit is None:
        return None, [
            _error("unspecified_unit", f"variable {pair.observation!r} has no unit")
        ]
    if not units_compatible(observation_unit, output.unit):
        return None, [
            _error(
                "incompatible_units",
                f"variable {pair.observation!r} unit {observation_unit!r} is incompatible with "
                f"output {pair.output!r} unit {output.unit!r}",
            )
        ]

    try:
        model_values = _as_float_list(output.values)
    except (ValueError, TypeError):
        return None, [_error("shape_mismatch", f"output {pair.output!r} is not numeric")]

    model_axis: list[float]
    if kind == "timeseries":
        if output.axis is None:
            return None, [
                _error("shape_mismatch", f"timeseries output {pair.output!r} has no axis")
            ]
        try:
            model_axis = _as_float_list(output.axis)
        except (ValueError, TypeError):
            return None, [_error("shape_mismatch", f"output {pair.output!r} axis is not numeric")]
        if len(model_axis) != len(model_values):
            return None, [
                _error(
                    "shape_mismatch",
                    f"output {pair.output!r} axis/values length mismatch "
                    f"({len(model_axis)} vs {len(model_values)})",
                )
            ]
        if not all(math.isfinite(v) for v in model_values) or not all(
            math.isfinite(v) for v in model_axis
        ):
            return None, [
                _error("non_finite_model_output", f"output {pair.output!r} contains non-finite values")
            ]
    else:
        if len(model_values) != 1:
            return None, [
                _error("shape_mismatch", f"scalar output {pair.output!r} is not a single value")
            ]
        if not math.isfinite(model_values[0]):
            return None, [
                _error("non_finite_model_output", f"output {pair.output!r} is non-finite")
            ]
        model_axis = [0.0]

    # Coordinate binding.
    obs_axis: list[float | None] | None = None
    if kind == "timeseries":
        if len(pair.coordinates) != 1:
            return None, [
                _error(
                    "coordinate_binding",
                    f"timeseries pair {pair.observation!r} requires exactly one coordinate, "
                    f"got {list(pair.coordinates)}",
                )
            ]
        coordinate_name = pair.coordinates[0]
        if coordinate_name not in observation_set.coordinates:
            return None, [
                _error("unknown_coordinate", f"unknown coordinate {coordinate_name!r}")
            ]
        if coordinate_name not in variable.depends_on:
            return None, [
                _error(
                    "coordinate_not_dependent",
                    f"variable {pair.observation!r} does not depend on {coordinate_name!r}",
                )
            ]
        coordinate_variable = by_name[coordinate_name]
        resolved, model_axis, axis_diagnostics = _resolve_axes(
            coordinate_variable.kind,
            coordinate_variable.unit,
            observation_set.columns.get(coordinate_name, []),
            output,
            model_axis,
            config,
        )
        diagnostics.extend(axis_diagnostics)
        if resolved is None:
            return None, diagnostics
        obs_axis = resolved
    elif pair.coordinates:
        return None, [
            _error(
                "coordinate_binding",
                f"scalar pair {pair.observation!r} must not bind coordinates",
            )
        ]

    values = observation_set.columns.get(variable.name, [])
    flags = (
        observation_set.columns.get(variable.quality.flag_column, [])
        if variable.quality is not None
        else []
    )
    row_count = len(values)

    exclusions: list[EvaluationExclusion] = []
    candidates: list[tuple[int, float]] = []  # (observation_index, observed)
    for index in range(row_count):
        reason = classify_value(variable.kind, values[index])
        if reason is None and variable.quality is not None and index < len(flags):
            reason = variable.quality.reason_for(flags[index])
        if reason is not None and reason != "flagged":
            exclusions.append(
                EvaluationExclusion(
                    observation_index=index,
                    reason=reason,
                    detail=f"observation {variable.name!r} row {index} is {reason}",
                )
            )
            continue
        if reason == "flagged":
            diagnostics.append(
                _info("flagged_observation", f"row {index} is flagged; kept usable")
            )
        try:
            observed = convert_to_output(
                float(values[index]),
                observation_unit=observation_unit,
                output_unit=output.unit,
                conversion=pair.unit_conversion,
            )
        except ObservationError as exc:
            return None, [_error("invalid_unit_conversion", str(exc))]
        candidates.append((index, observed))

    # Align model values to observation coordinates.
    matched: list[tuple[int, int | None, float | None, float, float]] = []
    interpolated = False
    if kind == "timeseries":
        assert obs_axis is not None
        ready: list[tuple[int, float, float]] = []
        for index, observed in candidates:
            coordinate = obs_axis[index]
            if coordinate is None:
                exclusions.append(
                    EvaluationExclusion(
                        observation_index=index,
                        reason="invalid",
                        detail="coordinate is missing or invalid",
                    )
                )
                continue
            ready.append((index, observed, coordinate))

        if config.alignment == "exact":
            from drw.observations import align as align_exact

            query = [coordinate for (_, _, coordinate) in ready]
            result = align_exact(
                model_axis, query, strategy="exact", tolerance=config.alignment_tolerance
            )
            for (index, observed, coordinate), model_index in zip(
                ready, result.matches, strict=True
            ):
                if model_index is None:
                    exclusions.append(
                        EvaluationExclusion(
                            observation_index=index,
                            reason="unmatched",
                            detail=(
                                f"coordinate {coordinate!r} has no model point within "
                                f"tolerance {config.alignment_tolerance:g}"
                            ),
                        )
                    )
                    continue
                matched.append(
                    (index, model_index, coordinate, observed, model_values[model_index])
                )
        else:  # interpolate
            order = sorted(range(len(model_axis)), key=lambda k: model_axis[k])
            sorted_axis = [model_axis[k] for k in order]
            sorted_values = [model_values[k] for k in order]
            if any(
                sorted_axis[k] >= sorted_axis[k + 1] for k in range(len(sorted_axis) - 1)
            ):
                return None, [
                    _error(
                        "alignment_failed",
                        "model axis must be strictly increasing to interpolate",
                    )
                ]
            low, high = sorted_axis[0], sorted_axis[-1]
            interpolated = True
            diagnostics.append(
                _warning(
                    "interpolated_alignment",
                    "model output was linearly interpolated onto the observation coordinates; "
                    "interpolation can change conclusions",
                )
            )
            for index, observed, coordinate in ready:
                if coordinate < low or coordinate > high:
                    exclusions.append(
                        EvaluationExclusion(
                            observation_index=index,
                            reason="unmatched",
                            detail=(
                                f"coordinate {coordinate!r} is outside the model axis range "
                                f"[{low}, {high}]"
                            ),
                        )
                    )
                    continue
                predicted = float(np.interp(coordinate, sorted_axis, sorted_values))
                matched.append((index, None, coordinate, observed, predicted))
    else:
        for index, observed in candidates:
            matched.append((index, None, None, observed, model_values[0]))

    # Build aligned points and residuals.
    weighted_requested = "normalized" in config.residual_modes
    relative_requested = "relative" in config.residual_modes
    points: list[AlignedPoint] = []
    relative_flagged = 0
    weighted_missing = 0
    for index, model_index, coordinate, observed, predicted in matched:
        if not math.isfinite(predicted):
            return None, [_error("non_finite_model_output", f"row {index} produced a non-finite prediction")]
        residual = predicted - observed
        relative: float | None = None
        if relative_requested:
            if abs(observed) > config.relative_epsilon:
                relative = residual / observed
            else:
                relative_flagged += 1
        sigma: float | None = None
        normalized: float | None = None
        if weighted_requested:
            candidate, invalid = _sigma_value(variable, dataset, index)
            if invalid:
                return None, [
                    _error(
                        "invalid_uncertainty",
                        f"row {index} has an unusable symmetric sigma (non-finite or <= 0)",
                    )
                ]
            if candidate is not None:
                sigma = candidate
                normalized = residual / candidate
            else:
                weighted_missing += 1
        points.append(
            AlignedPoint(
                observation_index=index,
                model_index=model_index,
                coordinate=coordinate,
                observed=observed,
                predicted=predicted,
                residual=residual,
                relative_residual=relative,
                sigma=sigma,
                normalized_residual=normalized,
            )
        )

    if relative_flagged:
        diagnostics.append(
            _warning(
                "unsafe_relative_denominator",
                f"{relative_flagged} point(s) have |observed| <= {config.relative_epsilon:g}; "
                "relative residuals are undefined there",
            )
        )
    if weighted_requested and weighted_missing:
        diagnostics.append(
            _warning(
                "uncertainty_not_usable",
                f"{weighted_missing} point(s) have no usable symmetric sigma (std/precision); "
                "they are excluded from weighted metrics",
            )
        )

    metrics = _compute_metrics(points, config)

    exclusion_counts: dict[str, int] = {}
    for exclusion in exclusions:
        exclusion_counts[exclusion.reason] = exclusion_counts.get(exclusion.reason, 0) + 1

    return (
        PairEvaluation(
            observation=pair.observation,
            output=pair.output,
            kind=kind,
            unit=output.unit,
            alignment=config.alignment,
            tolerance=config.alignment_tolerance,
            interpolated=interpolated,
            points=points,
            exclusions=exclusions,
            usable_count=len(points),
            excluded_count=len(exclusions),
            exclusion_counts=exclusion_counts,
            metrics=metrics,
            diagnostics=diagnostics,
        ),
        diagnostics,
    )


def _compute_metrics(
    points: list[AlignedPoint], config: EvaluationConfig
) -> dict[str, float | None]:
    requested = list(config.metrics)
    metrics: dict[str, float | None] = {name: None for name in requested}
    if not points:
        return metrics

    residuals = np.array([point.residual for point in points], dtype=float)
    if "mean_residual" in metrics:
        metrics["mean_residual"] = float(np.mean(residuals))
    if "mae" in metrics:
        metrics["mae"] = float(np.mean(np.abs(residuals)))
    if "rmse" in metrics:
        metrics["rmse"] = float(np.sqrt(np.mean(residuals**2)))
    if "max_abs_error" in metrics:
        metrics["max_abs_error"] = float(np.max(np.abs(residuals)))

    if set(requested) & set(RELATIVE_METRICS):
        relative = np.array(
            [point.relative_residual for point in points if point.relative_residual is not None],
            dtype=float,
        )
        if relative.size:
            if "relative_mae" in metrics:
                metrics["relative_mae"] = float(np.mean(np.abs(relative)))
            if "relative_rmse" in metrics:
                metrics["relative_rmse"] = float(np.sqrt(np.mean(relative**2)))
            if "max_abs_relative_error" in metrics:
                metrics["max_abs_relative_error"] = float(np.max(np.abs(relative)))

    if set(requested) & set(WEIGHTED_METRICS):
        normalized = np.array(
            [point.normalized_residual for point in points if point.normalized_residual is not None],
            dtype=float,
        )
        if normalized.size:
            if "weighted_rmse" in metrics:
                metrics["weighted_rmse"] = float(np.sqrt(np.mean(normalized**2)))
            if "chi_square" in metrics:
                metrics["chi_square"] = float(np.sum(normalized**2))
            if "reduced_chi_square" in metrics:
                assert config.degrees_of_freedom is not None
                metrics["reduced_chi_square"] = float(
                    np.sum(normalized**2) / config.degrees_of_freedom
                )
    return metrics


def _finalize(
    base: dict[str, Any],
    *,
    pairs: list[PairEvaluation],
    ok: bool,
    diagnostics: list[Diagnostic],
    total_usable: int = 0,
    total_excluded: int = 0,
) -> EvaluationResult:
    result = EvaluationResult(
        evaluation_hash="",
        pairs=pairs,
        ok=ok,
        diagnostics=diagnostics,
        total_usable=total_usable,
        total_excluded=total_excluded,
        **base,
    )
    return result.model_copy(update={"evaluation_hash": compute_evaluation_hash(result)})


def _base(
    dataset: Dataset,
    mapping: ObservationMapping,
    config: EvaluationConfig,
    *,
    model_ref: ModelRef,
    model_hash: str,
    parameter_snapshot: Any,
    experiment_id: str,
    run_id: str,
    attempt: int,
    spec_hash: str,
    environment_hash: str,
) -> dict[str, Any]:
    mapping_hash = content_hash(mapping)
    return {
        "dataset": dataset.ref(),
        "experiment_id": experiment_id,
        "run_id": run_id,
        "attempt": attempt,
        "model_ref": model_ref,
        "model_hash": model_hash,
        "parameter_snapshot": dict(parameter_snapshot or {}),
        "mapping": mapping,
        "mapping_hash": mapping_hash,
        "config": config,
        "provenance": EvaluationProvenance(
            spec_hash=spec_hash,
            model_hash=model_hash,
            environment_hash=environment_hash,
            dataset_content_hash=dataset.content_hash,
            mapping_hash=mapping_hash,
        ),
    }


def evaluate(
    model_result: ModelResult,
    *,
    schema: ModelSchema,
    dataset: Dataset,
    mapping: ObservationMapping,
    config: EvaluationConfig,
    experiment_id: str,
    run_id: str,
    attempt: int = 1,
    model_ref: ModelRef | None = None,
    model_hash: str = "",
    parameter_snapshot: Any = None,
    spec_hash: str = "",
    environment_hash: str = "",
) -> EvaluationResult:
    """Evaluate model outputs against a dataset (pure; never executes a model)."""
    resolved_ref = model_ref or mapping.model_ref
    base = _base(
        dataset,
        mapping,
        config,
        model_ref=resolved_ref,
        model_hash=model_hash,
        parameter_snapshot=parameter_snapshot,
        experiment_id=experiment_id,
        run_id=run_id,
        attempt=attempt,
        spec_hash=spec_hash,
        environment_hash=environment_hash,
    )

    if not model_result.ok:
        return _finalize(
            base,
            pairs=[],
            ok=False,
            diagnostics=[_error("run_not_succeeded", "the model result is not SUCCEEDED")],
        )

    structural = list(validate_mapping(mapping, dataset=dataset, schema=schema))
    if any(diagnostic.level == "error" for diagnostic in structural):
        return _finalize(base, pairs=[], ok=False, diagnostics=structural)

    pairs: list[PairEvaluation] = []
    for pair in mapping.pairs:
        pair_evaluation, pair_diagnostics = _evaluate_pair(
            pair, schema=schema, dataset=dataset, model_result=model_result, config=config
        )
        if pair_evaluation is None:
            return _finalize(
                base,
                pairs=[],
                ok=False,
                diagnostics=[*structural, *pair_diagnostics],
            )
        pairs.append(pair_evaluation)

    total_usable = sum(pair.usable_count for pair in pairs)
    total_excluded = sum(pair.excluded_count for pair in pairs)
    if total_usable == 0:
        return _finalize(
            base,
            pairs=[],
            ok=False,
            diagnostics=[
                *structural,
                _error(
                    "no_usable_observations",
                    "no usable observation/prediction comparisons remain",
                ),
            ],
        )
    return _finalize(
        base,
        pairs=pairs,
        ok=True,
        diagnostics=structural,
        total_usable=total_usable,
        total_excluded=total_excluded,
    )


def evaluate_run(
    run: RunRecord,
    *,
    schema: ModelSchema,
    dataset: Dataset,
    mapping: ObservationMapping,
    config: EvaluationConfig,
    spec_hash: str = "",
    environment_hash: str = "",
    model_hash: str = "",
) -> EvaluationResult:
    """Canonical evaluation of a completed run (read-only; never re-executes)."""
    base = _base(
        dataset,
        mapping,
        config,
        model_ref=run.model_ref,
        model_hash=model_hash,
        parameter_snapshot=run.inputs,
        experiment_id=run.experiment_id,
        run_id=run.run_id,
        attempt=run.attempt,
        spec_hash=spec_hash,
        environment_hash=environment_hash,
    )
    if not run.succeeded:
        code = "run_timed_out" if run.timed_out else "run_not_succeeded"
        return _finalize(base, pairs=[], ok=False, diagnostics=[_error(code, f"run is {run.status}")])
    if run.result is None:
        return _finalize(
            base,
            pairs=[],
            ok=False,
            diagnostics=[_error("run_not_succeeded", "the run has no result to evaluate")],
        )
    return evaluate(
        run.result,
        schema=schema,
        dataset=dataset,
        mapping=mapping,
        config=config,
        experiment_id=run.experiment_id,
        run_id=run.run_id,
        attempt=run.attempt,
        model_ref=run.model_ref,
        model_hash=model_hash,
        parameter_snapshot=run.inputs,
        spec_hash=spec_hash,
        environment_hash=environment_hash,
    )
