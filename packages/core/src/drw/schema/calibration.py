"""Calibration / parameter-estimation contract (M12B).

M12B is a thin orchestration layer around the existing engine. It never executes
a model directly (the :class:`~drw.execution.runner.Runner` is the only execution
path) and never compares outputs to data itself (M12A
:func:`drw.evaluation.evaluate_run` is the only comparison). This module defines
the *request* (``CalibrationConfig``) and the *outcome* (``CalibrationResult``)
together with their deterministic identities.

Design rules enforced here (all explicit, never silent):

* **Float parameters only**, with finite ``lower < upper`` bounds. Selected bounds
  may never widen the model's declared bounds; when the model declares none the
  selection must supply them. Integer / boolean / categorical parameters and
  log / non-linear transforms are rejected (deferred).
* **Initial values are never invented.** An explicit ``initial`` is used; else the
  model's valid ``nominal``; else it is a configuration error. A midpoint is
  never chosen silently.
* **One dataset, one mapping, one objective pair, one metric, minimize only.**
  Different metrics/units are never combined.
* **Objective metric must be present in the ``EvaluationConfig``** so the objective
  is read from M12A, never recomputed.
* ``calibration_hash`` identifies the **request** (scientific configuration only:
  no timestamps, host paths, wall-clock durations, notes or candidate outcomes).
* ``result_hash`` identifies the **outcome** (best candidate, status, history,
  provenance).

Calibration is **not** validation, **not** Bayesian inference and **not** a
statement of parameter uncertainty; convergence is not certainty. See ADR-0022.
"""

from __future__ import annotations

import math
import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from drw.schema.evaluation import (
    CORE_METRICS,
    RELATIVE_METRICS,
    WEIGHTED_METRICS,
    EvaluationConfig,
)
from drw.schema.experiment import IsolationMode, SolverChoice
from drw.schema.model import ModelRef, ModelSchema, ScalarValue
from drw.schema.observation import DatasetRef, ObservationMapping
from drw.schema.result import Diagnostic
from drw.schema.serialization import content_hash, to_plain

__all__ = [
    "CALIBRATION_SCHEMA_VERSION",
    "DEFAULT_DISCLOSURE",
    "DEFAULT_OBJECTIVE_METRIC",
    "DEFAULT_OPTIMIZER",
    "OBJECTIVE_METRICS",
    "OPTIMIZER_NAMES",
    "BudgetSpec",
    "CalibrationCandidateSummary",
    "CalibrationConfig",
    "CalibrationConfigError",
    "CalibrationObjective",
    "CalibrationProvenance",
    "CalibrationRef",
    "CalibrationResult",
    "CalibrationStatus",
    "CalibrationStopReason",
    "DataRole",
    "ExecutionTemplate",
    "FixedParameter",
    "IdentifiabilityMode",
    "ObjectiveConfig",
    "ObjectiveMetric",
    "OptimizerConfig",
    "OptimizerName",
    "ParameterScale",
    "ParameterSelection",
    "ParameterTransform",
    "ResolvedCalibration",
    "ResolvedParameter",
    "calibration_identity_payload",
    "calibration_result_payload",
    "compute_calibration_hash",
    "compute_result_hash",
    "resolve_calibration",
    "short_calibration_id",
    "validate_calibration_config",
]

CALIBRATION_SCHEMA_VERSION = "1.0.0"

_CALIBRATION_ID_PATTERN = re.compile(r"^cal-[0-9a-f]{12}$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")

ObjectiveMetric = Literal[
    "rmse",
    "mae",
    "max_abs_error",
    "mean_residual",
    "relative_rmse",
    "relative_mae",
    "max_abs_relative_error",
    "weighted_rmse",
    "chi_square",
]
OptimizerName = Literal["powell", "differential_evolution", "random_search"]
IdentifiabilityMode = Literal["off", "warn", "require"]
DataRole = Literal["calibration"]
ParameterScale = Literal["linear"]
ParameterTransform = Literal["identity"]

