"""SCI-003: differential analysis between a reference run and variant runs.

The core operations from specification sections 4.3 and 4.4:

* absolute delta ``Δy = y_variant - y_reference``
* relative change ``r = Δy / y_reference`` where ``|y_reference| > ε``; where
  ``|y_reference| <= ε`` it is undefined, reported as ``NaN`` and *flagged*, never
  silently divided through
* summary metrics (MAE, RMSE, max abs delta, area delta, peak shift, correlation,
  distribution distance)

Identical inputs always produce a zero delta, and the alignment strategy used is
recorded on every comparison.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from drw.numerics import metrics
from drw.numerics.alignment import AlignmentError, AlignmentStrategy, align
from drw.schema.result import Diagnostic, OutputValue, RunRecord

__all__ = ["Comparison", "compare_outputs", "compare_run"]


@dataclass(slots=True)
class Comparison:
    """A structured differential relationship between two runs for one output."""

    reference_run_id: str
    variant_run_id: str
    label: str
    output: str
    unit: str
    method: str
    alignment: AlignmentStrategy
    interpolated: bool
    axis: tuple[float, ...]
    reference: tuple[float, ...]
    variant: tuple[float, ...]
    delta: tuple[float, ...]
    relative_delta: tuple[float, ...] | None
    metrics: dict[str, float] = field(default_factory=dict)
    warnings: tuple[Diagnostic, ...] = ()


def _axis_of(output: OutputValue, length: int) -> np.ndarray:
    if output.axis is not None:
        return np.asarray(output.axis, dtype=float).reshape(-1)
    return np.arange(length, dtype=float)


def compare_outputs(
    reference_run: RunRecord,
    variant_run: RunRecord,
    reference_output: OutputValue,
    variant_output: OutputValue,
    *,
    method: str = "delta",
    strategy: AlignmentStrategy = "exact",
    relative_epsilon: float = 1e-12,
) -> Comparison:
    """Compare one output of a variant run against the reference run."""
    ref_values = np.asarray(reference_output.values, dtype=float).reshape(-1)
    var_values = np.asarray(variant_output.values, dtype=float).reshape(-1)
    if ref_values.shape != var_values.shape:
        raise AlignmentError(
            f"output {reference_output.name!r} has mismatched shapes "
            f"{ref_values.shape} vs {var_values.shape}"
        )
    ref_axis = _axis_of(reference_output, ref_values.size)
    var_axis = _axis_of(variant_output, var_values.size)

    warnings: list[Diagnostic] = []
    try:
        aligned = align(ref_axis, ref_values, var_axis, var_values, strategy=strategy)
    except AlignmentError:
        if strategy != "exact":
            raise
        aligned = align(ref_axis, ref_values, var_axis, var_values, strategy="interpolate")
        warnings.append(
            Diagnostic(
                level="warning",
                code="alignment_fallback",
                message="coordinate axes differed; fell back to interpolated alignment",
            )
        )
    warnings.extend(aligned.diagnostics)

    delta = aligned.variant - aligned.reference

    # Mask non-finite (missing/undefined) pairs. Metrics are computed only over
    # finite pairs; the number of excluded points is always reported so a reader
    # can judge whether the metric is representative.
    finite = np.isfinite(aligned.reference) & np.isfinite(aligned.variant)
    invalid = int(np.count_nonzero(~finite))
    if invalid:
        warnings.append(
            Diagnostic(
                level="warning",
                code="non_finite_series",
                message=(
                    f"{invalid} point(s) are non-finite; metrics use the "
                    f"{int(finite.sum())} finite point(s)"
                ),
            )
        )
    valid_reference = aligned.reference[finite]
    valid_variant = aligned.variant[finite]
    valid_axis = aligned.axis[finite]

    # Relative change is only defined where the reference is safely away from
    # zero; unsafe points stay NaN and are counted.
    relative = np.full(delta.shape, np.nan, dtype=float)
    flagged = 0
    if valid_reference.size:
        safe = np.abs(valid_reference) > relative_epsilon
        relative_valid = np.full(valid_reference.shape, np.nan, dtype=float)
        relative_valid[safe] = (
            valid_variant[safe] - valid_reference[safe]
        ) / valid_reference[safe]
        relative[finite] = relative_valid
        flagged = int(np.count_nonzero(~safe))
    if flagged:
        warnings.append(
            Diagnostic(
                level="warning",
                code="unsafe_relative_denominator",
                message=(
                    f"{flagged} point(s) have |reference| <= {relative_epsilon:g}; "
                    "relative change is undefined there and reported as NaN"
                ),
            )
        )

    if valid_reference.size:
        summary: dict[str, float] = {
            "n_points": float(delta.size),
            "valid_points": float(valid_reference.size),
            "non_finite_points": float(invalid),
            "mae": metrics.mean_absolute_error(valid_reference, valid_variant),
            "rmse": metrics.root_mean_squared_error(valid_reference, valid_variant),
            "max_abs_delta": metrics.max_abs_delta(valid_reference, valid_variant),
            "area_delta": metrics.area_delta(valid_reference, valid_variant, valid_axis),
            "peak_shift": metrics.peak_shift(valid_axis, valid_reference, valid_variant),
            "correlation": metrics.correlation(valid_reference, valid_variant),
            "distribution_distance": metrics.distribution_distance(
                valid_reference, valid_variant
            ),
            "relative_delta_flagged_points": float(flagged),
        }
        if flagged < valid_reference.size:
            summary["max_abs_relative_delta"] = float(np.nanmax(np.abs(relative)))
        else:
            summary["max_abs_relative_delta"] = float("nan")
    else:
        summary = {
            "n_points": float(delta.size),
            "valid_points": 0.0,
            "non_finite_points": float(invalid),
            "mae": float("nan"),
            "rmse": float("nan"),
            "max_abs_delta": float("nan"),
            "area_delta": float("nan"),
            "peak_shift": float("nan"),
            "correlation": float("nan"),
            "distribution_distance": float("nan"),
            "relative_delta_flagged_points": float(flagged),
            "max_abs_relative_delta": float("nan"),
        }
        warnings.append(
            Diagnostic(
                level="error",
                code="no_finite_pairs",
                message="no finite reference/variant pairs; all comparison metrics are undefined",
            )
        )

    return Comparison(
        reference_run_id=reference_run.run_id,
        variant_run_id=variant_run.run_id,
        label=variant_run.label,
        output=reference_output.name,
        unit=reference_output.unit,
        method=method,
        alignment=aligned.strategy,
        interpolated=aligned.interpolated,
        axis=tuple(float(v) for v in aligned.axis),
        reference=tuple(float(v) for v in aligned.reference),
        variant=tuple(float(v) for v in aligned.variant),
        delta=tuple(float(v) for v in delta),
        relative_delta=tuple(float(v) for v in relative),
        metrics=summary,
        warnings=tuple(warnings),
    )


def compare_run(
    reference_run: RunRecord,
    variant_run: RunRecord,
    *,
    outputs: tuple[str, ...] | None = None,
    method: str = "delta",
    strategy: AlignmentStrategy = "exact",
    relative_epsilon: float = 1e-12,
) -> list[Comparison]:
    """Compare every selected output of ``variant_run`` against ``reference_run``."""
    if reference_run.result is None or variant_run.result is None:
        raise ValueError("both runs must carry a result to be compared")
    ref_result = reference_run.result
    var_result = variant_run.result
    if outputs is None:
        names = [name for name in ref_result.output_names() if name in var_result.outputs]
    else:
        names = [name for name in outputs if name in ref_result.outputs and name in var_result.outputs]
    return [
        compare_outputs(
            reference_run,
            variant_run,
            ref_result.output(name),
            var_result.output(name),
            method=method,
            strategy=strategy,
            relative_epsilon=relative_epsilon,
        )
        for name in names
    ]
