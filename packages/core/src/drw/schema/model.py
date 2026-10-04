"""Typed scientific model contract (``ModelSchema``).

A model exposes a small, explicit interface: it declares the parameters it
accepts (with units, bounds, role and differentiability metadata) and the
outputs it produces. The platform never treats a model as an opaque black box.

See specification sections 4.2 ("Typed scientific model contract") and 10.1
("Model adapter contract").
"""

from __future__ import annotations

import math
import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from drw.schema.units import UnitError, resolve_unit

__all__ = [
    "MODEL_SCHEMA_VERSION",
    "ModelRef",
    "ModelSchema",
    "OutputKind",
    "OutputSpec",
    "ParamType",
    "ParameterSpec",
    "Role",
    "ScalarValue",
]

MODEL_SCHEMA_VERSION = "1.0.0"

_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_.\-]*$")

ParamType = Literal["float", "int", "bool", "categorical"]
Role = Literal["input", "state", "control"]
OutputKind = Literal["scalar", "vector", "timeseries", "matrix", "categorical"]

ScalarValue = float | int | bool | str

_NUMERIC_TYPES = ("float", "int")


def _validate_unit(symbol: str) -> str:
    try:
        resolve_unit(symbol)
    except UnitError as exc:  # pragma: no cover - defensive
        raise ValueError(str(exc)) from exc
    return symbol


class ParameterSpec(BaseModel):
    """A single parameter accepted by a model.

    ``nominal`` is the default/baseline value. ``lower``/``upper`` bound numeric
    parameters and are required to be varied across a range. ``role`` records
    whether the parameter is an ordinary input, a state variable (an initial
    condition) or a control.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    type: ParamType
    unit: str = "dimensionless"
    description: str = ""
    nominal: ScalarValue | None = None
    lower: float | None = None
    upper: float | None = None
    options: tuple[str, ...] = ()
    role: Role = "input"
    differentiable: bool = False

    @field_validator("name")
    @classmethod
    def _check_name(cls, value: str) -> str:
        if not _IDENTIFIER.match(value):
            raise ValueError(
                f"parameter name {value!r} must start with a letter/underscore and "
                "contain only letters, digits, '_', '.', '-'"
            )
        return value

    @field_validator("unit")
    @classmethod
    def _check_unit(cls, value: str) -> str:
        return _validate_unit(value)

    @model_validator(mode="after")
    def _check_consistency(self) -> ParameterSpec:
        if self.type == "categorical":
            if not self.options:
                raise ValueError(f"categorical parameter {self.name!r} requires options")
            if self.nominal is not None and str(self.nominal) not in self.options:
                raise ValueError(
                    f"nominal {self.nominal!r} for {self.name!r} is not one of {self.options}"
                )
            if self.lower is not None or self.upper is not None:
                raise ValueError(f"categorical parameter {self.name!r} cannot have bounds")
        if self.type == "bool":
            if self.lower is not None or self.upper is not None:
                raise ValueError(f"boolean parameter {self.name!r} cannot have bounds")
            if self.nominal is not None and not isinstance(self.nominal, bool):
                raise ValueError(f"boolean parameter {self.name!r} has non-boolean nominal")
        if self.type in _NUMERIC_TYPES:
            for label, bound in (("lower", self.lower), ("upper", self.upper)):
                if bound is not None and not math.isfinite(bound):
                    raise ValueError(
                        f"parameter {self.name!r} {label} bound must be finite, got {bound!r}"
                    )
            if self.lower is not None and self.upper is not None and self.lower >= self.upper:
                raise ValueError(
                    f"parameter {self.name!r} requires lower < upper "
                    f"(got {self.lower} >= {self.upper})"
                )
            if self.nominal is not None and not isinstance(self.nominal, bool):
                nominal = float(self.nominal)
                if not math.isfinite(nominal):
                    raise ValueError(
                        f"parameter {self.name!r} nominal must be finite, got {nominal!r}"
                    )
                if self.lower is not None and nominal < self.lower:
                    raise ValueError(
                        f"nominal {nominal} for {self.name!r} is below lower bound {self.lower}"
                    )
                if self.upper is not None and nominal > self.upper:
                    raise ValueError(
                        f"nominal {nominal} for {self.name!r} is above upper bound {self.upper}"
                    )
        return self

    def has_bounds(self) -> bool:
        return self.lower is not None and self.upper is not None


class ModelRef(BaseModel):
    """A reference to a registered model, optionally pinned to a version."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    model_id: str
    version: str | None = None


