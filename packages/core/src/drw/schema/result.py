"""Run results, diagnostics and the run state machine.

Specification section 8.3 defines the execution lifecycle::

    DRAFT -> VALIDATED -> QUEUED -> RUNNING -> SUCCEEDED | FAILED
    SUCCEEDED -> ANALYZED -> VERIFIED -> EXPORTED

A failed run is a first-class state: retries create a *new* attempt that links
back to the original record rather than mutating history (RUN-001).
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from drw.schema.model import ModelRef, OutputKind

__all__ = [
    "TERMINAL_STATES",
    "Diagnostic",
    "ModelResult",
    "OutputValue",
    "RunRecord",
    "RunStatus",
    "ValidationReport",
    "allowed_run_transition",
    "is_terminal",
]


class RunStatus(StrEnum):
    DRAFT = "draft"
    VALIDATED = "validated"
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    ANALYZED = "analyzed"
    VERIFIED = "verified"
    EXPORTED = "exported"


#: States from which no further transition is legal.
TERMINAL_STATES: frozenset[RunStatus] = frozenset({RunStatus.FAILED, RunStatus.EXPORTED})

_TRANSITIONS: dict[RunStatus, frozenset[RunStatus]] = {
    RunStatus.DRAFT: frozenset({RunStatus.VALIDATED, RunStatus.FAILED}),
    RunStatus.VALIDATED: frozenset({RunStatus.QUEUED, RunStatus.FAILED}),
    RunStatus.QUEUED: frozenset({RunStatus.RUNNING, RunStatus.FAILED}),
    RunStatus.RUNNING: frozenset({RunStatus.SUCCEEDED, RunStatus.FAILED}),
    RunStatus.SUCCEEDED: frozenset({RunStatus.ANALYZED, RunStatus.FAILED}),
    RunStatus.ANALYZED: frozenset({RunStatus.VERIFIED, RunStatus.FAILED}),
    RunStatus.VERIFIED: frozenset({RunStatus.EXPORTED}),
    RunStatus.FAILED: frozenset(),
    RunStatus.EXPORTED: frozenset(),
}


def allowed_run_transition(current: RunStatus, target: RunStatus) -> bool:
    """Return ``True`` when ``current -> target`` is a legal lifecycle edge."""
    return target in _TRANSITIONS[current]


def is_terminal(status: RunStatus) -> bool:
    """Return ``True`` when ``status`` admits no further transitions."""
    return status in TERMINAL_STATES


class Diagnostic(BaseModel):
    """A machine-readable note attached to a validation or run."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    level: Literal["info", "warning", "error"]
    code: str
    message: str


class ValidationReport(BaseModel):
    """Outcome of validating inputs against a model schema."""

    model_config = ConfigDict(extra="forbid")

    ok: bool = True
    diagnostics: tuple[Diagnostic, ...] = ()

    @property
    def errors(self) -> tuple[Diagnostic, ...]:
        return tuple(d for d in self.diagnostics if d.level == "error")

    @property
    def warnings(self) -> tuple[Diagnostic, ...]:
        return tuple(d for d in self.diagnostics if d.level == "warning")

    def error_messages(self) -> list[str]:
        return [d.message for d in self.errors]


class OutputValue(BaseModel):
    """A normalized model output.

    Values are stored as JSON-ready primitives (list / nested list), always
    accompanied by shape, labels, units and - for series - the coordinate axis.
    """

    model_config = ConfigDict(extra="forbid")

    name: str
    kind: OutputKind
    unit: str = "dimensionless"
    values: Any
    shape: tuple[int, ...] = ()
    labels: tuple[str, ...] = ()
    axis: tuple[float, ...] | None = None
    axis_unit: str | None = None
    dtype: str = "float64"

    def aux_units(self) -> tuple[str, ...]:
        units = [self.unit]
        if self.axis_unit:
            units.append(self.axis_unit)
        return tuple(units)


class ModelResult(BaseModel):
    """The result of a single model execution."""

    model_config = ConfigDict(extra="forbid")

    status: RunStatus = RunStatus.SUCCEEDED
    outputs: dict[str, OutputValue] = Field(default_factory=dict)
    diagnostics: tuple[Diagnostic, ...] = ()

    @property
    def ok(self) -> bool:
        return self.status == RunStatus.SUCCEEDED

    def output(self, name: str) -> OutputValue:
        try:
            return self.outputs[name]
        except KeyError as exc:
            raise KeyError(f"model result has no output {name!r}") from exc

    def output_names(self) -> tuple[str, ...]:
        return tuple(self.outputs.keys())


class RunRecord(BaseModel):
    """An immutable record of one execution attempt."""

    model_config = ConfigDict(extra="forbid")

    run_id: str
    experiment_id: str
    attempt: int = 1
    parent_run_id: str | None = None
    label: str = "variant"
    status: RunStatus = RunStatus.QUEUED
    model_ref: ModelRef
    inputs: dict[str, Any] = Field(default_factory=dict)
    seed: int | None = None
    environment: dict[str, Any] = Field(default_factory=dict)
    isolation: str = "in_process"
    timed_out: bool = False
    started_at: str | None = None
    finished_at: str | None = None
    duration_s: float | None = None
    metrics: dict[str, float] = Field(default_factory=dict)
    diagnostics: tuple[Diagnostic, ...] = ()
    error: str | None = None
    result: ModelResult | None = None

    @property
    def succeeded(self) -> bool:
        return self.status == RunStatus.SUCCEEDED

    @property
    def failed(self) -> bool:
        return self.status == RunStatus.FAILED
