"""Validation / generalisation contract (M12C).

M12C answers a single question: *given a completed calibration that fitted a
bounded parameter vector to a calibration dataset, does the model with those
parameters **frozen** reproduce independent observations that were not used to
fit it?*

It is **composition, not new science**. Validation never executes a model
directly (the :class:`~drw.execution.runner.Runner` is the only execution path),
never re-implements comparison (M12A :func:`drw.evaluation.evaluate_run` is the
only comparison) and contains **no optimizer**, so it cannot refit. All
measurement is M12A's.

Design rules enforced here:

* **Three orthogonal axes, never one boolean.** *Agreement* (does the model
  reproduce the held-out observations?), *acceptance* (does it meet an explicit
  user-supplied criterion?) and *independence* (was the evidence verified
  independent, or only declared?) are kept separate and never collapsed.
* **Per-dataset results.** One result per validation dataset. There is no
  implicit cross-dataset scalar.
* **No universal pass/fail.** A user criterion is a decision rule, not
  scientific truth; ``met`` alone never yields a supported status.
* **Fail closed.** Invalid inputs produce explicit codes, never fabricated
  numbers.

See ``docs/reports/milestone-12c-validation-design.md`` for the design.
"""

from __future__ import annotations

import math
import re
from collections.abc import Mapping
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from drw.schema.calibration import CalibrationRef, CalibrationResult, ExecutionTemplate
from drw.schema.evaluation import (
    CORE_METRICS,
    RELATIVE_METRICS,
    WEIGHTED_METRICS,
    EvaluationConfig,
    MetricName,
)
from drw.schema.model import ModelRef, ModelSchema
from drw.schema.observation import DatasetRef, ObservationMapping, short_dataset_id
from drw.schema.result import Diagnostic
from drw.schema.serialization import content_hash, to_plain

__all__ = [
    "AVAILABLE_METRICS",
    "DECLARED_DIMENSIONS",
    "DEFAULT_MAX_EVALUATIONS",
    "DEFAULT_MAX_WALL_SECONDS",
    "DEFAULT_VALIDATION_DISCLOSURE",
    "DEFAULT_VALIDATION_METRICS",
    "VALIDATION_ID_PATTERN",
    "VALIDATION_SCHEMA_VERSION",
    "VERIFIABLE_DIMENSIONS",
    "AcceptanceCriterion",
    "AcceptanceOp",
    "AcceptanceOutcome",
    "AcceptanceStatus",
    "AgreementStatus",
    "CoordinateRangeComparison",
    "CoordinateWindow",
    "DataRoleValidation",
    "IndependenceCheck",
    "IndependenceCheckState",
    "IndependenceDimension",
    "IndependenceReport",
    "IndependenceSpec",
    "IndependenceStatus",
    "RangeClassification",
    "ValidationBudget",
    "ValidationCalibrationSnapshot",
    "ValidationConfig",
    "ValidationConfigError",
    "ValidationContext",
    "ValidationDataset",
    "ValidationDatasetResult",
    "ValidationError",
    "ValidationParameterMismatch",
    "ValidationProvenance",
    "ValidationRef",
    "ValidationResult",
    "build_frozen_vector",
    "compute_validation_hash",
    "compute_validation_result_hash",
    "resolve_validation",
    "short_validation_id",
    "validate_validation_config",
    "validation_identity_payload",
    "validation_result_payload",
]

VALIDATION_SCHEMA_VERSION = "1.0.0"

VALIDATION_ID_PATTERN = re.compile(r"^val-[0-9a-f]{12}$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")

AgreementStatus = Literal[
    "not_run",  # no dataset was executed (budget)
    "evaluated",  # usable metrics produced (no verdict implied)
    "partial",  # some datasets failed / were not run
    "inconclusive",  # executed but every requested metric was unusable
    "does_not_agree",  # reserved: requires an explicit agreement rule (not v1)
    "failed",  # every dataset failed
]
AcceptanceStatus = Literal["met", "not_met", "not_specified", "indeterminate"]
AcceptanceOp = Literal["<=", "<", ">=", ">"]
IndependenceStatus = Literal[
    "verified", "partially_verified", "declared_only", "violated", "unknown"
]
IndependenceCheckState = Literal["verified", "violated", "declared", "unverifiable"]
IndependenceDimension = Literal[
    "dataset", "time_window", "entity", "region", "measurement_process", "experiment"
]
RangeClassification = Literal["within_range", "outside_range", "unknown"]

