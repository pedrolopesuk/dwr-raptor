"""Global variance-based sensitivity (Sobol' first- and total-order indices).

An **on-demand** study that estimates how much of the variance of a declared
scalar output is attributable to each independent input factor. It reuses the
existing execution engine (`Runner`) and the seeded quasi-Monte Carlo sampler
(`scipy.stats.qmc.Sobol`) - no numerical engine is duplicated.

Estimand (for independent inputs ``X_1..X_d`` and output ``Y = f(X)``)::

    S_i   = Var_{X_i}( E[Y | X_i] ) / Var(Y)          (first order)
    S_Ti  = 1 - Var_{X_-i}( E[Y | X_-i] ) / Var(Y)    (total order)

``S_i`` is the share of variance explained by ``X_i`` alone; ``S_Ti`` includes its
interactions with the other inputs (``S_Ti - S_i`` is the interaction share).

Sampling design (Saltelli coupled design)::

    A, B  : the two d-column halves of one 2d-dimensional N-point sample
            (seeded Sobol' sequence) - mutually independent, coupled to AB_i
    AB_i  : A with column i replaced by B[:, i]
    evaluations = N * (d + 2)

Estimators (documented conventions)::

    yA = f(A), yB = f(B), yAB_i = f(AB_i)
    V      = var([yA, yB], ddof=1)
    V_i    = (1/N)  * sum_j yB_j * (yAB_i_j - yA_j)          # Saltelli et al. 2010
    S_i    = V_i / V
    V_Ti   = (1/2N) * sum_j (yA_j - yAB_i_j) ** 2            # Jansen 1999
    S_Ti   = V_Ti / V

Limitations that are surfaced, never hidden:

* **Finite-sample estimates are not clipped.** ``S_i`` may be slightly negative,
  exceed 1, or exceed ``S_Ti``; theoretical relationships (``0 <= S_i <= S_Ti``,
  ``sum S_i <= 1``) hold only in the limit. The raw estimates are reported.
* **Convergence is not proven by any single sample size.** A percentile bootstrap
  interval is reported as a diagnostic only.
* **Independence is assumed.** Correlated real-world inputs invalidate these
  indices; this is not a correlated-input method.
* The study is **not causal** and is not scientific validation.

Failures are fail-closed: because the estimators require complete paired
``A``/``B``/``AB_i`` rows, any failed/timed-out/missing/non-finite evaluation makes
the whole study ``inconclusive`` (indices are ``null``) with explicit counts and
reasons - indices are never computed from a broken design.

References: Sobol' (2001); Saltelli et al. (2010), Comput. Phys. Commun. 181:259;
Jansen (1999).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

import numpy as np
from pydantic import BaseModel, ConfigDict, Field
from scipy.stats import qmc

from drw.execution.runner import Runner
from drw.schema.experiment import ExecutionSpec, ExperimentSpec
from drw.schema.model import ModelRef, ModelSchema

__all__ = [
    "DEFAULT_BOOTSTRAP",
    "DEFAULT_SAMPLE_COUNT",
    "ESTIMATOR",
    "MAX_EVALUATIONS",
    "FactorSensitivity",
    "GlobalSensitivityError",
    "SobolReport",
    "default_factors",
    "sobol_indices",
    "sobol_indices_for_experiment",
]

ESTIMATOR = "saltelli2010_first_order+jansen1999_total_order"

DEFAULT_SAMPLE_COUNT = 32  # power of two; N*(d+2) evaluations
DEFAULT_BOOTSTRAP = 100
#: Hard cap on total model evaluations for one study (bounds local runtime).
MAX_EVALUATIONS = 4096


class GlobalSensitivityError(ValueError):
    """Raised when a global-sensitivity study cannot be requested or set up."""


class FactorSensitivity(BaseModel):
    """First- and total-order index estimates for one factor."""

    model_config = ConfigDict(extra="forbid")

    name: str
    s1: float | None = None
    st: float | None = None
    s1_ci: tuple[float, float] | None = None
    st_ci: tuple[float, float] | None = None


class SobolReport(BaseModel):
    """A machine-readable global-sensitivity report (estimates, not truth)."""

    model_config = ConfigDict(extra="forbid")

    model_id: str
    output: str
    estimator: str = ESTIMATOR
    sample_count: int
    seed: int
    dimensions: int
    factors: list[str]
    evaluations_requested: int
    evaluations_completed: int
    variance: float | None = None
    inconclusive: bool
    reasons: list[str] = Field(default_factory=list)
    results: list[FactorSensitivity] = Field(default_factory=list)
    bootstrap_resamples: int = DEFAULT_BOOTSTRAP
    independent_inputs_assumed: bool = True
    note: str | None = None


def saltelli_design(
    dimension: int, sample_count: int, seed: int
) -> tuple[np.ndarray, np.ndarray, list[np.ndarray]]:
    """Return unit-cube ``A``, ``B`` and ``AB_i`` matrices (coupled design).

    ``A`` and ``B`` are the two halves of a single ``2 * dimension``-dimensional
    quasi-random sample (the standard Saltelli construction): this keeps the two
    matrices independent, whereas splitting one ``dimension``-dimensional sequence
    into two consecutive blocks makes them nearly collinear.
    """
    sampler = qmc.Sobol(d=2 * dimension, scramble=True, seed=seed)
    base = sampler.random(sample_count)
    a = base[:, :dimension]
    b = base[:, dimension:]
    ab = []
    for index in range(dimension):
        hybrid = a.copy()
        hybrid[:, index] = b[:, index]
        ab.append(hybrid)
    return a, b, ab


def _variance(y_a: np.ndarray, y_b: np.ndarray) -> float:
    return float(np.var(np.concatenate([y_a, y_b]), ddof=1))


def first_order_indices(
    y_a: np.ndarray, y_b: np.ndarray, y_ab: Sequence[np.ndarray], variance: float
) -> np.ndarray:
    """Saltelli et al. (2010) first-order estimators."""
    values = np.array(
        [float(np.mean(y_b * (hybrid - y_a))) / variance for hybrid in y_ab], dtype=float
    )
    return values


def total_order_indices(
    y_a: np.ndarray, y_ab: Sequence[np.ndarray], variance: float
) -> np.ndarray:
    """Jansen (1999) total-order estimators."""
    return np.array(
        [float(np.mean((y_a - hybrid) ** 2) / 2.0) / variance for hybrid in y_ab], dtype=float
    )


def _bootstrap(
    y_a: np.ndarray, y_b: np.ndarray, y_ab: list[np.ndarray], resamples: int, seed: int
) -> tuple[list[tuple[float, float] | None], list[tuple[float, float] | None]]:
    """Percentile bootstrap intervals for (S_i, S_Ti); a diagnostic, not proof."""
    rng = np.random.default_rng(seed ^ 0x5EED)
    n = y_a.shape[0]
    s1 = np.full((resamples, len(y_ab)), np.nan)
    st = np.full((resamples, len(y_ab)), np.nan)
    for replicate in range(resamples):
        idx = rng.integers(0, n, n)
        ya2, yb2 = y_a[idx], y_b[idx]
        ab2 = [hybrid[idx] for hybrid in y_ab]
        variance = _variance(ya2, yb2)
        if not np.isfinite(variance) or variance <= 0.0:
            continue
        s1[replicate] = first_order_indices(ya2, yb2, ab2, variance)
        st[replicate] = total_order_indices(ya2, ab2, variance)

    def interval(column: np.ndarray) -> tuple[float, float] | None:
        finite = column[np.isfinite(column)]
        if finite.size < max(2, resamples // 10):
            return None
        low, high = np.percentile(finite, [2.5, 97.5])
        return (float(low), float(high))

    return [interval(s1[:, i]) for i in range(len(y_ab))], [
        interval(st[:, i]) for i in range(len(y_ab))
    ]


def _estimate(
    y_a: np.ndarray,
    y_b: np.ndarray,
    y_ab: list[np.ndarray],
    names: list[str],
    *,
    bootstrap_resamples: int,
    seed: int,
) -> tuple[float | None, list[FactorSensitivity], list[str]]:
    """Compute indices + CIs; return (variance, results, reasons)."""
    variance = _variance(y_a, y_b)
    if not np.isfinite(variance) or variance <= 0.0:
        return (
            None,
            [FactorSensitivity(name=name) for name in names],
            ["output variance is zero or non-finite; the indices are undefined"],
        )
    s1 = first_order_indices(y_a, y_b, y_ab, variance)
    st = total_order_indices(y_a, y_ab, variance)
    s1_ci, st_ci = _bootstrap(y_a, y_b, y_ab, bootstrap_resamples, seed)
    results = [
        FactorSensitivity(
            name=names[index], s1=float(s1[index]), st=float(st[index]),
            s1_ci=s1_ci[index], st_ci=st_ci[index],
        )
        for index in range(len(names))
    ]
    return variance, results, []


def default_factors(schema: ModelSchema) -> list[str]:
    """Factors chosen when the caller supplies none.

    The canonical rule (shared by the core and the bridge): every numeric
    parameter that declares bounds. If none does, fall back to every numeric
    parameter name - ``_factor_bounds`` then rejects the study with a clear
    "no declared bounds" error, which is the intended behaviour.
    """
    bounded = [parameter.name for parameter in schema.parameters if parameter.has_bounds()]
    if bounded:
        return bounded
    return [parameter.name for parameter in schema.parameters if parameter.type in ("float", "int")]


def _factor_bounds(schema: ModelSchema, names: Sequence[str]) -> tuple[np.ndarray, np.ndarray]:
    lower, upper = [], []
    for name in names:
        if not schema.has_parameter(name):
            raise GlobalSensitivityError(f"unknown factor {name!r}")
        parameter = schema.parameter(name)
        if parameter.type not in ("float", "int"):
            raise GlobalSensitivityError(f"factor {name!r} is not numeric ({parameter.type})")
        if not parameter.has_bounds():
            raise GlobalSensitivityError(
                f"factor {name!r} has no declared bounds; global sensitivity needs a range"
            )
        lower.append(float(parameter.lower))
        upper.append(float(parameter.upper))
    return np.array(lower, dtype=float), np.array(upper, dtype=float)


def _evaluate(
    schema: ModelSchema,
    baseline: Mapping[str, Any],
    output: str,
    points: Sequence[Mapping[str, float]],
    runner: Runner | None,
    journal: Any | None,
    total: int,
) -> tuple[list[float | None], dict[str, int]]:
    active = runner or Runner()
    model_ref = ModelRef(model_id=schema.model_id, version=schema.version)
    values: list[float | None] = []
    failures: dict[str, int] = {}
    for index, overrides in enumerate(points, start=1):
        inputs = dict(baseline)
        inputs.update(overrides)
        spec = ExperimentSpec(
            name="global-sensitivity",
            hypothesis=f"Global sensitivity evaluation {index}",
            model_ref=model_ref,
            baseline=inputs,
            factors=(),
            outputs=(output,),
            analyses=(),
            execution=ExecutionSpec(isolation="subprocess"),
        )
        record = active.run(spec).runs[0]
        value: float | None = None
        if not record.succeeded:
            reason = "run_timed_out" if record.timed_out else "run_failed"
        elif output not in record.metrics:
            reason = "output_missing"
        elif not np.isfinite(record.metrics[output]):
            reason = "non_finite"
        else:
            reason = ""
            value = float(record.metrics[output])
        if reason:
            failures[reason] = failures.get(reason, 0) + 1
        values.append(value)
        if journal is not None:
            journal.append(
                "run_completed", index=index, total_runs=total,
                status=record.status.value, timed_out=record.timed_out,
            )
    return values, failures


def sobol_indices(
    schema: ModelSchema,
    *,
    baseline: Mapping[str, Any],
    output: str,
    factors: Sequence[str],
    sample_count: int = DEFAULT_SAMPLE_COUNT,
    seed: int = 0,
    runner: Runner | None = None,
    journal: Any | None = None,
    bootstrap_resamples: int = DEFAULT_BOOTSTRAP,
    max_evaluations: int = MAX_EVALUATIONS,
) -> SobolReport:
    """Run the coupled design and estimate first-/total-order Sobol' indices."""
    names = list(factors)
    if not names:
        raise GlobalSensitivityError("at least one factor is required")
    if len(set(names)) != len(names):
        raise GlobalSensitivityError("duplicate factors are not allowed")
    if sample_count < 2:
        raise GlobalSensitivityError("sample_count must be at least 2")
    if seed < 0:
        raise GlobalSensitivityError("seed must be a non-negative integer")
    output_spec = None
    for candidate in schema.outputs:
        if candidate.name == output:
            output_spec = candidate
            break
    if output_spec is None:
        raise GlobalSensitivityError(f"unknown output {output!r}")
    if output_spec.kind != "scalar":
        raise GlobalSensitivityError(
            f"output {output!r} is {output_spec.kind}; only scalar outputs are supported"
        )
    evaluations = sample_count * (len(names) + 2)
    if evaluations > max_evaluations:
        raise GlobalSensitivityError(
            f"study would run {evaluations} evaluations (limit {max_evaluations}); "
            "reduce sample_count or the number of factors"
        )

    lower, upper = _factor_bounds(schema, names)
    a, b, ab = saltelli_design(len(names), sample_count, seed)
    matrices = [qmc.scale(a, lower, upper), qmc.scale(b, lower, upper)] + [
        qmc.scale(hybrid, lower, upper) for hybrid in ab
    ]
    points = [
        {name: float(matrix[row, column]) for column, name in enumerate(names)}
        for matrix in matrices
        for row in range(sample_count)
    ]

    values, failures = _evaluate(
        schema, baseline, output, points, runner, journal, evaluations
    )
    completed = sum(1 for value in values if value is not None)

    base = dict(
        model_id=schema.model_id,
        output=output,
        sample_count=sample_count,
        seed=seed,
        dimensions=len(names),
        factors=names,
        evaluations_requested=evaluations,
        evaluations_completed=completed,
        bootstrap_resamples=bootstrap_resamples,
    )
    if failures:
        return SobolReport(
            **base,
            inconclusive=True,
            reasons=[
                f"{count} evaluation(s) {reason}" for reason, count in sorted(failures.items())
            ],
        )

    n = sample_count
    y_a = np.array(values[0:n], dtype=float)
    y_b = np.array(values[n : 2 * n], dtype=float)
    y_ab = [np.array(values[(2 + i) * n : (3 + i) * n], dtype=float) for i in range(len(names))]
    variance, results, reasons = _estimate(
        y_a, y_b, y_ab, names, bootstrap_resamples=bootstrap_resamples, seed=seed
    )
    note = (
        "finite-sample estimates; theoretical bounds are not imposed. "
        "A bootstrap interval is a diagnostic, not proof of convergence."
    )
    # Application-level, dependency-independent diagnostic. The power-of-two bit
    # check is exact and does not rely on capturing scipy's warning (which mutates
    # the process-global warning filter and is not thread-safe). SciPy may still
    # emit its own balance warning; this note is the authoritative signal.
    if sample_count & (sample_count - 1):
        note += (
            " N is not a power of two, so the Sobol' sequence balance properties are "
            "weaker and the estimates may be less accurate."
        )
    return SobolReport(
        **base,
        variance=variance,
        inconclusive=bool(reasons),
        reasons=reasons,
        results=results,
        note=note,
    )


