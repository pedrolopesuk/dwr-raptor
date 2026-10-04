"""Unit tests for the minimal unit system."""

from __future__ import annotations

import pytest

from drw.schema.units import UnitError, convert, register_unit, resolve_unit, units_compatible

pytestmark = pytest.mark.unit


def test_known_unit_resolves_to_dimension():
    assert resolve_unit("s").dimension == "time"
    assert resolve_unit("kg").dimension == "mass"
    assert resolve_unit("dimensionless").dimension == "dimensionless"


def test_opaque_units_are_distinct():
    assert resolve_unit("prey").dimension == "@prey"
    assert units_compatible("prey", "prey")
    assert not units_compatible("prey", "predator")


def test_convert_within_dimension():
    assert convert(1.0, "min", "s") == pytest.approx(60.0)
    assert convert(1000.0, "m", "km") == pytest.approx(1.0)


def test_convert_incompatible_raises():
    with pytest.raises(UnitError):
        convert(1.0, "s", "m")


def test_empty_symbol_raises():
    with pytest.raises(UnitError):
        resolve_unit("   ")


def test_register_custom_unit():
    register_unit("furlong", "length", 201.168)
    assert convert(1.0, "furlong", "m") == pytest.approx(201.168)


def test_register_rejects_non_positive_scale():
    with pytest.raises(UnitError):
        register_unit("bogus", "length", 0.0)