#: Validation-local data role. M12B's ``DataRole`` literal is deliberately not widened.
DataRoleValidation = Literal["validation"]

#: Dimensions DRW can mechanically verify (when the required columns exist).
VERIFIABLE_DIMENSIONS: tuple[str, ...] = ("dataset", "time_window", "entity", "region")
#: Dimensions that can only ever be *declared*.
DECLARED_DIMENSIONS: tuple[str, ...] = ("measurement_process", "experiment")

#: Conservative, generic default validation metrics (counts are separate fields).
DEFAULT_VALIDATION_METRICS: tuple[str, ...] = ("rmse", "mae", "max_abs_error")
#: Every M12A metric name, for capability advertisement only.
AVAILABLE_METRICS: tuple[str, ...] = (*CORE_METRICS, *RELATIVE_METRICS, *WEIGHTED_METRICS)

DEFAULT_MAX_EVALUATIONS = 10
DEFAULT_MAX_WALL_SECONDS = 600.0

#: Mandatory scientific disclosure attached to every validation result.
DEFAULT_VALIDATION_DISCLOSURE = (
    "Validation tests a frozen calibrated model against observations that were not used to fit "
    "it. It reports model/observation agreement, independence evidence and (optionally) a "
    "user-supplied acceptance criterion as three separate axes. Agreement here does not "
    "establish that the model is correct, does not generalise beyond the tested domain, and is "
    "not a statement of model truth; an acceptance criterion is a user decision rule, not "
    "scientific evidence."
)


class ValidationError(ValueError):
    """Base class for validation configuration/execution failures."""


class ValidationConfigError(ValidationError):
    """Raised when a validation cannot be requested or resolved against a model."""

    def __init__(self, message: str, *, diagnostics: tuple[Diagnostic, ...] = ()) -> None:
        super().__init__(message)
        self.diagnostics = diagnostics


class ValidationParameterMismatch(ValidationError):
    """Raised when the executed parameter snapshot differs from the frozen vector."""


# ---------------------------------------------------------------------------
# Configuration pieces.
# ---------------------------------------------------------------------------


class AcceptanceCriterion(BaseModel):
    """One user-supplied decision rule on a named M12A metric (arbitrary by nature)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    metric: MetricName
    observation: str | None = None
    output: str | None = None
    op: AcceptanceOp
    threshold: float
    rationale: str = ""

    @field_validator("threshold")
    @classmethod
    def _check_threshold(cls, value: float) -> float:
        if not math.isfinite(value):
            raise ValueError("acceptance threshold must be finite")
        return value

    @model_validator(mode="after")
    def _check_selector(self) -> AcceptanceCriterion:
        if (self.observation is None) != (self.output is None):
            raise ValueError("an acceptance criterion pair requires both observation and output")
        return self


class CoordinateWindow(BaseModel):
    """An explicit calibration window along a coordinate (optional override)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    coordinate: str
    lower: float | str | None = None
    upper: float | str | None = None

    @model_validator(mode="after")
    def _check_window(self) -> CoordinateWindow:
        if self.lower is None and self.upper is None:
            raise ValueError("a coordinate window requires at least one bound")
        for value in (self.lower, self.upper):
            if isinstance(value, float) and not math.isfinite(value):
                raise ValueError("numeric window bounds must be finite")
        if (
            isinstance(self.lower, (int, float))
            and not isinstance(self.lower, bool)
            and isinstance(self.upper, (int, float))
            and not isinstance(self.upper, bool)
            and self.lower > self.upper
        ):
            raise ValueError("window lower must be <= upper")
        return self


