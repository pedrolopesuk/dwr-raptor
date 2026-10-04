"""Time-series alignment for differential analysis (specification section 10.4).

Comparisons between two runs are only valid on a shared coordinate grid. This
module makes the alignment explicit and *discloses* whenever interpolation is
used, because interpolation can change conclusions.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import numpy as np

from drw.schema.result import Diagnostic

__all__ = ["AlignmentError", "AlignmentResult", "AlignmentStrategy", "align"]

AlignmentStrategy = Literal["exact", "interpolate", "resample"]


class AlignmentError(ValueError):
    """Raised when two series cannot be aligned under the requested strategy."""


@dataclass(slots=True)
class AlignmentResult:
    axis: np.ndarray
    reference: np.ndarray
    variant: np.ndarray
    strategy: AlignmentStrategy
    interpolated: bool
    diagnostics: tuple[Diagnostic, ...] = ()


def _as_float_array(values) -> np.ndarray:
    return np.asarray(values, dtype=float).reshape(-1)


def _interp_onto(axis: np.ndarray, values: np.ndarray, target: np.ndarray) -> np.ndarray:
    """Interpolate ``values`` (defined on ``axis``) onto ``target``."""
    if axis.ndim != 1 or values.ndim != 1 or axis.shape != values.shape:
        raise AlignmentError("axis and values must be 1-D and the same length")
    if axis.size < 2:
        raise AlignmentError("cannot interpolate a series with fewer than 2 points")
    order = np.argsort(axis, kind="stable")
    sorted_axis = axis[order]
    sorted_values = values[order]
    if np.any(np.diff(sorted_axis) <= 0):
        raise AlignmentError("axis must be strictly increasing to interpolate")
    return np.interp(target, sorted_axis, sorted_values)


def align(
    ref_axis,
    ref_values,
    var_axis,
    var_values,
    *,
    strategy: AlignmentStrategy = "exact",
    common_axis=None,
) -> AlignmentResult:
    """Align a variant series against a reference series.

    * ``exact`` - require identical coordinate axes (no interpolation).
    * ``interpolate`` - interpolate the variant onto the reference axis.
    * ``resample`` - interpolate *both* series onto ``common_axis`` (defaults to
      the reference axis).
    """
    ra = _as_float_array(ref_axis)
    rv = _as_float_array(ref_values)
    va = _as_float_array(var_axis)
    vv = _as_float_array(var_values)

    if strategy == "exact":
        if ra.shape != va.shape or not np.allclose(ra, va, rtol=1e-9, atol=1e-12):
            raise AlignmentError(
                "series coordinates differ; pass strategy='interpolate' or 'resample' "
                "to align them explicitly"
            )
        return AlignmentResult(
            axis=ra, reference=rv, variant=vv, strategy="exact", interpolated=False
        )

    if strategy == "interpolate":
        aligned_variant = _interp_onto(va, vv, ra)
        return AlignmentResult(
            axis=ra,
            reference=rv,
            variant=aligned_variant,
            strategy="interpolate",
            interpolated=True,
            diagnostics=(
                Diagnostic(
                    level="warning",
                    code="interpolated_alignment",
                    message=(
                        "variant series was interpolated onto the reference grid; "
                        "interpolation can change conclusions"
                    ),
                ),
            ),
        )

    if strategy == "resample":
        target = _as_float_array(common_axis if common_axis is not None else ra)
        return AlignmentResult(
            axis=target,
            reference=_interp_onto(ra, rv, target),
            variant=_interp_onto(va, vv, target),
            strategy="resample",
            interpolated=True,
            diagnostics=(
                Diagnostic(
                    level="warning",
                    code="resampled_alignment",
                    message="both series were resampled onto a common grid; interpolation is disclosed",
                ),
            ),
        )

    raise AlignmentError(f"unknown alignment strategy {strategy!r}")
