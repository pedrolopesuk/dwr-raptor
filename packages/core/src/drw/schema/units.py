"""Minimal, explicit unit system for the DRW MVP.

The specification's scientific validity rules require that incompatible units
are never compared without an explicit conversion. This module provides just
enough of a dimensional model to enforce that rule while keeping serialization
deterministic.

Known symbols map to a physical dimension. Unknown symbols become *opaque*
units whose dimension is the symbol itself (for example ``"prey"`` or
``"predator"`` in an ecological model); two opaque units are compatible only
when their symbols match exactly.

Full dimensional analysis - compound dimensions (``kg*m/s**2``), SI prefixes and
parsing - is deliberately out of scope for the MVP and is deferred to an
optional ``pint``-backed adapter. See ``docs/architecture/ADR-0003-units.md``.
"""

from __future__ import annotations

from dataclasses import dataclass

__all__ = [
    "DIMENSIONLESS",
    "Unit",
    "UnitError",
    "convert",
    "register_unit",
    "resolve_unit",
    "units_compatible",
]

DIMENSIONLESS = "dimensionless"


class UnitError(ValueError):
    """Raised when a unit symbol cannot be interpreted or converted."""


@dataclass(frozen=True, slots=True)
class Unit:
    """A unit of measurement with a physical dimension and a base scale."""

    symbol: str
    dimension: str
    scale: float = 1.0

    def is_compatible(self, other: Unit) -> bool:
        """Return ``True`` when ``other`` can be converted to this unit."""
        return self.dimension == other.dimension

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.symbol


_REGISTRY: dict[str, Unit] = {}


def register_unit(symbol: str, dimension: str, scale: float = 1.0) -> Unit:
    """Register (or replace) a named unit.

    ``scale`` is the size of one unit expressed in the base unit of its
    dimension (for example ``min`` -> ``60`` seconds).
    """
    if not symbol or not isinstance(symbol, str):
        raise UnitError("unit symbol must be a non-empty string")
    if not isinstance(dimension, str) or not dimension:
        raise UnitError(f"dimension must be a non-empty string for {symbol!r}")
    if scale <= 0:
        raise UnitError(f"unit scale must be positive, got {scale!r} for {symbol!r}")
    unit = Unit(symbol=symbol, dimension=dimension, scale=float(scale))
    _REGISTRY[symbol] = unit
    return unit


_BUILTIN_UNITS: tuple[tuple[str, str, float], ...] = (
    (DIMENSIONLESS, DIMENSIONLESS, 1.0),
    ("%", DIMENSIONLESS, 0.01),
    ("s", "time", 1.0),
    ("ms", "time", 1e-3),
    ("min", "time", 60.0),
    ("h", "time", 3600.0),
    ("day", "time", 86400.0),
    ("1/s", "frequency", 1.0),
    ("Hz", "frequency", 1.0),
    ("m", "length", 1.0),
    ("cm", "length", 0.01),
    ("km", "length", 1000.0),
    ("kg", "mass", 1.0),
    ("g", "mass", 1e-3),
    ("K", "temperature", 1.0),
    ("rad", "angle", 1.0),
    ("count", "amount", 1.0),
)
for _symbol, _dimension, _scale in _BUILTIN_UNITS:
    register_unit(_symbol, _dimension, _scale)


def resolve_unit(symbol: str) -> Unit:
    """Resolve a unit symbol to a :class:`Unit` (opaque when unknown)."""
    if not isinstance(symbol, str):
        raise UnitError(f"unit symbol must be a string, got {type(symbol).__name__}")
    text = symbol.strip()
    if not text:
        raise UnitError("unit symbol must not be empty")
    known = _REGISTRY.get(text)
    if known is not None:
        return known
    return Unit(symbol=text, dimension=f"@{text}", scale=1.0)


def units_compatible(a: str | Unit, b: str | Unit) -> bool:
    """Return ``True`` when two unit symbols share the same dimension."""
    unit_a = resolve_unit(a) if isinstance(a, str) else a
    unit_b = resolve_unit(b) if isinstance(b, str) else b
    return unit_a.is_compatible(unit_b)


def convert(value: float, from_unit: str | Unit, to_unit: str | Unit) -> float:
    """Convert ``value`` between two compatible units."""
    source = resolve_unit(from_unit) if isinstance(from_unit, str) else from_unit
    target = resolve_unit(to_unit) if isinstance(to_unit, str) else to_unit
    if not source.is_compatible(target):
        raise UnitError(
            f"cannot convert {source.symbol!r} ({source.dimension}) "
            f"to {target.symbol!r} ({target.dimension})"
        )
    return float(value) * source.scale / target.scale
