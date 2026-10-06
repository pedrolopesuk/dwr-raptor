"""Reproducibility check: re-run a stored experiment and compare (read-only).

The reproduction check answers: *if I execute this saved specification again now,
do I get the same numbers, and is the difference numerical, methodological or
environmental?*

It is deliberately **read-only** with respect to the store. The stored
specification is loaded, re-executed through the existing runner (which never
persists), and the fresh runs are compared to the stored reference runs using the
existing comparison infrastructure (:func:`drw.numerics.delta.compare_outputs`).
The stored experiment, its reference result, evidence manifest and artifacts are
never written.

Tolerance policy: see ADR-0013. The declared ``verification.rtol/atol`` are
*integration* tolerances and are **not** reused here; callers must pass explicit
``rtol``/``atol`` and the pass criterion is
``|fresh - reference| <= atol + rtol * |reference|``.

Classification precedence (intentional - these dimensions are not collapsed into
one boolean):

1. ``execution_failed`` - the fresh execution did not complete successfully.
2. ``inconclusive`` - the run counts differ, or an output could not be compared
   reliably (shape/axis incompatibility or non-finite pairs).
3. ``identical`` - every comparable output is exactly equal element-wise.
4. ``equivalent_within_tolerance`` - every comparable output passes the tolerance.
5. ``different`` - at least one comparable output falls outside the tolerance.

Specification/model/environment hash agreement is reported **separately** in
``provenance``: a matching hash does not prove numerical equivalence, and matching
numbers do not prove the environment or methodology is unchanged.
"""

from __future__ import annotations

from typing import Any, Literal

import numpy as np
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from drw.execution.environment import environment_fingerprint, fingerprint_hash
from drw.execution.runner import ExperimentValidationError, Runner
from drw.models.registry import build_model
from drw.numerics.alignment import AlignmentError
from drw.numerics.delta import compare_outputs
from drw.schema.experiment import ExperimentSpec
from drw.schema.result import Diagnostic, RunRecord
from drw.store import ExperimentStore, default_store

__all__ = [
    "OutputComparison",
    "ProvenanceComparison",
    "ReproduceError",
    "ReproduceReport",
    "ReproduceTolerances",
    "RunComparison",
    "reproduce_experiment",
]

Verdict = Literal[
    "identical",
    "equivalent_within_tolerance",
    "different",
    "inconclusive",
    "execution_failed",
]
OutputStatus = Literal["identical", "equivalent", "different", "incomparable"]


class ReproduceError(ValueError):
    """Raised when a reproduction check cannot be requested or set up."""


