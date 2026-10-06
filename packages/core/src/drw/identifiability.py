"""Local parameter identifiability via a normalized finite-difference sensitivity.

An **on-demand** study that answers: *could the selected declared outputs locally
distinguish these parameters, and which parameter combinations are effectively
indistinguishable near this baseline?* It reuses the existing execution engine
(``Runner``) - no numerical engine is duplicated.

Method (local *structural* identifiability, near a baseline ``theta_0``)::

    J_ij = d y_i / d theta_j        (central finite differences)
         = ( y_i(theta_j + h_j) - y_i(theta_j - h_j) ) / (2 h_j)

A **normalized sensitivity matrix** removes units and output scales::

    S_ij = J_ij * range_j / s_i
    range_j = upper_j - lower_j                       (parameter scale)
    s_i     = max(|y_i(theta_0)|, central variation, floor)   (output scale)

The singular value decomposition of ``S`` then exposes the locally identifiable
directions. A **near-null right-singular vector** is a parameter combination that
produces little distinguishable change in the selected outputs.

What this is (and is not):

* **Local and structural.** It is a linearised statement about this baseline and
  these targets only. A passing result does **not** establish global
  identifiability, practical identifiability from noisy observations, model
  validity, causal relationships, parameter correctness, or empirical validation.
  Practical identifiability needs observations, a noise model and an experimental
  design; it belongs to the future calibration/validation milestone.
* **Continuous parameters only.** Only ``float`` parameters that declare bounds
  are valid targets; booleans, categoricals and other discrete parameters are
  rejected. Bounds are never invented.
* **Fail-closed.** Central differences need a valid perturbation on both sides of
  the baseline; a parameter at (or too close to) a bound, a failed/timed-out run,
  a missing/non-finite output, or an unusable output scale makes the study
  ``inconclusive``. Rank, condition number and conclusions are never fabricated.

References: Belsley, Kuh & Welsch (1980) collinearity diagnostics; standard
central-difference Jacobian estimation and scaled-sensitivity conditioning.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal

import numpy as np
from pydantic import BaseModel, ConfigDict, Field

from drw.execution.runner import Runner
from drw.schema.experiment import ExecutionSpec, ExperimentSpec
from drw.schema.model import ModelRef, ModelSchema, OutputSpec

__all__ = [
    "ABSOLUTE_STEP",
    "CONDITION_THRESHOLD",
    "CORRELATION_THRESHOLD",
    "DEFAULT_RANK_TOLERANCE",
    "DEFAULT_STEP_SCALE",
    "IDENTIFIABILITY_METHOD",
    "MAX_EVALUATIONS",
    "ROW_SCALE_FLOOR",
    "SCALAR_FEATURE",
    "TIMESERIES_FEATURES",
    "DirectionDiagnostic",
    "FactorDiagnostic",
    "IdentifiabilityError",
    "IdentifiabilityReport",
    "IdentifiabilityVerdict",
    "MatrixDiagnostics",
    "PairCorrelation",
    "TargetDiagnostic",
    "analyze_sensitivity_matrix",
    "default_factors",
    "default_targets",
    "estimate_evaluations",
    "identifiability",
    "identifiability_for_experiment",
]

IDENTIFIABILITY_METHOD = "central_finite_difference_sensitivity_svd"

#: Relative finite-difference step: ``h_j = max(step_scale * |theta_j|, absolute_step)``.
DEFAULT_STEP_SCALE = 1e-3
#: Absolute floor on the finite-difference step (handles ``theta_j == 0``).
ABSOLUTE_STEP = 1e-6
#: Numerical floor for the output row scale (avoids dividing by a meaningless zero).
ROW_SCALE_FLOOR = 1e-12
#: A singular value below ``rank_tolerance * sigma_max`` is treated as null. The
#: orchestration raises this to at least the central-difference noise floor (below)
#: so a direction weaker than the finite-difference accuracy is not claimed as
#: identifiable; the pure matrix analysis uses the raw value.
DEFAULT_RANK_TOLERANCE = 1e-12
#: Central differences carry a truncation/round-off floor; a direction weaker than
#: ``FD_NOISE_FACTOR * max_step**2`` (relative to the largest singular value) is
#: treated as unresolved. This is why a true degeneracy is reported as
#: rank-deficient even though the numerical smallest singular value is not exactly 0.
FD_NOISE_FACTOR = 10.0
#: Condition number above which the study is reported "ill-conditioned".
CONDITION_THRESHOLD = 1e6
#: |column correlation| above which a parameter pair is reported as collinear.
CORRELATION_THRESHOLD = 0.9
#: Correlations need at least this many informative targets to be meaningful (with
#: only two or three points, |correlation| is trivially 1).
MIN_CORRELATION_TARGETS = 4
#: |right-singular-vector weight| above which a parameter is "dominant" in a direction.
DIRECTION_WEIGHT_THRESHOLD = 0.5
#: A target whose normalized row norm is below this responds to nothing: uninformative.
TARGET_NORM_FLOOR = 1e-9
#: Hard cap on total model evaluations for one study (bounds local runtime).
MAX_EVALUATIONS = 4096

#: Fixed, explicitly disclosed feature set for a time-series output.
TIMESERIES_FEATURES: tuple[str, ...] = ("max", "min", "mean", "final", "argmax_t")
#: The single feature taken from a scalar output.
SCALAR_FEATURE = "value"

IdentifiabilityVerdict = Literal["well-conditioned", "ill-conditioned", "rank-deficient", "inconclusive"]


class IdentifiabilityError(ValueError):
    """Raised when an identifiability study cannot be requested or set up."""


# ---------------------------------------------------------------------------
# Report models (strict, machine-readable).
# ---------------------------------------------------------------------------


class TargetDiagnostic(BaseModel):
    """One analyzed target feature (a scalar output value or a time-series feature)."""

    model_config = ConfigDict(extra="forbid")

    output: str
    feature: str
    unit: str
    baseline_value: float | None = None
    scale: float | None = None
    informative: bool = True
    note: str | None = None


class FactorDiagnostic(BaseModel):
    """One analyzed parameter and the actual finite-difference perturbation used."""

    model_config = ConfigDict(extra="forbid")

    name: str
    unit: str = "dimensionless"
    baseline_value: float | None = None
    step: float | None = None
    lower: float | None = None
    upper: float | None = None
    plus_value: float | None = None
    minus_value: float | None = None
    valid: bool = True
    note: str | None = None


class DirectionDiagnostic(BaseModel):
    """One right-singular direction of the normalized sensitivity matrix."""

    model_config = ConfigDict(extra="forbid")

    index: int
    singular_value: float
    condition_index: float | None = None
    problematic: bool = False
    dominant: list[str] = Field(default_factory=list)
    weights: dict[str, float] = Field(default_factory=dict)


class PairCorrelation(BaseModel):
    """|correlation| of two normalized sensitivity columns, above the threshold."""

    model_config = ConfigDict(extra="forbid")

    first: str
    second: str
    correlation: float


class MatrixDiagnostics(BaseModel):
    """Pure SVD-based diagnostics for a normalized sensitivity matrix."""

    model_config = ConfigDict(extra="forbid")

    dimensions: int
    n_targets: int
    singular_values: list[float] = Field(default_factory=list)
    numerical_rank: int = 0
    condition_number: float | None = None
    directions: list[DirectionDiagnostic] = Field(default_factory=list)
    factor_correlations: list[PairCorrelation] = Field(default_factory=list)
    verdict: IdentifiabilityVerdict
    inconclusive: bool = False
    reasons: list[str] = Field(default_factory=list)


class IdentifiabilityReport(BaseModel):
    """A machine-readable local-identifiability report (diagnostics, not truth)."""

    model_config = ConfigDict(extra="forbid")

    model_id: str
    experiment_id: str | None = None
    method: str = IDENTIFIABILITY_METHOD
    factors: list[str]
    factors_detail: list[FactorDiagnostic] = Field(default_factory=list)
    targets: list[TargetDiagnostic] = Field(default_factory=list)
    dimensions: int
    n_targets: int
    step_scale: float = DEFAULT_STEP_SCALE
    absolute_step: float = ABSOLUTE_STEP
    rank_tolerance: float = DEFAULT_RANK_TOLERANCE
    condition_threshold: float = CONDITION_THRESHOLD
    correlation_threshold: float = CORRELATION_THRESHOLD
    evaluations_requested: int = 0
    evaluations_completed: int = 0
    singular_values: list[float] = Field(default_factory=list)
    numerical_rank: int | None = None
    condition_number: float | None = None
    directions: list[DirectionDiagnostic] = Field(default_factory=list)
    factor_correlations: list[PairCorrelation] = Field(default_factory=list)
    verdict: IdentifiabilityVerdict
    inconclusive: bool
    reasons: list[str] = Field(default_factory=list)
    normalized: bool = True
    local_only: bool = True
    note: str | None = None


# ---------------------------------------------------------------------------
# Pure mathematics: SVD-based diagnostics.
# ---------------------------------------------------------------------------


def _pair_correlations(
    matrix: np.ndarray, factor_names: Sequence[str], threshold: float
) -> list[PairCorrelation]:
    if matrix.shape[0] < MIN_CORRELATION_TARGETS:
        # With fewer than MIN_CORRELATION_TARGETS informative targets the sample
        # correlation is trivially +/-1 and carries no information.
        return []
    pairs: list[PairCorrelation] = []
    for a in range(len(factor_names)):
        for b in range(a + 1, len(factor_names)):
            left, right = matrix[:, a], matrix[:, b]
            if float(np.std(left)) == 0.0 or float(np.std(right)) == 0.0:
                continue  # a degenerate column has no correlation to report
            correlation = float(np.corrcoef(left, right)[0, 1])
            if np.isfinite(correlation) and abs(correlation) >= threshold:
                pairs.append(
                    PairCorrelation(
                        first=factor_names[a], second=factor_names[b], correlation=correlation
                    )
                )
    pairs.sort(key=lambda pair: abs(pair.correlation), reverse=True)
    return pairs


def analyze_sensitivity_matrix(
    matrix: Sequence[Sequence[float]],
    *,
    factor_names: Sequence[str],
    target_labels: Sequence[str] = (),
    rank_tolerance: float = DEFAULT_RANK_TOLERANCE,
    condition_threshold: float = CONDITION_THRESHOLD,
    correlation_threshold: float = CORRELATION_THRESHOLD,
) -> MatrixDiagnostics:
    """Diagnose a normalized sensitivity matrix (one column per factor).

    Pure function: no model is executed. Returns the singular values, numerical
    rank, condition number, right-singular directions (including the null space
    when there are fewer targets than factors) and the largest collinear pairs.
    """
    names = list(factor_names)
    dimension = len(names)
    array = np.asarray(matrix, dtype=float)
    if array.size == 0:
        return MatrixDiagnostics(
            dimensions=dimension,
            n_targets=0,
            verdict="inconclusive",
            inconclusive=True,
            reasons=["no informative target responds to the selected factors"],
        )
    if array.ndim != 2 or array.shape[1] != dimension:
        raise IdentifiabilityError("sensitivity matrix must have one column per factor")
    n_targets = int(array.shape[0])
    if not np.all(np.isfinite(array)):
        return MatrixDiagnostics(
            dimensions=dimension,
            n_targets=n_targets,
            verdict="inconclusive",
            inconclusive=True,
            reasons=["the sensitivity matrix contains non-finite values"],
        )

    # full_matrices=True keeps the right-singular vectors that span the null space
    # (dimension p - rank), so a study with more factors than targets still exposes
    # the non-identifiable combinations instead of hiding them.
    _u, sigma, vh = np.linalg.svd(array, full_matrices=True)
    sigma_full = np.zeros(dimension, dtype=float)
    sigma_full[: sigma.size] = sigma
    sigma_max = float(sigma_full[0]) if dimension else 0.0
    if not np.isfinite(sigma_max) or sigma_max <= 0.0:
        return MatrixDiagnostics(
            dimensions=dimension,
            n_targets=n_targets,
            singular_values=[float(value) for value in sigma_full],
            verdict="inconclusive",
            inconclusive=True,
            reasons=["the sensitivity matrix has no measurable magnitude"],
        )

    tolerance = rank_tolerance * sigma_max
    numerical_rank = int(np.sum(sigma_full > tolerance))
    condition_number = (
        float(sigma_max / sigma_full[-1]) if float(sigma_full[-1]) > tolerance else None
    )

    directions: list[DirectionDiagnostic] = []
    for index in range(dimension):
        value = float(sigma_full[index])
        condition_index = float(sigma_max / value) if value > tolerance else None
        weights = {name: float(abs(vh[index, column])) for column, name in enumerate(names)}
        dominant = [name for name, weight in weights.items() if weight >= DIRECTION_WEIGHT_THRESHOLD]
        problematic = value <= tolerance or (
            condition_index is not None and condition_index > condition_threshold
        )
        directions.append(
            DirectionDiagnostic(
                index=index,
                singular_value=value,
                condition_index=condition_index,
                problematic=problematic,
                dominant=dominant,
                weights=weights,
            )
        )

    if numerical_rank < dimension:
        verdict: IdentifiabilityVerdict = "rank-deficient"
    elif condition_number is not None and condition_number > condition_threshold:
        verdict = "ill-conditioned"
    else:
        verdict = "well-conditioned"

    return MatrixDiagnostics(
        dimensions=dimension,
        n_targets=n_targets,
        singular_values=[float(value) for value in sigma_full],
        numerical_rank=numerical_rank,
        condition_number=condition_number,
        directions=directions,
        factor_correlations=_pair_correlations(array, names, correlation_threshold),
        verdict=verdict,
    )


# ---------------------------------------------------------------------------
# Targets.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _Target:
    output: str
    kind: str
    feature: str
    unit: str
    label: str


def _target_label(output: str, feature: str) -> str:
    return output if feature == SCALAR_FEATURE else f"{output}:{feature}"


def _output_targets(output: OutputSpec) -> list[_Target]:
    if output.kind == "scalar":
        return [_Target(output.name, "scalar", SCALAR_FEATURE, output.unit, output.name)]
    return [
        _Target(output.name, "timeseries", feature, output.unit, _target_label(output.name, feature))
        for feature in TIMESERIES_FEATURES
    ]


def default_targets(schema: ModelSchema, outputs: Sequence[str] | None = None) -> list[_Target]:
    """Resolve the analyzed targets: every declared scalar/time-series output.

    ``outputs`` selects *outputs* (not individual features); each selected output
    expands to its scalar value or its fixed five time-series features.
    """
    declared = {output.name: output for output in schema.outputs}
    if outputs is None:
        chosen = [output for output in schema.outputs if output.kind in ("scalar", "timeseries")]
    else:
        chosen = []
        for name in outputs:
            output = declared.get(name)
            if output is None:
                raise IdentifiabilityError(f"unknown output {name!r}")
            if output.kind not in ("scalar", "timeseries"):
                raise IdentifiabilityError(
                    f"output {name!r} is {output.kind}; only scalar and time-series outputs are supported"
                )
            chosen.append(output)
    targets: list[_Target] = []
    for output in chosen:
        targets.extend(_output_targets(output))
    return targets


def default_factors(schema: ModelSchema) -> list[str]:
    """Factors chosen when the caller supplies none: bounded continuous parameters.

    Only ``float`` parameters that declare bounds are valid identifiability
    targets; discrete parameters (int/bool/categorical) are excluded.
    """
    return [
        parameter.name
        for parameter in schema.parameters
        if parameter.type == "float" and parameter.has_bounds()
    ]


def estimate_evaluations(n_factors: int) -> int:
    """Model evaluations for one study: a central pair per factor plus a baseline.

    Note: a single model evaluation produces *every* selected target feature, so
    the count does not multiply by the number of targets.
    """
    return 2 * int(n_factors) + 1


# ---------------------------------------------------------------------------
# Execution helpers.
# ---------------------------------------------------------------------------


def _extract_feature(output: Any, feature: str, label: str) -> float:
    values = np.asarray(getattr(output, "values", None), dtype=float).reshape(-1)
    if values.size == 0 or not np.all(np.isfinite(values)):
        raise IdentifiabilityError(f"target {label!r} has non-finite or empty values")
    if feature == "value":
        if values.size != 1:
            raise IdentifiabilityError(f"scalar target {label!r} does not hold a single value")
        return float(values[0])
    if feature == "max":
        return float(np.max(values))
    if feature == "min":
        return float(np.min(values))
    if feature == "mean":
        return float(np.mean(values))
    if feature == "final":
        return float(values[-1])
    if feature == "argmax_t":
        axis = getattr(output, "axis", None)
        if axis is None:
            raise IdentifiabilityError(f"target {label!r} has no axis for 'argmax_t'")
        axis_values = np.asarray(axis, dtype=float).reshape(-1)
        if axis_values.shape != values.shape or not np.all(np.isfinite(axis_values)):
            raise IdentifiabilityError(f"target {label!r} has an invalid axis for 'argmax_t'")
        return float(axis_values[int(np.argmax(values))])
    raise IdentifiabilityError(f"unknown feature {feature!r}")  # pragma: no cover - fixed set


def _target_value(record: Any, target: _Target) -> float:
    if target.kind == "scalar":
        metrics = getattr(record, "metrics", None) or {}
        if target.output in metrics:
            value = float(metrics[target.output])
            if not np.isfinite(value):
                raise IdentifiabilityError(f"target {target.label!r} is non-finite")
            return value
    result = getattr(record, "result", None)
    outputs = getattr(result, "outputs", None) if result is not None else None
    if not outputs or target.output not in outputs:
        raise IdentifiabilityError(f"target {target.label!r} is missing from the result")
    return _extract_feature(outputs[target.output], target.feature, target.label)


def _extract(record: Any, targets: Sequence[_Target]) -> tuple[dict[str, float] | None, str | None]:
    if not getattr(record, "succeeded", False):
        return None, ("run_timed_out" if getattr(record, "timed_out", False) else "run_failed")
    values: dict[str, float] = {}
    for target in targets:
        try:
            values[target.label] = _target_value(record, target)
        except IdentifiabilityError as error:
            return None, str(error)
    return values, None


def _make_spec(schema: ModelSchema, inputs: Mapping[str, Any]) -> ExperimentSpec:
    return ExperimentSpec(
        name="identifiability",
        hypothesis="Local identifiability sensitivity evaluation.",
        model_ref=ModelRef(model_id=schema.model_id, version=schema.version),
        baseline=dict(inputs),
        factors=(),
        outputs=(),
        analyses=(),
        execution=ExecutionSpec(isolation="subprocess"),
    )


def _inconclusive(
    *,
    schema: ModelSchema,
    factors: Sequence[str],
    factors_detail: Sequence[FactorDiagnostic],
    targets: Sequence[_Target],
    step_scale: float,
    absolute_step: float,
    rank_tolerance: float,
    condition_threshold: float,
    correlation_threshold: float,
    reasons: Sequence[str],
    evaluations_requested: int = 0,
    evaluations_completed: int = 0,
) -> IdentifiabilityReport:
    return IdentifiabilityReport(
        model_id=schema.model_id,
        factors=list(factors),
        factors_detail=list(factors_detail),
        targets=[
            TargetDiagnostic(output=t.output, feature=t.feature, unit=t.unit) for t in targets
        ],
        dimensions=len(factors),
        n_targets=len(targets),
        step_scale=step_scale,
        absolute_step=absolute_step,
        rank_tolerance=rank_tolerance,
        condition_threshold=condition_threshold,
        correlation_threshold=correlation_threshold,
        evaluations_requested=evaluations_requested,
        evaluations_completed=evaluations_completed,
        verdict="inconclusive",
        inconclusive=True,
        reasons=list(reasons),
    )


# ---------------------------------------------------------------------------
# Orchestration.
# ---------------------------------------------------------------------------


def identifiability(
    schema: ModelSchema,
    *,
    baseline: Mapping[str, Any],
    factors: Sequence[str],
    outputs: Sequence[str] | None = None,
    step_scale: float = DEFAULT_STEP_SCALE,
    absolute_step: float = ABSOLUTE_STEP,
    seed: int = 0,
    runner: Runner | None = None,
    journal: Any | None = None,
    rank_tolerance: float = DEFAULT_RANK_TOLERANCE,
    condition_threshold: float = CONDITION_THRESHOLD,
    correlation_threshold: float = CORRELATION_THRESHOLD,
    max_evaluations: int = MAX_EVALUATIONS,
) -> IdentifiabilityReport:
    """Run a local identifiability study for a model + baseline (fail-closed).

    ``seed`` is accepted for interface parity with the other on-demand studies;
    the central-difference study is deterministic and does not consume randomness.
    """
    names = list(factors)
    if not names:
        raise IdentifiabilityError("at least one factor is required")
    if len(set(names)) != len(names):
        raise IdentifiabilityError("duplicate factors are not allowed")
    if step_scale <= 0:
        raise IdentifiabilityError("step_scale must be positive")
    if absolute_step <= 0:
        raise IdentifiabilityError("absolute_step must be positive")

    targets = default_targets(schema, outputs)
    if not targets:
        raise IdentifiabilityError("no scalar or time-series output is available to analyze")

    plan: list[FactorDiagnostic] = []
    invalid: list[str] = []
    for name in names:
        if not schema.has_parameter(name):
            raise IdentifiabilityError(f"unknown factor {name!r}")
        parameter = schema.parameter(name)
        if parameter.type != "float":
            raise IdentifiabilityError(
                f"factor {name!r} is not a continuous parameter ({parameter.type}); "
                "identifiability requires continuous numeric parameters"
            )
        if not parameter.has_bounds():
            raise IdentifiabilityError(
                f"factor {name!r} has no declared bounds; identifiability needs a range"
            )
        value = baseline.get(name)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise IdentifiabilityError(f"baseline does not provide a numeric value for {name!r}")
        theta = float(value)
        lower, upper = float(parameter.lower), float(parameter.upper)
        step = max(step_scale * abs(theta), absolute_step)
        plus, minus = theta + step, theta - step
        feasible = step > 0 and minus >= lower and plus <= upper
        note = None
        if not feasible:
            note = (
                f"central difference needs minus={minus:g} >= lower={lower:g} and "
                f"plus={plus:g} <= upper={upper:g} (requested step {step:g})"
            )
            invalid.append(note)
        plan.append(
            FactorDiagnostic(
                name=name,
                unit=parameter.unit,
                baseline_value=theta,
                step=step,
                lower=lower,
                upper=upper,
                plus_value=plus,
                minus_value=minus,
                valid=feasible,
                note=note,
            )
        )

    evaluations = estimate_evaluations(len(names))
    if evaluations > max_evaluations:
        raise IdentifiabilityError(
            f"study would run {evaluations} evaluations (limit {max_evaluations}); "
            "reduce the number of factors"
        )

    # A central-difference Jacobian cannot resolve a direction weaker than its own
    # noise floor, so the effective rank tolerance is floored accordingly.
    max_step = max(float(diagnostic.step) for diagnostic in plan)
    effective_rank_tolerance = max(rank_tolerance, FD_NOISE_FACTOR * max_step * max_step)

    if invalid:
        return _inconclusive(
            schema=schema,
            factors=names,
            factors_detail=plan,
            targets=targets,
            step_scale=step_scale,
            absolute_step=absolute_step,
            rank_tolerance=effective_rank_tolerance,
            condition_threshold=condition_threshold,
            correlation_threshold=correlation_threshold,
            reasons=[
                f"factor {diagnostic.name!r} cannot be perturbed: {diagnostic.note}"
                for diagnostic in plan
                if not diagnostic.valid
            ],
            evaluations_requested=evaluations,
            evaluations_completed=0,
        )

    active = runner or Runner()
    # Evaluation order: baseline, then (plus, minus) for each factor.
    points: list[Mapping[str, Any]] = [dict(baseline)]
    for diagnostic in plan:
        points.append({**baseline, diagnostic.name: float(diagnostic.plus_value)})
        points.append({**baseline, diagnostic.name: float(diagnostic.minus_value)})

    results: list[dict[str, float] | None] = []
    failures: dict[str, int] = {}
    for index, inputs in enumerate(points, start=1):
        record = active.run(_make_spec(schema, inputs)).runs[0]
        values, reason = _extract(record, targets)
        if reason is not None:
            failures[reason] = failures.get(reason, 0) + 1
        results.append(values)
        if journal is not None:
            journal.append(
                "run_completed",
                index=index,
                total_runs=evaluations,
                status=record.status.value,
                timed_out=record.timed_out,
            )

    if any(values is None for values in results):
        return _inconclusive(
            schema=schema,
            factors=names,
            factors_detail=plan,
            targets=targets,
            step_scale=step_scale,
            absolute_step=absolute_step,
            rank_tolerance=effective_rank_tolerance,
            condition_threshold=condition_threshold,
            correlation_threshold=correlation_threshold,
            reasons=[
                f"{count} evaluation(s) {reason}" for reason, count in sorted(failures.items())
            ]
            or ["an evaluation did not produce a usable target value"],
            evaluations_requested=evaluations,
            evaluations_completed=sum(1 for values in results if values is not None),
        )

    baseline_values: dict[str, float] = results[0]  # type: ignore[assignment]
    plus_all = [results[1 + 2 * offset] for offset in range(len(plan))]
    minus_all = [results[2 + 2 * offset] for offset in range(len(plan))]
    widths = np.array([float(d.upper) - float(d.lower) for d in plan], dtype=float)

    # Central-difference Jacobian J[i, j] = d y_i / d theta_j.
    raw = np.array(
        [
            [
                (plus_all[offset][target.label] - minus_all[offset][target.label])
                / (2 * float(plan[offset].step))
                for offset in range(len(plan))
            ]
            for target in targets
        ],
        dtype=float,
    )

    target_detail: list[TargetDiagnostic] = []
    rows: list[np.ndarray] = []
    for row_index, target in enumerate(targets):
        baseline_value = baseline_values[target.label]
        # The output scale is the baseline magnitude, floored by the observed
        # variation (a target whose baseline is exactly zero - e.g. an argmax_t at
        # the start of the window - still has a meaningful, non-exploding scale).
        variation = max(
            abs(plus_all[offset][target.label] - minus_all[offset][target.label])
            for offset in range(len(plan))
        )
        scale = max(abs(baseline_value), variation)
        if not np.isfinite(scale) or scale <= ROW_SCALE_FLOOR:
            # A constant (zero-scale) target carries no information; it is excluded
            # rather than failing the whole study, and it is never fabricated.
            target_detail.append(
                TargetDiagnostic(
                    output=target.output,
                    feature=target.feature,
                    unit=target.unit,
                    baseline_value=baseline_value,
                    scale=float(scale),
                    informative=False,
                    note="constant target: no baseline magnitude or variation to scale",
                )
            )
            continue
        # Normalize parameters by their declared range and the output by its scale.
        normalized = (raw[row_index, :] * widths) / scale
        informative = float(np.linalg.norm(normalized)) > TARGET_NORM_FLOOR
        target_detail.append(
            TargetDiagnostic(
                output=target.output,
                feature=target.feature,
                unit=target.unit,
                baseline_value=baseline_value,
                scale=float(scale),
                informative=informative,
                note=None if informative else "no local response to the selected factors",
            )
        )
        if informative:
            rows.append(normalized)

    informative_labels = [
        _target_label(detail.output, detail.feature)
        for detail in target_detail
        if detail.informative
    ]
    matrix = np.vstack(rows) if rows else np.zeros((0, len(names)))
    diagnostics = analyze_sensitivity_matrix(
        matrix,
        factor_names=names,
        target_labels=informative_labels,
        rank_tolerance=effective_rank_tolerance,
        condition_threshold=condition_threshold,
        correlation_threshold=correlation_threshold,
    )

    note = (
        "Local (linearised) structural identifiability at this baseline and these "
        "targets. This is not global identifiability, not practical identifiability "
        "from noisy observations, and not a statement that the model is valid."
    )
    if len(names) > diagnostics.n_targets:
        note += (
            f" With {len(names)} parameters and {diagnostics.n_targets} informative "
            "target(s), the system is under-determined: at most "
            f"{diagnostics.n_targets} direction(s) can be distinguished."
        )

    return IdentifiabilityReport(
        model_id=schema.model_id,
        factors=names,
        factors_detail=plan,
        targets=target_detail,
        dimensions=len(names),
        n_targets=diagnostics.n_targets,
        step_scale=step_scale,
        absolute_step=absolute_step,
        rank_tolerance=effective_rank_tolerance,
        condition_threshold=condition_threshold,
        correlation_threshold=correlation_threshold,
        evaluations_requested=evaluations,
        evaluations_completed=sum(1 for values in results if values is not None),
        singular_values=diagnostics.singular_values,
        numerical_rank=diagnostics.numerical_rank,
        condition_number=diagnostics.condition_number,
        directions=diagnostics.directions,
        factor_correlations=diagnostics.factor_correlations,
        verdict=diagnostics.verdict,
        inconclusive=diagnostics.inconclusive,
        reasons=diagnostics.reasons,
        note=note,
    )


def identifiability_for_experiment(
    experiment_id: str,
    store: Any,
    *,
    factors: Sequence[str] | None = None,
    outputs: Sequence[str] | None = None,
    step_scale: float = DEFAULT_STEP_SCALE,
    absolute_step: float = ABSOLUTE_STEP,
    seed: int = 0,
    runner: Runner | None = None,
    journal: Any | None = None,
    rank_tolerance: float = DEFAULT_RANK_TOLERANCE,
    condition_threshold: float = CONDITION_THRESHOLD,
    correlation_threshold: float = CORRELATION_THRESHOLD,
    max_evaluations: int = MAX_EVALUATIONS,
) -> IdentifiabilityReport:
    """Run a local identifiability study for a stored experiment (read-only)."""
    from drw.models.registry import build_model
    from drw.schema.experiment import ExperimentSpec as _Spec

    loaded = store.load(experiment_id)
    spec = _Spec.model_validate(loaded["spec"])
    schema = build_model(spec.model_ref.model_id).describe()
    chosen_factors = list(factors) if factors else default_factors(schema)
    report = identifiability(
        schema,
        baseline=dict(spec.baseline),
        factors=chosen_factors,
        outputs=outputs,
        step_scale=step_scale,
        absolute_step=absolute_step,
        seed=seed,
        runner=runner,
        journal=journal,
        rank_tolerance=rank_tolerance,
        condition_threshold=condition_threshold,
        correlation_threshold=correlation_threshold,
        max_evaluations=max_evaluations,
    )
    return report.model_copy(update={"experiment_id": experiment_id})