def sobol_indices_for_experiment(
    experiment_id: str,
    store: Any,
    *,
    output: str | None = None,
    factors: Sequence[str] | None = None,
    sample_count: int = DEFAULT_SAMPLE_COUNT,
    seed: int = 0,
    runner: Runner | None = None,
    journal: Any | None = None,
    bootstrap_resamples: int = DEFAULT_BOOTSTRAP,
    max_evaluations: int = MAX_EVALUATIONS,
) -> SobolReport:
    """Run a global-sensitivity study for a stored experiment (read-only)."""
    from drw.models.registry import build_model
    from drw.schema.experiment import ExperimentSpec as _Spec
    from drw.sensitivity import primary_output

    loaded = store.load(experiment_id)
    spec = _Spec.model_validate(loaded["spec"])
    schema = build_model(spec.model_ref.model_id).describe()
    chosen_output = output or primary_output(schema)
    chosen_factors = list(factors) if factors else default_factors(schema)
    return sobol_indices(
        schema,
        baseline=dict(spec.baseline),
        output=chosen_output,
        factors=chosen_factors,
        sample_count=sample_count,
        seed=seed,
        runner=runner,
        journal=journal,
        bootstrap_resamples=bootstrap_resamples,
        max_evaluations=max_evaluations,
    )