class IndependenceSpec(BaseModel):
    """The structured independence claim for one validation dataset (never a boolean)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    vs_dataset: DatasetRef
    coordinate_windows: tuple[CoordinateWindow, ...] = ()
    group_key: str | None = None
    claimed_dimensions: tuple[IndependenceDimension, ...] = ()
    declaration: str = ""

    @field_validator("coordinate_windows")
    @classmethod
    def _check_windows(cls, value: tuple[CoordinateWindow, ...]) -> tuple[CoordinateWindow, ...]:
        names = [window.coordinate for window in value]
        duplicates = sorted({name for name in names if names.count(name) > 1})
        if duplicates:
            raise ValueError(f"duplicate coordinate windows: {duplicates}")
        return value

    @field_validator("claimed_dimensions")
    @classmethod
    def _check_dimensions(
        cls, value: tuple[IndependenceDimension, ...]
    ) -> tuple[IndependenceDimension, ...]:
        duplicates = sorted({name for name in value if value.count(name) > 1})
        if duplicates:
            raise ValueError(f"duplicate claimed dimensions: {duplicates}")
        return value


class ValidationDataset(BaseModel):
    """One validation target: a dataset, its mapping and its independence claim."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    dataset: DatasetRef
    mapping: ObservationMapping
    independence: IndependenceSpec
    label: str = ""
    acceptance: tuple[AcceptanceCriterion, ...] | None = None

    @model_validator(mode="after")
    def _check_mapping(self) -> ValidationDataset:
        if (
            self.mapping.dataset.dataset_id != self.dataset.dataset_id
            or self.mapping.dataset.content_hash != self.dataset.content_hash
        ):
            raise ValueError("mapping.dataset does not match dataset")
        return self


class ValidationBudget(BaseModel):
    """Validation's own hard budget (never shared with M12B's calibration budget)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    max_evaluations: int = DEFAULT_MAX_EVALUATIONS
    max_wall_seconds: float = DEFAULT_MAX_WALL_SECONDS
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


class ValidationConfig(BaseModel):
    """A complete validation request (the *identity* of one validation)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: str = VALIDATION_SCHEMA_VERSION
    experiment_id: str
    model_ref: ModelRef
    calibration: CalibrationRef
    datasets: tuple[ValidationDataset, ...]
    evaluation: EvaluationConfig
    budget: ValidationBudget = Field(default_factory=ValidationBudget)
    execution: ExecutionTemplate = Field(default_factory=ExecutionTemplate)
    acceptance: tuple[AcceptanceCriterion, ...] = ()
    report_gap: bool = True
    allow_non_independent: bool = False
    data_role: DataRoleValidation = "validation"
    notes: str = ""

    @model_validator(mode="after")
    def _check_consistency(self) -> ValidationConfig:
        if not self.datasets:
            raise ValueError("at least one validation dataset is required")

        dataset_ids = [item.dataset.dataset_id for item in self.datasets]
        duplicates = sorted({name for name in dataset_ids if dataset_ids.count(name) > 1})
        if duplicates:
            raise ValueError(f"duplicate validation datasets: {duplicates}")

        if self.calibration.model_id != self.model_ref.model_id:
            raise ValueError("calibration.model_id does not match model_ref")

        for item in self.datasets:
            if item.mapping.model_ref.model_id != self.model_ref.model_id:
                raise ValueError("a validation dataset mapping does not match model_ref")
            criteria = item.acceptance if item.acceptance is not None else ()
            if len(item.mapping.pairs) > 1:
                for criterion in criteria:
                    if criterion.observation is None:
                        raise ValueError(
                            "an acceptance criterion must select a pair when the mapping "
                            "declares multiple pairs"
                        )

        criteria = [*self.acceptance, *(c for item in self.datasets for c in (item.acceptance or ()))]
        for criterion in criteria:
            if criterion.metric not in self.evaluation.metrics:
                raise ValueError(
                    f"acceptance metric {criterion.metric!r} is not requested in "
                    "evaluation.metrics; acceptance must reference an M12A metric"
                )
        return self

    def content_hash(self) -> str:
        return compute_validation_hash(self)


# ---------------------------------------------------------------------------
# Result pieces.
# ---------------------------------------------------------------------------


class IndependenceCheck(BaseModel):
    """One independence check for one dimension (verified / violated / declared / unverifiable)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    dimension: str
    state: IndependenceCheckState
    message: str = ""


class IndependenceReport(BaseModel):
    """The structured independence report for one validation dataset."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    status: IndependenceStatus
    checks: tuple[IndependenceCheck, ...] = ()
    declaration: str = ""
    note: str = ""


class CoordinateRangeComparison(BaseModel):
    """How a validation coordinate range compares to the calibration range."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    coordinate: str
    kind: str
    calibration_min: float | None = None
    calibration_max: float | None = None
    validation_min: float | None = None
    validation_max: float | None = None
    classification: RangeClassification = "unknown"


class ValidationContext(BaseModel):
    """Minimal, mechanically-derived interpolation/extrapolation context (plus declarations)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    coordinate_ranges: tuple[CoordinateRangeComparison, ...] = ()
    unseen_groups: tuple[str, ...] = ()
    regime: str = ""
    note: str = ""


