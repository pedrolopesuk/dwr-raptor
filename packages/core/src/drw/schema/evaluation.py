"""Observation <-> model evaluation contract (M12A).

M12A answers a single question: *given an already-produced deterministic model
run and a scientific Dataset, how well does the model reproduce the
observations?* It is **execution-free**: it never launches the ``Runner``, never
changes parameters and performs no inference. M12B (calibration) will execute the
runner and repeatedly call this evaluator.

The contract here defines:

* :class:`EvaluationConfig` - explicit comparison behaviour (metrics, residual
  modes, alignment, tolerance, datetime origin, degrees of freedom).
* :class:`EvaluationResult` (and the per-pair/point pieces) - a strict,
  content-addressed, in-memory analysis artifact.

Nothing is persisted in M12A; ``EvaluationResult`` is on-demand only. Any
scientifically invalid comparison fails closed (``ok=False``, no metrics): no
fabricated values, no silent unit conversion, no silent normalization, no
fabricated uncertainty and no silent exclusion of observations.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from drw.schema.model import ModelRef
from drw.schema.observation import DatasetRef, ObservationMapping
from drw.schema.result import Diagnostic
from drw.schema.serialization import content_hash, to_plain

__all__ = [
    "CORE_METRICS",
    "EVALUATION_SCHEMA_VERSION",
    "RELATIVE_METRICS",
    "WEIGHTED_METRICS",
    "AlignedPoint",
    "AlignmentStrategyEval",
    "EvaluationConfig",
    "EvaluationExclusion",
    "EvaluationProvenance",
    "EvaluationResult",
    "MetricName",
    "PairEvaluation",
    "ResidualMode",
    "compute_evaluation_hash",
    "evaluation_identity_payload",
]

EVALUATION_SCHEMA_VERSION = "1.0.0"

MetricName = Literal[
    "mean_residual",
    "mae",
    "rmse",
    "max_abs_error",
    "relative_mae",
    "relative_rmse",
    "max_abs_relative_error",
    "weighted_rmse",
    "chi_square",
    "reduced_chi_square",
]
ResidualMode = Literal["raw", "relative", "normalized"]
AlignmentStrategyEval = Literal["exact", "interpolate"]

CORE_METRICS: tuple[str, ...] = ("mean_residual", "mae", "rmse", "max_abs_error")
RELATIVE_METRICS: tuple[str, ...] = ("relative_mae", "relative_rmse", "max_abs_relative_error")
WEIGHTED_METRICS: tuple[str, ...] = ("weighted_rmse", "chi_square", "reduced_chi_square")


def _parse_iso(value: str) -> datetime:
    text = value[:-1] + "+00:00" if value.endswith("Z") else value
    return datetime.fromisoformat(text)


class EvaluationConfig(BaseModel):
    """Explicit comparison configuration (no implicit scientific behaviour)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    metrics: tuple[MetricName, ...] = CORE_METRICS  # type: ignore[assignment]
    residual_modes: tuple[ResidualMode, ...] = ("raw",)
    alignment: AlignmentStrategyEval = "exact"
    alignment_tolerance: float = 0.0
    relative_epsilon: float = 1e-12
    time_origin: str | None = None
    degrees_of_freedom: int | None = None

    @field_validator("metrics")
    @classmethod
    def _check_metrics(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if not value:
            raise ValueError("at least one metric must be requested")
        if len(set(value)) != len(value):
            raise ValueError("metric names must be unique")
        return value

    @field_validator("residual_modes")
    @classmethod
    def _check_modes(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if not value:
            raise ValueError("at least one residual mode is required")
        if len(set(value)) != len(value):
            raise ValueError("residual modes must be unique")
        if "raw" not in value:
            raise ValueError("the 'raw' residual mode is required")
        return value

    @field_validator("alignment_tolerance")
    @classmethod
    def _check_tolerance(cls, value: float) -> float:
        if value != value or value in (float("inf"), float("-inf")) or value < 0:
            raise ValueError("alignment_tolerance must be finite and >= 0")
        return value

    @field_validator("relative_epsilon")
    @classmethod
    def _check_epsilon(cls, value: float) -> float:
        if not (value > 0) or value in (float("inf"), float("-inf")):
            raise ValueError("relative_epsilon must be finite and > 0")
        return value

    @field_validator("time_origin")
    @classmethod
    def _check_origin(cls, value: str | None) -> str | None:
        if value is None:
            return None
        try:
            _parse_iso(value)
        except ValueError as exc:
            raise ValueError(f"time_origin must be ISO-8601: {exc}") from exc
        return value

    @field_validator("degrees_of_freedom")
    @classmethod
    def _check_dof(cls, value: int | None) -> int | None:
        if value is not None and (isinstance(value, bool) or value < 1):
            raise ValueError("degrees_of_freedom must be a positive integer when supplied")
        return value

    @model_validator(mode="after")
    def _check_metric_consistency(self) -> EvaluationConfig:
        modes = set(self.residual_modes)
        requested = set(self.metrics)
        if requested & set(RELATIVE_METRICS) and "relative" not in modes:
            raise ValueError("relative metrics require the 'relative' residual mode")
        if requested & set(WEIGHTED_METRICS) and "normalized" not in modes:
            raise ValueError("weighted metrics require the 'normalized' residual mode")
        if "reduced_chi_square" in requested and self.degrees_of_freedom is None:
            raise ValueError(
                "reduced_chi_square requires an explicit degrees_of_freedom "
                "(M12A never estimates it)"
            )
        return self


class EvaluationExclusion(BaseModel):
    """One excluded observation, with an explicit reason (never silent)."""

    model_config = ConfigDict(extra="forbid")

    observation_index: int
    reason: str
    detail: str = ""


class AlignedPoint(BaseModel):
    """One usable, aligned observation/prediction pair."""

    model_config = ConfigDict(extra="forbid")

    observation_index: int
    model_index: int | None = None
    coordinate: float | None = None
    observed: float
    predicted: float
    residual: float
    relative_residual: float | None = None
    sigma: float | None = None
    normalized_residual: float | None = None


class PairEvaluation(BaseModel):
    """The evaluation of one mapping pair (observation variable -> model output)."""

    model_config = ConfigDict(extra="forbid")

    observation: str
    output: str
    kind: str  # "scalar" | "timeseries"
    unit: str
    alignment: str
    tolerance: float
    interpolated: bool
    points: list[AlignedPoint]
    exclusions: list[EvaluationExclusion]
    usable_count: int
    excluded_count: int
    exclusion_counts: dict[str, int] = Field(default_factory=dict)
    metrics: dict[str, float | None] = Field(default_factory=dict)
    diagnostics: list[Diagnostic] = Field(default_factory=list)


class EvaluationProvenance(BaseModel):
    """The exact inputs an evaluation was produced from."""

    model_config = ConfigDict(extra="forbid")

    spec_hash: str = ""
    model_hash: str = ""
    environment_hash: str = ""
    dataset_content_hash: str
    mapping_hash: str


class EvaluationResult(BaseModel):
    """A content-addressed, on-demand evaluation artifact (not persisted in M12A)."""

    model_config = ConfigDict(extra="forbid")

    eval_schema_version: str = EVALUATION_SCHEMA_VERSION
    evaluation_hash: str
    dataset: DatasetRef
    experiment_id: str
    run_id: str
    attempt: int = 1
    model_ref: ModelRef
    model_hash: str = ""
    parameter_snapshot: dict[str, Any] = Field(default_factory=dict)
    mapping: ObservationMapping
    mapping_hash: str
    config: EvaluationConfig
    pairs: list[PairEvaluation] = Field(default_factory=list)
    total_usable: int = 0
    total_excluded: int = 0
    ok: bool
    diagnostics: list[Diagnostic] = Field(default_factory=list)
    provenance: EvaluationProvenance

    @property
    def metric_names(self) -> tuple[str, ...]:
        return tuple(self.config.metrics)


def evaluation_identity_payload(result: EvaluationResult) -> dict[str, Any]:
    """The canonical payload that defines the evaluation hash (excludes the hash)."""
    return {
        "eval_schema_version": result.eval_schema_version,
        "dataset": to_plain(result.dataset),
        "experiment_id": result.experiment_id,
        "run_id": result.run_id,
        "attempt": result.attempt,
        "model_ref": to_plain(result.model_ref),
        "model_hash": result.model_hash,
        "parameter_snapshot": to_plain(result.parameter_snapshot),
        "mapping": to_plain(result.mapping),
        "mapping_hash": result.mapping_hash,
        "config": to_plain(result.config),
        "pairs": to_plain(result.pairs),
        "total_usable": result.total_usable,
        "total_excluded": result.total_excluded,
        "ok": result.ok,
        "diagnostics": to_plain(result.diagnostics),
        "provenance": to_plain(result.provenance),
    }


def compute_evaluation_hash(result: EvaluationResult) -> str:
    """Recompute the content hash of an evaluation result (reuses canonical hashing)."""
    return content_hash(evaluation_identity_payload(result))
