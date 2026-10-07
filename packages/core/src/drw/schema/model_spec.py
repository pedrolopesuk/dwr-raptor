"""Structured, inspectable model specifications (the model-generation path).

DRW must eventually *construct* computational models, not only consume ones a user
already registered. The unsafe shortcut - an LLM writing and executing arbitrary
Python - is explicitly rejected. Instead a model is described as a **structured
specification**: variables, parameters, units, symbolic relationships,
assumptions, initial/boundary conditions, provenance and a content identity.

A specification is *declarative*: the relationships are stored as symbolic text
and are never executed here. :func:`specification_to_schema` projects the
specification onto the existing :class:`~drw.schema.model.ModelSchema` (the same
contract the engine already consumes), which is the clean extension point for a
future controlled compiler. Compilation to an executable artifact is deliberately
staged: :func:`compilation_supported` reports what is and is not available.
"""

from __future__ import annotations

import math
import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from drw.schema.model import ModelSchema, OutputSpec, ParameterSpec
from drw.schema.result import Diagnostic
from drw.schema.serialization import content_hash
from drw.schema.units import UnitError, resolve_unit

__all__ = [
    "MODEL_SPEC_SCHEMA_VERSION",
    "ModelSpecParameter",
    "ModelSpecProvenance",
    "ModelSpecRelationship",
    "ModelSpecVariable",
    "ModelSpecification",
    "compilation_supported",
    "specification_to_schema",
    "validate_model_specification",
]

MODEL_SPEC_SCHEMA_VERSION = "1.0.0"

_SPEC_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_.\-]*$")

#: How the (future) compiler would execute the model. Recorded, never guessed.
ModelSpecKind = Literal["ode", "algebraic", "discrete"]


class ModelSpecParameter(BaseModel):
    """A numeric input/control parameter of a proposed model."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    unit: str = "dimensionless"
    description: str = ""
    nominal: float | None = None
    lower: float | None = None
    upper: float | None = None
    role: Literal["input", "control"] = "input"
    differentiable: bool = False

    @field_validator("name")
    @classmethod
    def _check_name(cls, value: str) -> str:
        if not _SPEC_IDENTIFIER.match(value):
            raise ValueError(f"parameter name {value!r} is not a valid identifier")
        return value

    @field_validator("unit")
    @classmethod
    def _check_unit(cls, value: str) -> str:
        try:
            resolve_unit(value)
        except UnitError as exc:  # pragma: no cover - defensive
            raise ValueError(str(exc)) from exc
        return value

    def has_bounds(self) -> bool:
        return self.lower is not None and self.upper is not None


class ModelSpecVariable(BaseModel):
    """A state variable (initial condition) or a derived output of the model."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    kind: Literal["state", "derived"] = "state"
    unit: str = "dimensionless"
    description: str = ""
    initial: float | None = None

    @field_validator("name")
    @classmethod
    def _check_name(cls, value: str) -> str:
        if not _SPEC_IDENTIFIER.match(value):
            raise ValueError(f"variable name {value!r} is not a valid identifier")
        return value

    @field_validator("unit")
    @classmethod
    def _check_unit(cls, value: str) -> str:
        try:
            resolve_unit(value)
        except UnitError as exc:  # pragma: no cover - defensive
            raise ValueError(str(exc)) from exc
        return value


class ModelSpecRelationship(BaseModel):
    """A symbolic relationship (equation / rate law).

    For an ODE specification, a relationship with ``rate_of`` set declares the
    time-derivative of a state variable (``d<rate_of>/dt = expression``). A
    relationship without ``rate_of`` is a plain symbolic relation. Neither is ever
    executed here; the bounded compiler in :mod:`drw.model_compiler` consumes them.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    expression: str
    description: str = ""
    depends_on: tuple[str, ...] = ()
    rate_of: str | None = None

    @field_validator("name")
    @classmethod
    def _check_name(cls, value: str) -> str:
        if not _SPEC_IDENTIFIER.match(value):
            raise ValueError(f"relationship name {value!r} is not a valid identifier")
        return value

    @field_validator("rate_of")
    @classmethod
    def _check_rate_of(cls, value: str | None) -> str | None:
        if value is not None and not _SPEC_IDENTIFIER.match(value):
            raise ValueError(f"rate_of {value!r} is not a valid identifier")
        return value

    @field_validator("expression")
    @classmethod
    def _check_expression(cls, value: str) -> str:
        if not value or not value.strip():
            raise ValueError(f"relationship {value!r} has an empty expression")
        return value


class ModelSpecProvenance(BaseModel):
    """Where a model specification came from."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    author: str = "SI"
    generated_by: str = "si"
    source_reference: str = ""
    created_at: str
    notes: str = ""