class AcceptanceOutcome(BaseModel):
    """The outcome of applying one acceptance criterion to one dataset's metrics."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    metric: str
    observation: str | None = None
    output: str | None = None
    op: AcceptanceOp
    threshold: float
    observed: float | None = None
    status: Literal["met", "not_met", "indeterminate"]
    message: str = ""


class ValidationDatasetResult(BaseModel):
    """The per-dataset validation outcome (always present, never aggregated)."""

    model_config = ConfigDict(extra="forbid")

    label: str = ""
    dataset: DatasetRef
    mapping_hash: str
    independence: IndependenceReport
    context: ValidationContext = Field(default_factory=ValidationContext)
    run_id: str | None = None
    run_status: str | None = None
    evaluation_hash: str | None = None
    metrics: dict[str, float | None] = Field(default_factory=dict)
    n_used: int = 0
    n_excluded: int = 0
    exclusion_counts: dict[str, int] = Field(default_factory=dict)
    calibration_metrics: dict[str, float | None] = Field(default_factory=dict)
    calibration_evaluation_hash: str | None = None
    acceptance: tuple[AcceptanceOutcome, ...] = ()
    agreement: AgreementStatus
    failure: str | None = None
    diagnostics: tuple[Diagnostic, ...] = ()


class ValidationCalibrationSnapshot(BaseModel):
    """The frozen calibration a validation was produced from (the no-refit record)."""

    model_config = ConfigDict(extra="forbid")

    calibration_id: str
    result_hash: str
    calibration_hash: str
    model_id: str
    model_hash: str
    parameters: dict[str, float] = Field(default_factory=dict)
    dataset_content_hash: str
    dataset_science_hash: str
    mapping_hash: str
    evaluation_hash: str | None = None


class ValidationProvenance(BaseModel):
    """The exact inputs a validation was produced from (the full dependency chain)."""

    model_config = ConfigDict(extra="forbid")

    experiment_id: str
    spec_hash: str = ""
    model_id: str
    model_hash: str
    calibration_result_hash: str
    calibration_hash: str
    calibration_dataset_content_hash: str
    calibration_dataset_science_hash: str
    calibration_mapping_hash: str
    calibration_evaluation_hash: str | None = None
    validation_dataset_content_hashes: tuple[str, ...] = ()
    validation_science_hashes: tuple[str, ...] = ()
    mapping_hashes: tuple[str, ...] = ()
    evaluation_config_hash: str
    evaluation_hashes: tuple[str, ...] = ()
    environment_hash: str
    engine_schema_version: str = VALIDATION_SCHEMA_VERSION
    scipy_version: str = ""
    deterministic: bool = True


class ValidationResult(BaseModel):
    """A content-addressed validation outcome (request + execution + per-dataset results)."""

    model_config = ConfigDict(extra="forbid")

    schema_version: str = VALIDATION_SCHEMA_VERSION
    validation_hash: str
    result_hash: str
    experiment_id: str
    model_ref: ModelRef
    config: ValidationConfig
    calibration: ValidationCalibrationSnapshot
    datasets: tuple[ValidationDatasetResult, ...]
    agreement_status: AgreementStatus
    acceptance_status: AcceptanceStatus
    independence_status: IndependenceStatus
    evaluations_requested: int
    evaluations_completed: int
    evaluations_failed: int
    wall_seconds: float
    descriptive: bool = False
    diagnostics: tuple[Diagnostic, ...] = ()
    provenance: ValidationProvenance
    note: str = DEFAULT_VALIDATION_DISCLOSURE


class ValidationRef(BaseModel):
    """A stable reference to a stored validation (id + authoritative result hash)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    validation_id: str
    result_hash: str
    experiment_id: str
    model_id: str
    agreement_status: str
    created_at: str | None = None

    @model_validator(mode="after")
    def _check_identity(self) -> ValidationRef:
        if not _HEX64.match(self.result_hash):
            raise ValueError("result_hash must be a 64-character lowercase hex digest")
        if not VALIDATION_ID_PATTERN.match(self.validation_id):
            raise ValueError(f"invalid validation id {self.validation_id!r}")
        if self.validation_id != short_validation_id(self.result_hash):
            raise ValueError(f"validation_id {self.validation_id!r} does not match result_hash")
        return self