class OutputSpec(BaseModel):
    """A named output produced by a model."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    kind: OutputKind = "timeseries"
    unit: str = "dimensionless"
    description: str = ""
    labels: tuple[str, ...] = ()
    axis_unit: str | None = None

    @field_validator("name")
    @classmethod
    def _check_name(cls, value: str) -> str:
        if not _IDENTIFIER.match(value):
            raise ValueError(f"output name {value!r} is not a valid identifier")
        return value

    @field_validator("unit")
    @classmethod
    def _check_unit(cls, value: str) -> str:
        return _validate_unit(value)

    @field_validator("axis_unit")
    @classmethod
    def _check_axis_unit(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _validate_unit(value)


class ModelSchema(BaseModel):
    """The complete declared contract of a scientific model."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: str = MODEL_SCHEMA_VERSION
    model_id: str
    version: str = "0.1.0"
    description: str = ""
    runtime: str = "python"
    parameters: tuple[ParameterSpec, ...]
    outputs: tuple[OutputSpec, ...]
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("model_id")
    @classmethod
    def _check_model_id(cls, value: str) -> str:
        if not _IDENTIFIER.match(value):
            raise ValueError(f"model_id {value!r} is not a valid identifier")
        return value

    @model_validator(mode="after")
    def _check_uniqueness(self) -> ModelSchema:
        if not self.parameters:
            raise ValueError(f"model {self.model_id!r} must declare at least one parameter")
        if not self.outputs:
            raise ValueError(f"model {self.model_id!r} must declare at least one output")
        param_names = [p.name for p in self.parameters]
        if len(set(param_names)) != len(param_names):
            duplicates = sorted({n for n in param_names if param_names.count(n) > 1})
            raise ValueError(f"duplicate parameter names in {self.model_id!r}: {duplicates}")
        output_names = [o.name for o in self.outputs]
        if len(set(output_names)) != len(output_names):
            duplicates = sorted({n for n in output_names if output_names.count(n) > 1})
            raise ValueError(f"duplicate output names in {self.model_id!r}: {duplicates}")
        return self

    # -- lookup helpers -----------------------------------------------------

    def parameter(self, name: str) -> ParameterSpec:
        """Return the parameter named ``name`` or raise :class:`KeyError`."""
        for param in self.parameters:
            if param.name == name:
                return param
        raise KeyError(f"model {self.model_id!r} has no parameter {name!r}")

    def has_parameter(self, name: str) -> bool:
        return any(param.name == name for param in self.parameters)

    def output(self, name: str) -> OutputSpec:
        for spec in self.outputs:
            if spec.name == name:
                return spec
        raise KeyError(f"model {self.model_id!r} has no output {name!r}")

    def parameter_names(self) -> tuple[str, ...]:
        return tuple(param.name for param in self.parameters)

    def state_parameters(self) -> tuple[ParameterSpec, ...]:
        """Parameters that act as initial conditions, in declaration order."""
        return tuple(p for p in self.parameters if p.role == "state")

    def control_parameters(self) -> tuple[ParameterSpec, ...]:
        return tuple(p for p in self.parameters if p.role == "control")

    def content_hash(self) -> str:
        """Deterministic hash of the declared contract."""
        from drw.schema.serialization import content_hash

        return content_hash(self)
