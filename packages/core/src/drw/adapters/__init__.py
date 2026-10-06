"""Observation import adapters (M11C).

The internal scientific data model never knows about file formats. An *adapter*
turns a concrete source (CSV today; Parquet/FITS/HDF5/NetCDF later) into the
M11A contract, and nothing else in DRW may depend on a format.

Every adapter exposes a stable ``id``/``version`` and the operations
``can_handle`` (cheap format check), ``inspect`` (advisory, non-persistent) and
``read`` (parse + build a validated :class:`~drw.schema.observation.Dataset`).
Detection is advisory: an adapter may *suggest* roles/units, but the caller must
supply an explicit configuration - science is never inferred from file contents.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from drw.schema.observation import Dataset

__all__ = [
    "ObservationAdapter",
    "adapter_for",
    "get_adapter",
    "list_adapters",
    "register_adapter",
]


@runtime_checkable
class ObservationAdapter(Protocol):
    """Structural type for an observation import adapter."""

    id: str
    version: str

    def can_handle(self, source: str | Path) -> bool:
        """Return ``True`` if this adapter can probably read ``source``."""

    def inspect(self, source: str | Path, **options: Any) -> Any:
        """Return an advisory, non-persistent inspection of ``source``."""

    def read(self, source: str | Path, config: Any) -> Dataset:
        """Parse ``source`` with ``config`` into a validated dataset."""


_REGISTRY: dict[str, ObservationAdapter] = {}


def register_adapter(adapter: ObservationAdapter) -> None:
    """Register an adapter under its ``id`` (replacing any existing one)."""
    if not getattr(adapter, "id", None) or not getattr(adapter, "version", None):
        raise ValueError("an observation adapter must declare a non-empty id and version")
    _REGISTRY[adapter.id] = adapter


def get_adapter(adapter_id: str) -> ObservationAdapter:
    """Return the adapter registered under ``adapter_id`` or raise ``KeyError``."""
    try:
        return _REGISTRY[adapter_id]
    except KeyError:
        raise KeyError(f"unknown observation adapter {adapter_id!r}") from None


def list_adapters() -> list[dict[str, str]]:
    """Return the registered adapters (id + version), deterministically ordered."""
    return [
        {"id": adapter.id, "version": adapter.version}
        for adapter in sorted(_REGISTRY.values(), key=lambda item: item.id)
    ]


def adapter_for(source: str | Path) -> ObservationAdapter | None:
    """Return the first registered adapter that claims ``source``, else ``None``."""
    for adapter in _REGISTRY.values():
        if adapter.can_handle(source):
            return adapter
    return None


# Register the built-in adapters (CSV is the first and only one in M11C).
from drw.adapters import csv_adapter as _csv_adapter  # noqa: E402,F401
