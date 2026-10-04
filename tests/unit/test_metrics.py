"""Unit tests for comparison metrics."""

from __future__ import annotations

import numpy as np
import pytest

from drw.numerics import metrics

pytestmark = pytest.mark.unit


def test_identical_series_have_zero_error():
    values = [1.0, 2.0, 3.0]
    assert metrics.mean_absolute_error(values, values) == 0.0
    assert metrics.root_mean_squared_error(values, values) == 0.0
    assert metrics.max_abs_delta(values, values) == 0.0


def test_known_mae_and_rmse():
    reference = [0.0, 0.0]
    variant = [1.0, 2.0]
    assert metrics.mean_absolute_error(reference, variant) == pytest.approx(1.5)
    assert metrics.root_mean_squared_error(reference, variant) == pytest.approx(np.sqrt(2.5))


def test_area_delta_is_signed_and_integrated():
    reference = [0.0, 0.0, 0.0]
    variant = [1.0, 1.0, 1.0]
    assert metrics.area_delta(reference, variant, [0.0, 1.0, 2.0]) == pytest.approx(2.0)
    assert metrics.area_delta(variant, reference, [0.0, 1.0, 2.0]) == pytest.approx(-2.0)


def test_peak_shift_measures_timing_change():
    axis = [0.0, 1.0, 2.0, 3.0]
    reference = [0.0, 5.0, 0.0, 0.0]
    variant = [0.0, 0.0, 5.0, 0.0]
    assert metrics.peak_shift(axis, reference, variant) == pytest.approx(1.0)


def test_correlation_and_distribution_distance():
    assert metrics.correlation([1.0, 2.0, 3.0], [2.0, 4.0, 6.0]) == pytest.approx(1.0)
    assert metrics.distribution_distance([1.0, 2.0], [1.0, 2.0]) == pytest.approx(0.0)
    assert np.isnan(metrics.correlation([1.0, 1.0], [1.0, 1.0]))


def test_shape_mismatch_raises():
    with pytest.raises(ValueError):
        metrics.mean_absolute_error([0.0, 1.0], [0.0])