class ReproduceTolerances(BaseModel):
    """Explicit, validated tolerances for the reproduction check (ADR-0013)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    rtol: float
    atol: float

    @field_validator("rtol", "atol")
    @classmethod
    def _finite_non_negative(cls, value: float) -> float:
        if not np.isfinite(value) or value < 0.0:
            raise ValueError("tolerances must be finite and >= 0")
        return float(value)

    @field_validator("rtol")
    @classmethod
    def _rtol_below_one(cls, value: float) -> float:
        if value >= 1.0:
            raise ValueError("rtol must be < 1")
        return float(value)


class OutputComparison(BaseModel):
    """Per-output reproduction comparison, built on the existing delta metrics."""

    model_config = ConfigDict(extra="forbid")

    output: str
    unit: str = "dimensionless"
    comparable: bool
    status: OutputStatus
    identical: bool
    passes_tolerance: bool | None = None
    alignment: str | None = None
    interpolated: bool | None = None
    shape_compatible: bool
    max_abs_delta: float | None = None
    max_abs_relative_delta: float | None = None
    mae: float | None = None
    rmse: float | None = None
    n_points: int | None = None
    valid_points: int | None = None
    non_finite_points: int | None = None
    warnings: list[Diagnostic] = Field(default_factory=list)
    note: str | None = None


class RunComparison(BaseModel):
    """Reproduction comparison for one stored run against its fresh counterpart."""

    model_config = ConfigDict(extra="forbid")

    index: int
    label: str
    reference_run_id: str
    fresh_run_id: str | None = None
    reference_status: str
    fresh_status: str | None = None
    comparable: bool
    identical: bool
    passes_tolerance: bool | None = None
    outputs: list[OutputComparison] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class ProvenanceComparison(BaseModel):
    """Hash comparison, independent of the numerical result."""

    model_config = ConfigDict(extra="forbid")

    spec_hash_stored: str
    spec_hash_current: str
    spec_hash_match: bool
    model_hash_stored: str
    model_hash_current: str
    model_hash_match: bool
    environment_hash_stored: str
    environment_hash_current: str
    environment_hash_match: bool
    differences: list[str] = Field(default_factory=list)


class ReproduceReport(BaseModel):
    """A structured, machine-readable reproduction-check report.

    **Reference vs fresh identity.** ``reference_run_ids`` identify the **stored**
    runs the experiment already holds on disk. ``fresh_run_ids`` identify the runs
    produced by re-executing that same specification **in memory**; they are never
    persisted, so ``fresh_runs_persisted`` is always ``False``. Because the
    deterministic experiment id is derived from the specification, a fresh run id
    can be *identical* to the corresponding stored reference run id - the two are
    still distinct executions, but only the stored one exists on disk. Do not read
    a coinciding id as evidence of two separately stored runs.
    """

    model_config = ConfigDict(extra="forbid")

    experiment_id: str
    verdict: Verdict
    numerical: Verdict
    tolerances: ReproduceTolerances
    provenance: ProvenanceComparison
    reference_run_ids: list[str]
    fresh_run_ids: list[str]
    runs: list[RunComparison]
    warnings: list[str] = Field(default_factory=list)
    fresh_runs_persisted: bool = False


def _finite_or_none(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if np.isfinite(number) else None


def _count(value: Any) -> int | None:
    number = _finite_or_none(value)
    return int(number) if number is not None else None


def _within_tolerance(
    reference: np.ndarray, variant: np.ndarray, rtol: float, atol: float
) -> bool | None:
    """Return the element-wise tolerance verdict, or ``None`` if unverifiable."""
    finite = np.isfinite(reference) & np.isfinite(variant)
    if finite.size == 0 or not bool(finite.all()):
        return None
    return bool(np.all(np.abs(variant - reference) <= atol + rtol * np.abs(reference)))


def _compare_output(
    reference_run: RunRecord,
    fresh_run: RunRecord,
    reference_output: Any,
    fresh_output: Any,
    tolerances: ReproduceTolerances,
) -> OutputComparison:
    name = reference_output.name
    unit = reference_output.unit
    try:
        comparison = compare_outputs(
            reference_run,
            fresh_run,
            reference_output,
            fresh_output,
            method="reproduce",
            strategy="exact",
        )
    except AlignmentError as exc:
        return OutputComparison(
            output=name,
            unit=unit,
            comparable=False,
            status="incomparable",
            identical=False,
            shape_compatible=False,
            note=f"outputs could not be aligned exactly: {exc}",
        )

    metrics = comparison.metrics
    common = dict(
        output=name,
        unit=unit,
        alignment=comparison.alignment,
        interpolated=comparison.interpolated,
        shape_compatible=True,
        max_abs_delta=_finite_or_none(metrics.get("max_abs_delta")),
        max_abs_relative_delta=_finite_or_none(metrics.get("max_abs_relative_delta")),
        mae=_finite_or_none(metrics.get("mae")),
        rmse=_finite_or_none(metrics.get("rmse")),
        n_points=_count(metrics.get("n_points")),
        valid_points=_count(metrics.get("valid_points")),
        non_finite_points=_count(metrics.get("non_finite_points")),
        warnings=list(comparison.warnings),
    )

    if comparison.interpolated or comparison.alignment != "exact":
        return OutputComparison(
            **common,
            comparable=False,
            status="incomparable",
            identical=False,
            note="coordinate axes differ; exact comparison is not possible",
        )

    reference = np.asarray(comparison.reference, dtype=float)
    variant = np.asarray(comparison.variant, dtype=float)
    identical = bool(np.array_equal(reference, variant))
    passes = _within_tolerance(reference, variant, tolerances.rtol, tolerances.atol)
    non_finite = int(metrics.get("non_finite_points", 0))

    if passes is None or non_finite > 0:
        return OutputComparison(
            **common,
            comparable=False,
            status="incomparable",
            identical=identical,
            passes_tolerance=None,
            note="non-finite values are present; the tolerance could not be evaluated",
        )
    status: OutputStatus = "identical" if identical else ("equivalent" if passes else "different")
    return OutputComparison(
        **common,
        comparable=True,
        status=status,
        identical=identical,
        passes_tolerance=passes,
    )


def _compare_run(
    index: int,
    reference_run: RunRecord,
    fresh_run: RunRecord,
    tolerances: ReproduceTolerances,
) -> RunComparison:
    warnings: list[str] = []
    reference_status = reference_run.status.value
    fresh_status = fresh_run.status.value

    if not reference_run.succeeded or reference_run.result is None:
        return RunComparison(
            index=index,
            label=reference_run.label,
            reference_run_id=reference_run.run_id,
            fresh_run_id=fresh_run.run_id,
            reference_status=reference_status,
            fresh_status=fresh_status,
            comparable=False,
            identical=False,
            warnings=["the stored reference run did not succeed"],
        )
    if not fresh_run.succeeded or fresh_run.result is None:
        return RunComparison(
            index=index,
            label=reference_run.label,
            reference_run_id=reference_run.run_id,
            fresh_run_id=fresh_run.run_id,
            reference_status=reference_status,
            fresh_status=fresh_status,
            comparable=False,
            identical=False,
            warnings=[f"the fresh run did not succeed ({fresh_status})"],
        )

    reference_result = reference_run.result
    fresh_result = fresh_run.result
    reference_names = set(reference_result.output_names())
    fresh_names = set(fresh_result.output_names())
    shared = [name for name in reference_result.output_names() if name in fresh_names]
    missing = sorted(reference_names ^ fresh_names)

    outputs = [
        _compare_output(
            reference_run,
            fresh_run,
            reference_result.output(name),
            fresh_result.output(name),
            tolerances,
        )
        for name in shared
    ]
    if missing:
        warnings.append(f"outputs present on only one side: {', '.join(missing)}")

    comparable = bool(shared) and not missing and all(o.comparable for o in outputs)
    identical = comparable and all(o.status == "identical" for o in outputs)
    passes = comparable and all(bool(o.passes_tolerance) for o in outputs)
    return RunComparison(
        index=index,
        label=reference_run.label,
        reference_run_id=reference_run.run_id,
        fresh_run_id=fresh_run.run_id,
        reference_status=reference_status,
        fresh_status=fresh_status,
        comparable=comparable,
        identical=identical,
        passes_tolerance=passes if comparable else None,
        outputs=outputs,
        warnings=warnings,
    )


def _provenance(
    spec: ExperimentSpec, results: dict[str, Any]
) -> ProvenanceComparison:
    spec_hash_current = spec.content_hash()
    schema = build_model(spec.model_ref.model_id).describe()
    model_hash_current = schema.content_hash()
    environment_hash_current = fingerprint_hash(environment_fingerprint())

    spec_hash_stored = str(results.get("spec_hash") or "")
    model_hash_stored = str(results.get("model_hash") or "")
    environment_hash_stored = fingerprint_hash(results.get("environment") or {})

    differences: list[str] = []
    if spec_hash_stored and spec_hash_stored != spec_hash_current:
        differences.append("the stored specification hash differs from the re-loaded specification")
    if model_hash_stored and model_hash_stored != model_hash_current:
        differences.append("the model implementation fingerprint has changed since this experiment")
    if environment_hash_stored and environment_hash_stored != environment_hash_current:
        differences.append("the recorded environment fingerprint differs from the current environment")

    return ProvenanceComparison(
        spec_hash_stored=spec_hash_stored,
        spec_hash_current=spec_hash_current,
        spec_hash_match=bool(spec_hash_stored) and spec_hash_stored == spec_hash_current,
        model_hash_stored=model_hash_stored,
        model_hash_current=model_hash_current,
        model_hash_match=bool(model_hash_stored) and model_hash_stored == model_hash_current,
        environment_hash_stored=environment_hash_stored,
        environment_hash_current=environment_hash_current,
        environment_hash_match=environment_hash_stored == environment_hash_current,
        differences=differences,
    )


def reproduce_experiment(
    experiment_id: str,
    *,
    rtol: float,
    atol: float,
    store: ExperimentStore | None = None,
) -> ReproduceReport:
    """Re-execute a stored experiment and compare it to the stored reference.

    Read-only with respect to the store: the fresh execution is never persisted
    (``Runner`` does not write), so the original experiment, reference result,
    evidence manifest and artifacts are untouched. Raises :class:`ReproduceError`
    for an invalid request or unusable reference data; a failed *fresh execution*
    is reported as a report with ``verdict="execution_failed"``.
    """
    try:
        tolerances = ReproduceTolerances(rtol=rtol, atol=atol)
    except ValidationError as exc:
        raise ReproduceError(f"invalid tolerances: {exc}") from exc

    active_store = store if store is not None else default_store()
    loaded = active_store.load(experiment_id)  # KeyError -> not found
    results = loaded["results"]

    try:
        spec = ExperimentSpec.model_validate(loaded["spec"])
    except ValidationError as exc:
        raise ReproduceError(f"stored specification is not valid: {exc}") from exc

    stored_runs_raw = results.get("runs") or []
    if not stored_runs_raw:
        raise ReproduceError("stored experiment has no reference runs to compare against")
    try:
        stored_runs = [RunRecord.model_validate(run) for run in stored_runs_raw]
    except ValidationError as exc:
        raise ReproduceError(f"stored reference runs are not readable: {exc}") from exc

    baseline = stored_runs[0]
    if not baseline.succeeded or baseline.result is None:
        raise ReproduceError(
            "the stored reference baseline did not succeed; there is nothing to reproduce"
        )

    provenance = _provenance(spec, results)

    try:
        fresh = Runner().run(spec)
    except ExperimentValidationError as exc:
        raise ReproduceError(
            f"the stored specification no longer validates: {exc}"
        ) from exc

    run_comparisons = [
        _compare_run(index, stored_runs[index], fresh.runs[index], tolerances)
        for index in range(min(len(stored_runs), len(fresh.runs)))
    ]

    warnings = list(provenance.differences)
    count_mismatch = len(stored_runs) != len(fresh.runs)
    if count_mismatch:
        warnings.append(
            f"run count differs: stored {len(stored_runs)}, fresh {len(fresh.runs)}"
        )

    execution_ok = bool(fresh.runs) and all(run.succeeded for run in fresh.runs)
    any_incomparable = any(not comparison.comparable for comparison in run_comparisons)

    if not execution_ok:
        verdict: Verdict = "execution_failed"
        numerical: Verdict = "inconclusive"
    elif count_mismatch or any_incomparable or not run_comparisons:
        verdict = "inconclusive"
        numerical = "inconclusive"
    elif all(comparison.identical for comparison in run_comparisons):
        verdict = "identical"
        numerical = "identical"
    elif all(bool(comparison.passes_tolerance) for comparison in run_comparisons):
        verdict = "equivalent_within_tolerance"
        numerical = "equivalent_within_tolerance"
    else:
        verdict = "different"
        numerical = "different"

    return ReproduceReport(
        experiment_id=experiment_id,
        verdict=verdict,
        numerical=numerical,
        tolerances=tolerances,
        provenance=provenance,
        reference_run_ids=[run.run_id for run in stored_runs],
        fresh_run_ids=[run.run_id for run in fresh.runs],
        runs=run_comparisons,
        warnings=warnings,
        fresh_runs_persisted=False,
    )