# ---------------------------------------------------------------------------
# Model-aware resolution: the frozen parameter vector.
# ---------------------------------------------------------------------------


def _resolve_frozen(
    schema: ModelSchema,
    calibration: CalibrationResult,
    baseline: Mapping[str, Any],
) -> tuple[dict[str, Any] | None, tuple[Diagnostic, ...]]:
    diagnostics: list[Diagnostic] = []

    def error(code: str, message: str) -> None:
        diagnostics.append(Diagnostic(level="error", code=code, message=message))

    if calibration.model_ref.model_id != schema.model_id:
        error(
            "model_mismatch",
            f"calibration references model {calibration.model_ref.model_id!r} but schema is "
            f"{schema.model_id!r}",
        )
    if calibration.best is None:
        error("calibration_has_no_best", "the calibration has no best candidate to freeze")

    frozen: dict[str, Any] = {}
    if calibration.best is not None:
        free = dict(calibration.best.parameters)
        explicit_fixed = {item.name: item.value for item in calibration.config.fixed}
        for parameter in schema.parameters:
            name = parameter.name
            if name in free:
                value: Any = free[name]
            elif name in explicit_fixed:
                value = explicit_fixed[name]
            elif name in baseline:
                value = baseline[name]
            elif parameter.nominal is not None:
                value = parameter.nominal
            else:
                error(
                    "invalid_frozen_parameters",
                    f"parameter {name!r} has no calibrated, fixed, baseline or nominal value",
                )
                continue
            if parameter.type in ("float", "int"):
                if (
                    isinstance(value, bool)
                    or not isinstance(value, (int, float))
                    or not math.isfinite(float(value))
                ):
                    error(
                        "invalid_frozen_parameters",
                        f"frozen value {value!r} for parameter {name!r} is not a finite number",
                    )
                    continue
                if parameter.lower is not None and float(value) < parameter.lower:
                    error(
                        "invalid_frozen_parameters",
                        f"frozen value {value} for {name!r} is below the model bound "
                        f"{parameter.lower}",
                    )
                    continue
                if parameter.upper is not None and float(value) > parameter.upper:
                    error(
                        "invalid_frozen_parameters",
                        f"frozen value {value} for {name!r} is above the model bound "
                        f"{parameter.upper}",
                    )
                    continue
            frozen[name] = value

        for name in free:
            if not schema.has_parameter(name):
                error(
                    "invalid_frozen_parameters",
                    f"calibrated parameter {name!r} is not a parameter of model "
                    f"{schema.model_id!r}",
                )

    if any(diagnostic.level == "error" for diagnostic in diagnostics):
        return None, tuple(diagnostics)
    return frozen, tuple(diagnostics)