class ModelSpecification(BaseModel):
    """A proposed, inspectable, domain-neutral model specification."""

    model_config = ConfigDict(extra="forbid")

    schema_version: str = MODEL_SPEC_SCHEMA_VERSION
    model_id: str
    version: str = "0.1.0"
    description: str = ""
    domain: str = "general"
    kind: ModelSpecKind = "ode"
    parameters: tuple[ModelSpecParameter, ...] = ()
    variables: tuple[ModelSpecVariable, ...] = ()
    relationships: tuple[ModelSpecRelationship, ...] = ()
    assumptions: tuple[str, ...] = ()
    initial_conditions: dict[str, float] = Field(default_factory=dict)
    boundary_conditions: tuple[str, ...] = ()
    execution: dict[str, Any] = Field(default_factory=dict)
    provenance: ModelSpecProvenance

    @field_validator("model_id")
    @classmethod
    def _check_model_id(cls, value: str) -> str:
        if not _SPEC_IDENTIFIER.match(value):
            raise ValueError(f"model_id {value!r} is not a valid identifier")
        return value

    def content_hash(self) -> str:
        return content_hash(self)

    def spec_id(self) -> str:
        return "mspec-" + self.content_hash()[:12]


def validate_model_specification(spec: ModelSpecification) -> tuple[Diagnostic, ...]:
    """Validate a specification structurally. Returns diagnostics (errors block use)."""
    diagnostics: list[Diagnostic] = []

    def error(code: str, message: str) -> None:
        diagnostics.append(Diagnostic(level="error", code=code, message=message))

    def warn(code: str, message: str) -> None:
        diagnostics.append(Diagnostic(level="warning", code=code, message=message))

    if not spec.parameters:
        error(
            "no_parameters", "a model specification must declare at least one parameter"
        )
    if not spec.variables:
        error(
            "no_variables", "a model specification must declare at least one variable"
        )

    all_names = [p.name for p in spec.parameters] + [v.name for v in spec.variables]
    duplicates = sorted({name for name in all_names if all_names.count(name) > 1})
    if duplicates:
        error("duplicate_names", f"names declared more than once: {duplicates}")

    states = {v.name for v in spec.variables if v.kind == "state"}
    declared = set(all_names)

    for name, value in spec.initial_conditions.items():
        if name not in declared:
            error(
                "unknown_initial_condition",
                f"initial condition names unknown symbol {name!r}",
            )
        elif name not in states:
            error(
                "initial_condition_not_state",
                f"initial condition {name!r} is not a state variable",
            )
        elif not isinstance(value, (int, float)) or isinstance(value, bool):
            error(
                "invalid_initial_condition",
                f"initial condition {name!r} must be a number",
            )
        elif not math.isfinite(float(value)):
            error(
                "non_finite_initial_condition",
                f"initial condition {name!r} is not finite",
            )

    for variable in spec.variables:
        if (
            variable.kind == "state"
            and variable.name not in spec.initial_conditions
            and variable.initial is None
        ):
            error(
                "missing_initial_condition",
                f"state variable {variable.name!r} has no initial condition",
            )

    for parameter in spec.parameters:
        if parameter.lower is not None or parameter.upper is not None:
            if parameter.lower is None or parameter.upper is None:
                error(
                    "incomplete_bounds",
                    f"parameter {parameter.name!r} must declare both lower and upper, or neither",
                )
            elif parameter.lower >= parameter.upper:
                error(
                    "invalid_bounds",
                    f"parameter {parameter.name!r} requires lower < upper",
                )
            elif parameter.nominal is not None and not (
                parameter.lower <= parameter.nominal <= parameter.upper
            ):
                error(
                    "nominal_out_of_bounds",
                    f"parameter {parameter.name!r} nominal lies outside its bounds",
                )

    for relationship in spec.relationships:
        if not relationship.depends_on:
            warn(
                "relationship_without_dependencies",
                f"relationship {relationship.name!r} declares no dependencies",
            )
        for dependency in relationship.depends_on:
            if dependency not in declared:
                error(
                    "unknown_relationship_dependency",
                    f"relationship {relationship.name!r} depends on unknown symbol {dependency!r}",
                )
        if relationship.rate_of is not None and relationship.rate_of not in states:
            error(
                "unknown_rate_target",
                f"relationship {relationship.name!r} declares rate_of "
                f"{relationship.rate_of!r}, which is not a state variable",
            )

    if spec.kind == "ode" and not any(r.rate_of for r in spec.relationships):
        warn(
            "no_rate_equations",
            "an ODE specification declares no rate equations (relationships with 'rate_of')",
        )

    return tuple(diagnostics)


