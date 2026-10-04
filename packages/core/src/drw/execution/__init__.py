"""Local execution engine, isolation, environment fingerprinting and evidence."""

from __future__ import annotations

from drw.execution.context import RunContext
from drw.execution.environment import environment_fingerprint, fingerprint_hash
from drw.execution.evidence import EvidenceManifest, build_evidence_package, render_report
from drw.execution.isolation import ExecutionOutcome, SubprocessExecutor
from drw.execution.result import ExperimentResult
from drw.execution.runner import ExperimentValidationError, Runner

__all__ = [
    "EvidenceManifest",
    "ExecutionOutcome",
    "ExperimentResult",
    "ExperimentValidationError",
    "RunContext",
    "Runner",
    "SubprocessExecutor",
    "build_evidence_package",
    "environment_fingerprint",
    "fingerprint_hash",
    "render_report",
]
