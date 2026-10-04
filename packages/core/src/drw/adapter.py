"""The model adapter contract (specification section 10.1).

A *model adapter* is anything that can declare a :class:`ModelSchema`, validate
a set of inputs, and execute deterministically. The platform depends only on
this protocol, never on a concrete model implementation.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Protocol, runtime_checkable

from drw.execution.context import RunContext
from drw.schema.model import ModelSchema
from drw.schema.result import ModelResult, ValidationReport

__all__ = ["ModelAdapter"]


@runtime_checkable
class ModelAdapter(Protocol):
    """Structural type implemented by every scientific model adapter."""

    def describe(self) -> ModelSchema:
        """Return the declared contract of the model."""
        ...

    def validate(self, inputs: Mapping[str, Any]) -> ValidationReport:
        """Check ``inputs`` against the schema without executing the model."""
        ...

    def run(self, inputs: Mapping[str, Any], context: RunContext) -> ModelResult:
        """Execute the model and return normalized outputs."""
        ...
