"""Simulation specifications and the synthetic-vs-real observation boundary.

A **real observation** is empirical evidence about the world. A **simulated
observation** is a consequence of a model plus assumptions, parameters and a
scenario. DRW must never blur the two. This module defines the simulation request
contract and - crucially - the helpers that *mark* and *detect* synthetic data so
no downstream analysis can silently treat a model's output as evidence.

The full simulate→dataset pipeline is staged (see :func:`simulation_supported`);
what is implemented here is the contract, the deterministic identity, the
provenance marker and the fail-closed guard.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from drw.schema.model import ModelRef
from drw.schema.observation import (
    DatasetRef,
    ObservationSet,
    PreprocessStep,
    Provenance,
)
from drw.schema.result import Diagnostic
from drw.schema.serialization import content_hash

__all__ = [
    "SIMULATION_SCHEMA_VERSION",
    "SimulationConfig",
    "SimulationProvenance",
    "SimulationResult",
    "SimulationSpec",
    "SimulationUnsupported",
    "SyntheticObservationError",
    "assert_empirical",
    "is_synthetic",
    "simulation_supported",
    "synthetic_provenance",
]

SIMULATION_SCHEMA_VERSION = "1.0.0"


class SimulationUnsupported(RuntimeError):
    """Raised when a simulation is requested but the pipeline cannot run it."""


class SyntheticObservationError(ValueError):
    """Raised when synthetic data would be used as if it were empirical."""


class SimulationConfig(BaseModel):
    """Deterministic execution configuration for a simulation."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    t_span: tuple[float, float] = (0.0, 10.0)
    n_points: int = 200
    solver: Literal["auto", "explicit", "stiff"] = "auto"
    seed: int | None = None
    timeout_s: float = 60.0

    @field_validator("n_points")
    @classmethod
    def _check_points(cls, value: int) -> int:
        if value < 2:
            raise ValueError("n_points must be >= 2")
        return value

    @field_validator("t_span")
    @classmethod
    def _check_span(cls, value: tuple[float, float]) -> tuple[float, float]:
        if value[1] <= value[0]:
            raise ValueError("t_span must be increasing")
        return value


class SimulationProvenance(BaseModel):
    """Everything needed to reproduce a simulation and mark its output synthetic."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    source_kind: Literal["synthetic"] = "synthetic"
    source_model_id: str
    source_model_hash: str
    parameters: dict[str, float] = Field(default_factory=dict)
    initial_conditions: dict[str, float] = Field(default_factory=dict)
    scenario: str = ""
    seed: int | None = None
    generated_by: str = "drw.simulation"
    generated_at: str
    notes: str = ""


class SimulationSpec(BaseModel):
    """A reproducible request to simulate observations from a model."""

    model_config = ConfigDict(extra="forbid")

    schema_version: str = SIMULATION_SCHEMA_VERSION
    model_ref: ModelRef
    model_hash: str
    parameters: dict[str, float] = Field(default_factory=dict)
    initial_conditions: dict[str, float] = Field(default_factory=dict)
    scenario: str = ""
    boundary_conditions: tuple[str, ...] = ()
    config: SimulationConfig = Field(default_factory=SimulationConfig)
    outputs: tuple[str, ...] = ()
    notes: str = ""

    def content_hash(self) -> str:
        return content_hash(self)


class SimulationResult(BaseModel):
    """The outcome of a simulation: synthetic by construction."""

    model_config = ConfigDict(extra="forbid")

    schema_version: str = SIMULATION_SCHEMA_VERSION
    simulation_hash: str
    spec: SimulationSpec
    run_id: str | None = None
    observation_set: ObservationSet | None = None
    dataset_ref: DatasetRef | None = None
    provenance: SimulationProvenance
    synthetic: Literal[True] = True
    diagnostics: tuple[Diagnostic, ...] = ()
    note: str = (
        "These values are consequences of a model and its assumptions, not "
        "empirical evidence about the world."
    )


def simulation_supported() -> tuple[bool, str]:
    """Whether DRW can currently run a simulation end to end.

    Implemented (M14): the compiled/specified model is executed through the existing
    :class:`~drw.execution.runner.Runner` and its outputs are stored as an explicitly
    synthetic dataset. Only the model families the engine can execute are supported;
    anything else fails closed.
    """
    return (
        True,
        "Simulation is available: a model is executed through the Runner and its "
        "outputs are stored as an explicitly synthetic dataset.",
    )


def synthetic_provenance(
    *,
    source_model_id: str,
    source_model_hash: str,
    imported_at: str,
    parameters: dict[str, float] | None = None,
    seed: int | None = None,
    notes: str = "",
    scenario: str = "",
    simulation_hash: str = "",
    dataset_version: str = "synthetic-1.0.0",
    preprocessing: tuple[PreprocessStep, ...] = (),
) -> Provenance:
    """Build a dataset provenance that unambiguously marks the data synthetic.

    ``source_kind='synthetic'`` is the M11 contract for exactly this case; the
    provenance chain (source model + hash, parameter values, scenario, seed and the
    simulation hash) is recorded so a reader can see exactly what produced the data.
    """
    detail = (
        notes or "Generated by simulation from a model; not an empirical observation."
    )
    if parameters:
        pairs = ", ".join(
            f"{name}={value:g}" for name, value in sorted(parameters.items())
        )
        detail = f"{detail} parameters: {pairs}."
    if scenario:
        detail = f"{detail} scenario: {scenario}."
    if seed is not None:
        detail = f"{detail} seed={seed}."
    if simulation_hash:
        detail = f"{detail} simulation={simulation_hash[:12]}."
    steps = preprocessing
    if not steps:
        steps = (
            PreprocessStep(
                operation="simulation",
                version=dataset_version,
                params={
                    "source_model_id": source_model_id,
                    "source_model_hash": source_model_hash,
                    "simulation_hash": simulation_hash,
                    "scenario": scenario,
                    "seed": seed,
                    "parameters": dict(parameters or {}),
                },
            ),
        )
    return Provenance(
        source_kind="synthetic",
        imported_at=imported_at,
        dataset_version=dataset_version,
        source_id=source_model_id,
        source_sha256=source_model_hash if len(source_model_hash) == 64 else None,
        preprocessing=steps,
        notes=detail,
    )


def is_synthetic(provenance: Provenance | None) -> bool:
    """Whether a provenance marks synthetic (non-empirical) data."""
    return provenance is not None and provenance.source_kind == "synthetic"


def assert_empirical(provenance: Provenance | None, *, what: str) -> None:
    """Fail closed when synthetic data would be used as empirical evidence.

    Evaluation, calibration and validation are claims about the world; they must
    be based on real observations. Callers that genuinely want to study a model
    against its own output must opt in explicitly elsewhere, never by accident.
    """
    if is_synthetic(provenance):
        raise SyntheticObservationError(
            f"{what} requires empirical observations, but the dataset is marked "
            "synthetic. Synthetic data is a consequence of a model, not evidence "
            "about the world."
        )