CalibrationStatus = Literal[
    "converged",
    "budget_exhausted",
    "not_converged",
    "failed",
    "cancelled",
    "invalid",
]
CalibrationStopReason = Literal[
    "optimizer_converged",
    "max_evaluations",
    "max_wall_seconds",
    "max_iterations",
    "max_failed",
    "cancelled",
    "optimizer_failure",
    "all_candidates_failed",
    "identifiability_required",
    "validation_error",
]

#: Metrics M12B may minimise (exactly one, never combined).
OBJECTIVE_METRICS: tuple[str, ...] = (*CORE_METRICS, *RELATIVE_METRICS, *WEIGHTED_METRICS)
#: The default objective metric (a convention, not a statistical claim).
DEFAULT_OBJECTIVE_METRIC: str = "rmse"
#: The default optimizer (bounded, derivative-free, deterministic given a seed).
DEFAULT_OPTIMIZER: str = "powell"
OPTIMIZER_NAMES: tuple[str, ...] = ("powell", "differential_evolution", "random_search")

#: Mandatory scientific disclosure attached to every result.
DEFAULT_DISCLOSURE = (
    "Calibration reports a point estimate: within the searched bounds, seed, objective, "
    "dataset/mapping and budget, the lowest objective value found was attained at the "
    "reported parameter vector. It is not a statement of parameter uncertainty, "
    "statistical significance or the true parameter values; convergence is not certainty. "
    "Calibration is not validation and does not establish model validity."
)


class CalibrationConfigError(ValueError):
    """Raised when a calibration cannot be requested or resolved against a model."""

    def __init__(self, message: str, *, diagnostics: tuple[Diagnostic, ...] = ()) -> None:
        super().__init__(message)
        self.diagnostics = diagnostics


# ---------------------------------------------------------------------------
# Configuration pieces.
# ---------------------------------------------------------------------------


class ParameterSelection(BaseModel):
    """One free (calibrated) continuous parameter and its search interval."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    lower: float
    upper: float
    initial: float | None = None
    scale: ParameterScale = "linear"
    transform: ParameterTransform = "identity"

    @field_validator("lower", "upper")
    @classmethod
    def _check_finite(cls, value: float) -> float:
        if not math.isfinite(value):
            raise ValueError("parameter bounds must be finite")
        return value

    @field_validator("initial")
    @classmethod
    def _check_initial(cls, value: float | None) -> float | None:
        if value is not None and not math.isfinite(value):
            raise ValueError("initial value must be finite when supplied")
        return value

    @model_validator(mode="after")
    def _check_range(self) -> ParameterSelection:
        if not self.lower < self.upper:
            raise ValueError(
                f"parameter {self.name!r} requires lower < upper (got {self.lower} >= {self.upper})"
            )
        if self.initial is not None and not (self.lower <= self.initial <= self.upper):
            raise ValueError(
                f"initial {self.initial} for {self.name!r} is outside [{self.lower}, {self.upper}]"
            )
        return self


class FixedParameter(BaseModel):
    """A non-free parameter pinned to an explicit value."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    value: ScalarValue

    @field_validator("value")
    @classmethod
    def _check_value(cls, value: ScalarValue) -> ScalarValue:
        if isinstance(value, float) and not math.isfinite(value):
            raise ValueError("fixed value must be finite")
        return value


class ObjectiveConfig(BaseModel):
    """Which M12A metric is minimised, and over which mapping pair."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    metric: ObjectiveMetric = DEFAULT_OBJECTIVE_METRIC  # type: ignore[assignment]
    observation: str | None = None
    output: str | None = None
    aggregation: Literal["single_pair"] = "single_pair"
    direction: Literal["minimize"] = "minimize"

    @model_validator(mode="after")
    def _check_pair_selector(self) -> ObjectiveConfig:
        if (self.observation is None) != (self.output is None):
            raise ValueError("objective pair requires both 'observation' and 'output'")
        return self


class BudgetSpec(BaseModel):
    """Explicit execution budgets. Evaluation count is the authoritative hard cap."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    max_evaluations: int = 100
    max_wall_seconds: float = 600.0
    max_failed: int | None = None

    @field_validator("max_evaluations")
    @classmethod
    def _check_evals(cls, value: int) -> int:
        if isinstance(value, bool) or value < 1:
            raise ValueError("max_evaluations must be a positive integer")
        return value

    @field_validator("max_wall_seconds")
    @classmethod
    def _check_wall(cls, value: float) -> float:
        if not math.isfinite(value) or value <= 0:
            raise ValueError("max_wall_seconds must be finite and > 0")
        return value

    @field_validator("max_failed")
    @classmethod
    def _check_failed(cls, value: int | None) -> int | None:
        if value is not None and (isinstance(value, bool) or value < 1):
            raise ValueError("max_failed must be a positive integer when supplied")
        return value


