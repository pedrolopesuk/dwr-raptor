"""Typed contracts for DRW: models, experiments, runs, units and (de)serialization."""

from __future__ import annotations

from drw.schema.experiment import (
    EXPERIMENT_SCHEMA_VERSION,
    AnalysisSpec,
    ConstraintSpec,
    ExecutionSpec,
    ExperimentSpec,
    FactorSpec,
    IsolationMode,
    ReportingSpec,
    RunEstimate,
    SamplingSpec,
    VerificationSpec,
    dedupe_diagnostics,
    estimate_run_count,
    validate_experiment,
)
from drw.schema.model import (
    MODEL_SCHEMA_VERSION,
    ModelRef,
    ModelSchema,
    OutputSpec,
    ParameterSpec,
)
from drw.schema.result import (
    TERMINAL_STATES,
    Diagnostic,
    ModelResult,
    OutputValue,
    RunRecord,
    RunStatus,
    ValidationReport,
    allowed_run_transition,
    is_terminal,
)
from drw.schema.serialization import canonical_json, content_hash, dumps_pretty, sha256_hex

__all__ = [
    "EXPERIMENT_SCHEMA_VERSION",
    "MODEL_SCHEMA_VERSION",
    "TERMINAL_STATES",
    "AnalysisSpec",
    "ConstraintSpec",
    "Diagnostic",
    "ExecutionSpec",
    "ExperimentSpec",
    "FactorSpec",
    "IsolationMode",
    "ModelRef",
    "ModelResult",
    "ModelSchema",
    "OutputSpec",
    "OutputValue",
    "ParameterSpec",
    "ReportingSpec",
    "RunEstimate",
    "RunRecord",
    "RunStatus",
    "SamplingSpec",
    "ValidationReport",
    "VerificationSpec",
    "allowed_run_transition",
    "canonical_json",
    "content_hash",
    "dedupe_diagnostics",
    "dumps_pretty",
    "estimate_run_count",
    "is_terminal",
    "sha256_hex",
    "validate_experiment",
]