def compilation_supported() -> tuple[bool, str]:
    """Whether DRW can compile a specification into an executable model.

    Compilation is **bounded**: :mod:`drw.model_compiler` compiles an ``ode``
    specification whose state variables each declare exactly one rate equation
    (``rate_of``) written in a restricted arithmetic/function grammar. It never
    executes LLM-authored Python. Anything outside that subset fails closed.
    """
    return (
        True,
        "The bounded ODE compiler (drw.model_compiler) is available: it compiles an "
        "'ode' specification with one rate equation per state variable, written in a "
        "restricted arithmetic/function grammar. Other model kinds and constructs "
        "fail closed.",
    )


def specification_to_schema(spec: ModelSpecification) -> ModelSchema:
    """Project a specification onto the engine's declared :class:`ModelSchema`.

    This is *declarative*: it produces the parameters/outputs the engine would
    consume, so the model can be inspected everywhere a registered model is. The
    relationships are **not** compiled into executable code.
    """
    parameters: list[ParameterSpec] = []
    for variable in spec.variables:
        if variable.kind != "state":
            continue
        parameters.append(
            ParameterSpec(
                name=variable.name,
                type="float",
                unit=variable.unit,
                description=variable.description,
                nominal=spec.initial_conditions.get(variable.name, variable.initial),
                role="state",
            )
        )
    for parameter in spec.parameters:
        parameters.append(
            ParameterSpec(
                name=parameter.name,
                type="float",
                unit=parameter.unit,
                description=parameter.description,
                nominal=parameter.nominal,
                lower=parameter.lower,
                upper=parameter.upper,
                role=parameter.role,
                differentiable=parameter.differentiable,
            )
        )

    outputs: list[OutputSpec] = []
    for variable in spec.variables:
        if variable.kind == "state":
            outputs.append(
                OutputSpec(
                    name=variable.name,
                    kind="timeseries",
                    unit=variable.unit,
                    description=variable.description,
                    axis_unit="s",
                )
            )
    for relationship in spec.relationships:
        if relationship.rate_of is not None:
            continue  # a rate equation is execution semantics, not a model output
        outputs.append(
            OutputSpec(
                name=relationship.name,
                kind="scalar",
                unit="dimensionless",
                description=relationship.description or relationship.expression,
            )
        )
    if not outputs:
        outputs.append(OutputSpec(name="value", kind="scalar", unit="dimensionless"))

    return ModelSchema(
        model_id=spec.model_id,
        version=spec.version,
        description=spec.description,
        runtime="specification (not compiled)",
        parameters=tuple(parameters),
        outputs=tuple(outputs),
        metadata={
            "kind": spec.kind,
            "domain": spec.domain,
            "compiled": False,
            "spec_hash": spec.content_hash(),
        },
    )