class ExecutionTemplate(BaseModel):
    """Execution controls applied to each single-run candidate experiment."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    solver: SolverChoice = "auto"
    timeout_s: float = 60.0
    isolation: IsolationMode = "subprocess"
    max_runs: Literal[1] = 1

    @field_validator("timeout_s")
    @classmethod
    def _check_timeout(cls, value: float) -> float:
        if not math.isfinite(value) or value <= 0:
            raise ValueError("timeout_s must be finite and > 0")
        return value


class OptimizerConfig(BaseModel):
    """The search strategy and its (secondary) configuration."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: OptimizerName = DEFAULT_OPTIMIZER  # type: ignore[assignment]
    max_iterations: int | None = None
    population_size: int | None = None
    mutation: float | None = None
    recombination: float | None = None

    @field_validator("max_iterations")
    @classmethod
    def _check_iterations(cls, value: int | None) -> int | None:
        if value is not None and (isinstance(value, bool) or value < 1):
            raise ValueError("max_iterations must be a positive integer when supplied")
        return value

    @field_validator("population_size")
    @classmethod
    def _check_population(cls, value: int | None) -> int | None:
        if value is not None and (isinstance(value, bool) or value < 1):
            raise ValueError("population_size must be a positive integer when supplied")
        return value

    @model_validator(mode="after")
    def _check_de_only(self) -> OptimizerConfig:
        de_only = (self.population_size, self.mutation, self.recombination)
        if self.name != "differential_evolution" and any(item is not None for item in de_only):
            raise ValueError(
                "population_size/mutation/recombination are only valid for "
                "the 'differential_evolution' optimizer"
            )
        return self