def build_frozen_vector(
    calibration: CalibrationResult,
    schema: ModelSchema,
    baseline: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the complete frozen parameter vector (raises on any invalid input)."""
    frozen, diagnostics = _resolve_frozen(schema, calibration, baseline or {})
    if frozen is None:
        errors = [d.message for d in diagnostics if d.level == "error"]
        raise ValidationConfigError(
            "; ".join(errors) or "invalid frozen parameters", diagnostics=diagnostics
        )
    return frozen


def _validate_frozen(
    config: ValidationConfig,
    schema: ModelSchema,
    calibration: CalibrationResult,
    baseline: Mapping[str, Any],
) -> tuple[dict[str, Any] | None, tuple[Diagnostic, ...]]:
    diagnostics: list[Diagnostic] = []

    def error(code: str, message: str) -> None:
        diagnostics.append(Diagnostic(level="error", code=code, message=message))

    if config.model_ref.model_id != schema.model_id:
        error(
            "model_mismatch",
            f"config references model {config.model_ref.model_id!r} but schema is "
            f"{schema.model_id!r}",
        )

    for item in config.datasets:
        target = item.independence.vs_dataset
        expected_id = short_dataset_id(calibration.provenance.dataset_content_hash)
        if (
            target.content_hash != calibration.provenance.dataset_content_hash
            or target.dataset_id != expected_id
        ):
            error(
                "independence_target_mismatch",
                "independence.vs_dataset does not reference the calibration dataset",
            )

    frozen, frozen_diagnostics = _resolve_frozen(schema, calibration, baseline)
    diagnostics.extend(frozen_diagnostics)
    if any(diagnostic.level == "error" for diagnostic in diagnostics):
        return None, tuple(diagnostics)
    return frozen, tuple(diagnostics)


def validate_validation_config(
    config: ValidationConfig,
    schema: ModelSchema,
    calibration: CalibrationResult,
    baseline: Mapping[str, Any] | None = None,
) -> tuple[Diagnostic, ...]:
    """Return model-aware diagnostics (empty when the validation is executable)."""
    _, diagnostics = _validate_frozen(config, schema, calibration, baseline or {})
    return diagnostics


def resolve_validation(
    config: ValidationConfig,
    schema: ModelSchema,
    calibration: CalibrationResult,
    baseline: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Resolve the frozen parameter vector, raising when the request is not executable."""
    frozen, diagnostics = _validate_frozen(config, schema, calibration, baseline or {})
    if frozen is None:
        errors = [d.message for d in diagnostics if d.level == "error"]
        raise ValidationConfigError(
            "; ".join(errors) or "invalid validation", diagnostics=diagnostics
        )
    return frozen


# ---------------------------------------------------------------------------
# Identity / hashing.
# ---------------------------------------------------------------------------

#: Config fields excluded from ``validation_hash`` (non-scientific metadata).
_IDENTITY_EXCLUDED = frozenset({"notes"})
_REF_SCIENTIFIC_FIELDS = ("calibration_id", "result_hash", "experiment_id", "model_id", "status")
_DATASET_REF_FIELDS = ("dataset_id", "content_hash")


def _canonical_criteria(criteria: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        criteria,
        key=lambda item: (
            item.get("metric", ""),
            item.get("observation") or "",
            item.get("output") or "",
            item.get("op", ""),
            item.get("threshold", 0.0),
        ),
    )


def validation_identity_payload(config: ValidationConfig) -> dict[str, Any]:
    """The canonical payload defining ``validation_hash`` (the *request*)."""
    plain = to_plain(config)
    for key in _IDENTITY_EXCLUDED:
        plain.pop(key, None)
    # Exclude storage metadata (created_at) from the calibration reference.
    calibration = plain.get("calibration") or {}
    plain["calibration"] = {key: calibration.get(key) for key in _REF_SCIENTIFIC_FIELDS}
    for item in plain.get("datasets", []):
        dataset_ref = item.get("dataset") or {}
        item["dataset"] = {key: dataset_ref.get(key) for key in _DATASET_REF_FIELDS}
        independence = item.get("independence") or {}
        target = independence.get("vs_dataset") or {}
        independence["vs_dataset"] = {key: target.get(key) for key in _DATASET_REF_FIELDS}
        independence["claimed_dimensions"] = sorted(independence.get("claimed_dimensions", []))
        independence["coordinate_windows"] = sorted(
            independence.get("coordinate_windows", []), key=lambda w: w.get("coordinate", "")
        )
        if item.get("acceptance") is not None:
            item["acceptance"] = _canonical_criteria(item["acceptance"])
    plain["datasets"] = sorted(
        plain.get("datasets", []), key=lambda item: item["dataset"]["dataset_id"]
    )
    plain["acceptance"] = _canonical_criteria(plain.get("acceptance", []))
    return {"kind": "validation_request", **plain}


def compute_validation_hash(config: ValidationConfig) -> str:
    """Deterministic identity of a validation request."""
    return content_hash(validation_identity_payload(config))


def validation_result_payload(result: ValidationResult) -> dict[str, Any]:
    """The canonical payload defining ``result_hash`` (the *outcome*).

    Wall-clock durations are excluded: the outcome identity is the deterministic
    per-dataset result, not how long it took.
    """
    plain = to_plain(result)
    plain.pop("result_hash", None)
    plain.pop("wall_seconds", None)
    return {"kind": "validation_result", **plain}


def compute_validation_result_hash(result: ValidationResult) -> str:
    """Deterministic content address of a validation outcome."""
    return content_hash(validation_result_payload(result))


def short_validation_id(result_hash: str) -> str:
    """Derive the short validation id from a full result hash (``val-<12 hex>``)."""
    if not isinstance(result_hash, str) or not _HEX64.match(result_hash):
        raise ValueError("result_hash must be a 64-character lowercase hex digest")
    return f"val-{result_hash[:12]}"
