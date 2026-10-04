"""Comparison metrics for differential analysis (specification section 10.5).

Every function takes the *reference* series first and the *variant* second, so a
positive delta always means "the variant is larger than the reference".
"""

from __future__ import annotations

from typing import Any

import numpy as np
from scipy.integrate import trapezoid
from scipy.stats import wasserstein_distance

__all__ = [
    "area_delta",
    "correlation",
    "distribution_distance",
    "max_abs_delta",
    "mean_absolute_error",
    "peak_shift",
    "root_mean_squared_error",
]


def _arr(values: Any) -> np.ndarray:
    return np.asarray(values, dtype=float).reshape(-1)


def mean_absolute_error(reference: Any, variant: Any) -> float:
    ref, var = _arr(reference), _arr(variant)
    if ref.shape != var.shape:
        raise ValueError("reference and variant must have the same shape")
    return float(np.mean(np.abs(var - ref)))


def root_mean_squared_error(reference: Any, variant: Any) -> float:
    ref, var = _arr(reference), _arr(variant)
    if ref.shape != var.shape:
        raise ValueError("reference and variant must have the same shape")
    return float(np.sqrt(np.mean((var - ref) ** 2)))


def max_abs_delta(reference: Any, variant: Any) -> float:
    ref, var = _arr(reference), _arr(variant)
    if ref.shape != var.shape:
        raise ValueError("reference and variant must have the same shape")
    return float(np.max(np.abs(var - ref)))


def area_delta(reference: Any, variant: Any, axis: Any | None = None) -> float:
    """Cumulative effect ``integral(variant - reference) dt``."""
    ref, var = _arr(reference), _arr(variant)
    if ref.shape != var.shape:
        raise ValueError("reference and variant must have the same shape")
    difference = var - ref
    if axis is None:
        return float(trapezoid(difference))
    return float(trapezoid(difference, _arr(axis)))


def peak_shift(axis: Any, reference: Any, variant: Any) -> float:
    """Absolute shift of the argmax location of the variant relative to the reference."""
    ax, ref, var = _arr(axis), _arr(reference), _arr(variant)
    if ref.size == 0 or var.size == 0:
        return float("nan")
    if ax.shape != ref.shape or ax.shape != var.shape:
        raise ValueError("axis, reference and variant must have the same shape")
    return float(abs(ax[int(np.argmax(var))] - ax[int(np.argmax(ref))]))


def correlation(reference: Any, variant: Any) -> float:
    """Pearson correlation (shape similarity, not magnitude equivalence)."""
    ref, var = _arr(reference), _arr(variant)
    if ref.size < 2 or var.size < 2:
        return float("nan")
    if np.std(ref) == 0.0 or np.std(var) == 0.0:
        return float("nan")
    return float(np.corrcoef(ref, var)[0, 1])


def distribution_distance(reference: Any, variant: Any) -> float:
    """Wasserstein distance between the two output distributions."""
    ref, var = _arr(reference), _arr(variant)
    if ref.size == 0 or var.size == 0:
        return float("nan")
    return float(wasserstein_distance(ref, var))