class CalibrationConfig(BaseModel):
    """A complete calibration request (the *identity* of one search)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: str = CALIBRATION_SCHEMA_VERSION
    experiment_id: str
    model_ref: ModelRef
    free: tuple[ParameterSelection, ...]
    fixed: tuple[FixedParameter, ...] = ()
    objective: ObjectiveConfig
    optimizer: OptimizerConfig = Field(default_factory=OptimizerConfig)
    budget: BudgetSpec = Field(default_factory=BudgetSpec)
    seed: int = 0
    execution: ExecutionTemplate = Field(default_factory=ExecutionTemplate)
    dataset: DatasetRef
    mapping: ObservationMapping
    evaluation: EvaluationConfig
    identifiability: IdentifiabilityMode = "warn"
    data_role: DataRole = "calibration"
    notes: str = ""

    @field_validator("seed")
    @classmethod
    def _check_seed(cls, value: int) -> int:
        if isinstance(value, bool) or value < 0:
            raise ValueError("seed must be a non-negative integer")
        return value

    @model_validator(mode="after")
    def _check_consistency(self) -> CalibrationConfig:
        if not self.free:
            raise ValueError("at least one free parameter is required")
        free_names = [item.name for item in self.free]
        duplicates = sorted({name for name in free_names if free_names.count(name) > 1})
        if duplicates:
            raise ValueError(f"duplicate free parameters: {duplicates}")
        fixed_names = [item.name for item in self.fixed]
        fixed_duplicates = sorted({name for name in fixed_names if fixed_names.count(name) > 1})
        if fixed_duplicates:
            raise ValueError(f"duplicate fixed parameters: {fixed_duplicates}")
        overlap = sorted(set(free_names) & set(fixed_names))
        if overlap:
            raise ValueError(f"parameters cannot be both free and fixed: {overlap}")

        if self.objective.metric not in self.evaluation.metrics:
            raise ValueError(
                f"objective metric {self.objective.metric!r} is not requested in "
                "evaluation.metrics; the objective must come from M12A"
            )

        if self.mapping.model_ref.model_id != self.model_ref.model_id:
            raise ValueError("mapping.model_ref does not match model_ref")
        if (
            self.mapping.dataset.dataset_id != self.dataset.dataset_id
            or self.mapping.dataset.content_hash != self.dataset.content_hash
        ):
            raise ValueError("mapping.dataset does not match dataset")

        # Pair selector: required when the mapping holds more than one pair.
        pairs = {(pair.observation, pair.output) for pair in self.mapping.pairs}
        if self.objective.observation is not None:
            if (self.objective.observation, self.objective.output) not in pairs:
                raise ValueError(
                    f"objective pair ({self.objective.observation!r}, {self.objective.output!r}) "
                    "is not declared in the mapping"
                )
        elif len(self.mapping.pairs) > 1:
            raise ValueError(
                "the mapping declares multiple pairs; the objective must select one pair "
                "via 'observation' and 'output'"
            )
        return self

    def content_hash(self) -> str:
        return compute_calibration_hash(self)


# ---------------------------------------------------------------------------
# Model-aware resolution (initial values, bounds, fixed set).
# ---------------------------------------------------------------------------


class ResolvedParameter(BaseModel):
    """A free parameter with its concrete bounds and initial value."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    lower: float
    upper: float
    initial: float
    unit: str = "dimensionless"


