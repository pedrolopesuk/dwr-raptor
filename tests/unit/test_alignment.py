"""Unit tests for time-series alignment."""

from __future__ import annotations

import numpy as np
import pytest

from drw.numerics.alignment import AlignmentError, align

pytestmark = pytest.mark.unit


def test_exact_alignment_returns_inputs():
    result = align([0, 1, 2], [0, 1, 2], [0, 1, 2], [0, 1, 2])
    assert result.interpolated is False
    assert result.strategy == "exact"
    assert np.allclose(result.variant, [0, 1, 2])


def test_exact_alignment_rejects_different_axes():
    with pytest.raises(AlignmentError):
        align([0, 1, 2], [0, 1, 2], [0, 1], [0, 1])


def test_interpolate_matches_linear_function_and_discloses():
    result = align([0, 1, 2], [0, 2, 4], [0, 2], [0, 4], strategy="interpolate")
    assert result.interpolated is True
    assert np.allclose(result.variant, [0, 2, 4])
    assert result.diagnostics[0].code == "interpolated_alignment"


def test_resample_onto_common_axis():
    result = align([0, 1, 2], [0, 1, 2], [0, 2], [0, 2], strategy="resample", common_axis=[0, 1, 2])
    assert result.strategy == "resample"
    assert np.allclose(result.variant, [0, 1, 2])


def test_unknown_strategy_raises():
    with pytest.raises(AlignmentError):
        align([0, 1], [0, 1], [0, 1], [0, 1], strategy="nope")  # type: ignore[arg-type]