class ResolvedCalibration(BaseModel):
    """The fully resolved search domain (canonical parameter order)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    free: tuple[ResolvedParameter, ...]  # sorted by name
    fixed: dict[str, ScalarValue]

    @property
    def names(self) -> list[str]:
        return [item.name for item in self.free]

    @property
    def bounds(self) -> list[tuple[float, float]]:
        return [(item.lower, item.upper) for item in self.free]

    @property
    def initial(self) -> list[float]:
        return [item.initial for item in self.free]


def _resolve(
    config: CalibrationConfig,
    schema: ModelSchema,
    baseline: dict[str, ScalarValue],
) -> tuple[ResolvedCalibration | None, tuple[Diagnostic, ...]]:
    diagnostics: list[Diagnostic] = []

    def error(code: str, message: str) -> None:
        diagnostics.append(Diagnostic(level="error", code=code, message=message))

    if config.model_ref.model_id != schema.model_id:
        error(
            "model_mismatch",
            f"config references model {config.model_ref.model_id!r} but schema is "
            f"{schema.model_id!r}",
        )

    free_names = {item.name for item in config.free}
    free_resolved: list[ResolvedParameter] = []
    for selection in config.free:
        name = selection.name
        if not schema.has_parameter(name):
            error("unknown_free_parameter", f"model {schema.model_id!r} has no parameter {name!r}")
            continue
        parameter = schema.parameter(name)
        if parameter.type != "float":
            error(
                "free_parameter_not_float",
                f"free parameter {name!r} has type {parameter.type!r}; only float parameters "
                "are supported in v1",
            )
            continue
        lower, upper = selection.lower, selection.upper
        if parameter.lower is not None and lower < parameter.lower:
            error(
                "bounds_widen_model_lower",
                f"free parameter {name!r} lower {lower} is below the model bound {parameter.lower}",
            )
        if parameter.upper is not None and upper > parameter.upper:
            error(
                "bounds_widen_model_upper",
                f"free parameter {name!r} upper {upper} is above the model bound {parameter.upper}",
            )
        initial = selection.initial
        if initial is None:
            nominal = parameter.nominal
            if isinstance(nominal, bool) or not isinstance(nominal, (int, float)):
                error(
                    "initial_required",
                    f"free parameter {name!r} has no explicit initial and the model declares "
                    "no numeric nominal; an explicit initial is required",
                )
                continue
            initial = float(nominal)
        if not (lower <= initial <= upper):
            error(
                "initial_out_of_bounds",
                f"initial {initial} for {name!r} is outside [{lower}, {upper}]",
            )
            continue
        free_resolved.append(
            ResolvedParameter(
                name=name, lower=lower, upper=upper, initial=initial, unit=parameter.unit
            )
        )

    # Fixed set: every declared parameter that is not free.
    fixed: dict[str, ScalarValue] = {}
    explicit_fixed = {item.name: item.value for item in config.fixed}
    for parameter in schema.parameters:
        if parameter.name in free_names:
            continue
        if parameter.name in explicit_fixed:
            value = explicit_fixed[parameter.name]
        elif parameter.name in baseline:
            value = baseline[parameter.name]
        elif parameter.nominal is not None:
            value = parameter.nominal
        else:
            error(
                "fixed_value_unavailable",
                f"parameter {parameter.name!r} is not free and has no baseline, override or "
                "nominal value",
            )
            continue
        if parameter.type in ("float", "int") and (
            isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value))
        ):
            error(
                "fixed_value_invalid",
                f"fixed value {value!r} for parameter {parameter.name!r} is not a finite number",
            )
            continue
        fixed[parameter.name] = value

    for name in explicit_fixed:
        if not schema.has_parameter(name):
            error("unknown_fixed_parameter", f"model {schema.model_id!r} has no parameter {name!r}")

    if any(diagnostic.level == "error" for diagnostic in diagnostics):
        return None, tuple(diagnostics)

    free_resolved.sort(key=lambda item: item.name)
    return ResolvedCalibration(free=tuple(free_resolved), fixed=fixed), tuple(diagnostics)


def resolve_calibration(
    config: CalibrationConfig,
    schema: ModelSchema,
    baseline: dict[str, ScalarValue],
) -> ResolvedCalibration:
    """Resolve free bounds/initials and the fixed parameter set against a model.

    Raises :class:`CalibrationConfigError` when the request is not executable.
    """
    resolved, diagnostics = _resolve(config, schema, baseline)
    if resolved is None:
        errors = [d.message for d in diagnostics if d.level == "error"]
        raise CalibrationConfigError("; ".join(errors) or "invalid calibration", diagnostics=diagnostics)
    return resolved


def validate_calibration_config(
    config: CalibrationConfig,
    schema: ModelSchema,
    baseline: dict[str, ScalarValue],
) -> tuple[Diagnostic, ...]:
    """Return model-aware diagnostics (empty when the calibration is executable)."""
    _, diagnostics = _resolve(config, schema, baseline)
    return diagnostics


# ---------------------------------------------------------------------------
# Result contract.
# ---------------------------------------------------------------------------


class CalibrationCandidateSummary(BaseModel):
    """One recorded candidate: parameters, run, objective and failure code."""

    model_config = ConfigDict(extra="forbid")

    index: int
    parameters: dict[str, float]
    run_id: str | None = None
    run_status: str | None = None
    evaluation_hash: str | None = None
    objective: float | None = None
    failure: str | None = None
    n_used: int = 0
    n_excluded: int = 0
    duration_s: float | None = None
    diagnostics: list[Diagnostic] = Field(default_factory=list)

    @property
    def valid(self) -> bool:
        return self.objective is not None and self.failure is None


class CalibrationObjective(BaseModel):
    """The resolved objective: metric, pair, direction and best value."""

    model_config = ConfigDict(extra="forbid")

    metric: str
    observation: str
    output: str
    aggregation: str = "single_pair"
    direction: str = "minimize"
    value: float | None = None
    invalid_objective_sentinel: str = "+inf"


class CalibrationProvenance(BaseModel):
    """The exact inputs a calibration was produced from."""

    model_config = ConfigDict(extra="forbid")

    experiment_id: str
    spec_hash: str = ""
    model_id: str
    model_hash: str
    environment_hash: str
    scipy_version: str
    dataset_content_hash: str
    dataset_science_hash: str
    mapping_hash: str
    evaluation_config_hash: str
    evaluation_hash: str | None = None
    engine_schema_version: str = CALIBRATION_SCHEMA_VERSION


class CalibrationResult(BaseModel):
    """A content-addressed calibration outcome (request + execution + history)."""

    model_config = ConfigDict(extra="forbid")

    schema_version: str = CALIBRATION_SCHEMA_VERSION
    calibration_hash: str
    result_hash: str
    experiment_id: str
    model_ref: ModelRef
    config: CalibrationConfig
    status: CalibrationStatus
    stop_reason: CalibrationStopReason
    converged: bool
    best: CalibrationCandidateSummary | None = None
    objective: CalibrationObjective
    evaluations_requested: int
    evaluations_completed: int
    evaluations_invalid: int
    iterations: int
    wall_seconds: float
    identifiability: dict[str, Any] | None = None
    history: list[CalibrationCandidateSummary] = Field(default_factory=list)
    diagnostics: list[Diagnostic] = Field(default_factory=list)
    provenance: CalibrationProvenance
    note: str = DEFAULT_DISCLOSURE


class CalibrationRef(BaseModel):
    """A stable reference to a stored calibration (id + authoritative result hash)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    calibration_id: str
    result_hash: str
    experiment_id: str
    model_id: str
    status: str
    created_at: str | None = None

    @model_validator(mode="after")
    def _check_identity(self) -> CalibrationRef:
        if not _HEX64.match(self.result_hash):
            raise ValueError("result_hash must be a 64-character lowercase hex digest")
        if not _CALIBRATION_ID_PATTERN.match(self.calibration_id):
            raise ValueError(f"invalid calibration id {self.calibration_id!r}")
        if self.calibration_id != short_calibration_id(self.result_hash):
            raise ValueError(
                f"calibration_id {self.calibration_id!r} does not match result_hash"
            )
        return self


# ---------------------------------------------------------------------------
# Identity / hashing.
# ---------------------------------------------------------------------------

#: Config fields excluded from ``calibration_hash`` (non-scientific metadata).
_IDENTITY_EXCLUDED = frozenset({"notes"})


def calibration_identity_payload(config: CalibrationConfig) -> dict[str, Any]:
    """The canonical payload defining ``calibration_hash`` (the *request*)."""
    plain = to_plain(config)
    for key in _IDENTITY_EXCLUDED:
        plain.pop(key, None)
    # Canonical parameter ordering (independent of declaration order).
    plain["free"] = sorted(plain["free"], key=lambda item: item["name"])
    plain["fixed"] = sorted(plain["fixed"], key=lambda item: item["name"])
    return {"kind": "calibration_request", **plain}


def compute_calibration_hash(config: CalibrationConfig) -> str:
    """Deterministic identity of a calibration request."""
    return content_hash(calibration_identity_payload(config))


def calibration_result_payload(result: CalibrationResult) -> dict[str, Any]:
    """The canonical payload defining ``result_hash`` (the *outcome*).

    Wall-clock durations are excluded: the outcome identity is the deterministic
    candidate search (ordering, parameters, objectives), not how long it took.
    """
    plain = to_plain(result)
    plain.pop("result_hash", None)
    plain.pop("wall_seconds", None)
    best = plain.get("best")
    if isinstance(best, dict):
        best.pop("duration_s", None)
    for candidate in plain.get("history", []):
        candidate.pop("duration_s", None)
    return {"kind": "calibration_result", **plain}


def compute_result_hash(result: CalibrationResult) -> str:
    """Deterministic content address of a calibration outcome."""
    return content_hash(calibration_result_payload(result))


def short_calibration_id(result_hash: str) -> str:
    """Derive the short calibration id from a full result hash (``cal-<12 hex>``)."""
    if not isinstance(result_hash, str) or not _HEX64.match(result_hash):
        raise ValueError("result_hash must be a 64-character lowercase hex digest")
    return f"cal-{result_hash[:12]}"
