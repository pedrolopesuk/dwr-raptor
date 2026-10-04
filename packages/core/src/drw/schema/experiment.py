"""The typed experiment specification (``ExperimentSpec``).

Mirrors specification section 7.3::

    ExperimentSpec = { hypothesis, model_ref, baseline, factors[], outputs[],
                       sampling, constraints[], analyses[], execution,
                       verification, reporting }

The AI layer may *propose* a spec, but only the deterministic validator in this
module decides whether it is executable. :func:`estimate_run_count` implements
the "predict the number of runs before execution" requirement.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from drw.schema.model import ModelRef, ModelSchema, ScalarValue
from drw.schema.result import Diagnostic

__all__ = [
    "EXPERIMENT_SCHEMA_VERSION",
    "AnalysisSpec",
    "ConstraintSpec",
    "ExecutionSpec",
    "ExperimentSpec",
    "FactorSpec",
    "IsolationMode",
    "ReportingSpec",
    "RunEstimate",
    "SamplingMethod",
    "SamplingSpec",
    "VerificationSpec",
    "dedupe_diagnostics",
    "estimate_run_count",
    "is_power_of_two",
]

EXPERIMENT_SCHEMA_VERSION = "1.0.0"

SamplingMethod = Literal["grid", "random", "latin_hypercube", "sobol"]
AnalysisMethod = Literal["delta", "relative_delta", "sensitivity", "uncertainty", "optimization"]
SolverChoice = Literal["auto", "explicit", "stiff"]
ConstraintOp = Literal["<=", "<", ">=", ">", "=="]
IsolationMode = Literal["in_process", "subprocess"]


def dedupe_diagnostics(diagnostics: Iterable[Diagnostic]) -> tuple[Diagnostic, ...]:
    """Remove exact duplicate diagnostics while preserving order."""
    seen: set[tuple[str, str, str]] = set()
    unique: list[Diagnostic] = []
    for diagnostic in diagnostics:
        key = (diagnostic.level, diagnostic.code, diagnostic.message)
        if key in seen:
            continue
        seen.add(key)
        unique.append(diagnostic)
    return tuple(unique)


def is_power_of_two(n: int) -> bool:
    return n >= 1 and (n & (n - 1)) == 0


class FactorSpec(BaseModel):
    """How one parameter is varied.

    Three modes, mutually exclusive:

    * ``values`` - an explicit list of values (used by grid designs),
    * ``range`` - ``lower``, ``upper`` and ``steps``; endpoints inclusive via
      ``numpy.linspace`` (used by grid designs), or
    * ``bounds`` - ``lower``/``upper`` only, with no ``steps``. The number of
      points comes from ``sampling.n_samples``; this is the natural form for
      random / Latin-hypercube / Sobol designs. Bounds may be omitted, in which
      case the model parameter's declared bounds are used.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    parameter: str
    values: tuple[float, ...] = ()
    lower: float | None = None
    upper: float | None = None
    steps: int | None = None

    @model_validator(mode="after")
    def _check_mode(self) -> FactorSpec:
        has_list = len(self.values) > 0
        has_bounds = self.lower is not None or self.upper is not None
        if has_list and has_bounds:
            raise ValueError(
                f"factor {self.parameter!r} must use either 'values' or 'lower'/'upper', not both"
            )
        if not has_list and not has_bounds:
            raise ValueError(
                f"factor {self.parameter!r} requires 'values' or at least one of 'lower'/'upper'"
            )
        if has_bounds:
            if self.lower is None or self.upper is None:
                raise ValueError(
                    f"factor {self.parameter!r} must set both 'lower' and 'upper'"
                )
            if self.lower >= self.upper:
                raise ValueError(
                    f"factor {self.parameter!r} requires lower < upper "
                    f"(got {self.lower} >= {self.upper})"
                )
            if self.steps is not None and self.steps < 1:
                raise ValueError(f"factor {self.parameter!r} steps must be >= 1")
        if self.steps is not None and not has_bounds:
            raise ValueError(f"factor {self.parameter!r} sets 'steps' without 'lower'/'upper'")
        return self

    @property
    def mode(self) -> Literal["list", "range", "bounds"]:
        if self.values:
            return "list"
        return "range" if self.steps is not None else "bounds"

    def cardinality(self) -> int:
        """Number of discrete points (list/range modes only)."""
        if self.values:
            return len(self.values)
        if self.steps is None:
            raise ValueError(
                f"factor {self.parameter!r} defines bounds only; its cardinality comes "
                "from sampling.n_samples"
            )
        return int(self.steps)

    def grid_values(self) -> tuple[float, ...]:
        """Materialize the discrete values for this factor (deterministic order)."""
        if self.values:
            return tuple(float(v) for v in self.values)
        if self.lower is None or self.upper is None or self.steps is None:
            raise ValueError(
                f"factor {self.parameter!r} cannot be expanded to a grid without 'steps'"
            )
        import numpy as np

        return tuple(float(v) for v in np.linspace(self.lower, self.upper, self.steps))


class SamplingSpec(BaseModel):
    """The sampling design over the declared factors."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    method: SamplingMethod = "grid"
    n_samples: int | None = None
    seed: int = 0

    @field_validator("seed")
    @classmethod
    def _check_seed(cls, value: int) -> int:
        if value < 0:
            raise ValueError("seed must be non-negative")
        return value

    @model_validator(mode="after")
    def _check_n_samples(self) -> SamplingSpec:
        if self.method == "grid":
            return self
        if self.n_samples is None or self.n_samples < 1:
            raise ValueError(f"sampling method {self.method!r} requires n_samples >= 1")
        return self


class ConstraintSpec(BaseModel):
    """A simple box/linear constraint on one parameter."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    parameter: str
    op: ConstraintOp
    value: float

    def holds(self, actual: float, *, epsilon: float = 0.0) -> bool:
        if self.op == "<=":
            return actual <= self.value + epsilon
        if self.op == "<":
            return actual < self.value + epsilon
        if self.op == ">=":
            return actual >= self.value - epsilon
        if self.op == ">":
            return actual > self.value - epsilon
        return abs(actual - self.value) <= epsilon


class AnalysisSpec(BaseModel):
    """A declared differential/sensitivity analysis."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    method: AnalysisMethod
    config: dict[str, Any] = Field(default_factory=dict)
    outputs: tuple[str, ...] = ()


class ExecutionSpec(BaseModel):
    """Execution controls for the run engine.

    ``isolation`` selects the process boundary. ``"subprocess"`` (the default)
    runs each model in an isolated child process so ``timeout_s`` is a hard,
    enforced wall-clock limit; ``"in_process"`` is the legacy fast path and does
    **not** enforce the timeout. See ``docs/architecture/ADR-0005-*.md``.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    solver: SolverChoice = "auto"
    timeout_s: float = 60.0
    max_runs: int = 512
    isolation: IsolationMode = "subprocess"
    workdir: str | None = None

    @field_validator("timeout_s")
    @classmethod
    def _check_timeout(cls, value: float) -> float:
        if value <= 0:
            raise ValueError("timeout_s must be positive")
        return value

    @field_validator("max_runs")
    @classmethod
    def _check_max_runs(cls, value: int) -> int:
        if value < 1:
            raise ValueError("max_runs must be at least 1")
        return value


class VerificationSpec(BaseModel):
    """Numerical tolerances and the checks the engine must record."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    rtol: float = 1e-8
    atol: float = 1e-10
    relative_epsilon: float = 1e-12
    checks: tuple[str, ...] = (
        "schema",
        "units",
        "bounds",
        "denominator_safety",
        "solver_status",
    )


class ReportingSpec(BaseModel):
    """Evidence/report rendering options."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    title: str = ""
    template: str = "default"
    formats: tuple[str, ...] = ("json", "markdown")


class ExperimentSpec(BaseModel):
    """A research question plus a deterministic execution plan."""

    model_config = ConfigDict(extra="forbid")

    schema_version: str = EXPERIMENT_SCHEMA_VERSION
    name: str = ""
    hypothesis: str = Field(min_length=1)
    model_ref: ModelRef
    baseline: dict[str, ScalarValue]
    factors: tuple[FactorSpec, ...] = ()
    outputs: tuple[str, ...] = ()
    sampling: SamplingSpec = Field(default_factory=SamplingSpec)
    constraints: tuple[ConstraintSpec, ...] = ()
    analyses: tuple[AnalysisSpec, ...] = ()
    execution: ExecutionSpec = Field(default_factory=ExecutionSpec)
    verification: VerificationSpec = Field(default_factory=VerificationSpec)
    reporting: ReportingSpec = Field(default_factory=ReportingSpec)

    @model_validator(mode="before")
    @classmethod
    def _accept_analysis_alias(cls, data: Any) -> Any:
        """Accept the specification's singular ``analysis`` key for ``analyses``.

        The product specification (section 7.3) names the field ``analysis[]``
        while the canonical field here is ``analyses``. Both are accepted on
        input; the canonical ``analyses`` name is always emitted.
        """
        if isinstance(data, dict) and "analysis" in data:
            if "analyses" in data:
                raise ValueError("provide either 'analysis' or 'analyses', not both")
            data = dict(data)
            data["analyses"] = data.pop("analysis")
        return data

    @model_validator(mode="after")
    def _check_no_duplicate_factors(self) -> ExperimentSpec:
        seen = [f.parameter for f in self.factors]
        duplicates = sorted({name for name in seen if seen.count(name) > 1})
        if duplicates:
            raise ValueError(f"duplicate factors: {duplicates}")
        return self

    def factor(self, parameter: str) -> FactorSpec:
        for spec in self.factors:
            if spec.parameter == parameter:
                return spec
        raise KeyError(f"no factor for parameter {parameter!r}")

    def content_hash(self) -> str:
        from drw.schema.serialization import content_hash

        return content_hash(self)


class RunEstimate(BaseModel):
    """Predicted number of runs for an experiment, before execution."""

    model_config = ConfigDict(extra="forbid")

    method: SamplingMethod
    baseline_runs: int = 1
    variant_runs: int
    total_runs: int
    warnings: tuple[Diagnostic, ...] = ()


def estimate_run_count(spec: ExperimentSpec) -> RunEstimate:
    """Predict the run count for ``spec`` deterministically.

    The baseline is always executed exactly once (index 0) and acts as the frozen
    reference for differential analysis; the design matrix supplies the variants.
    """
    warnings: list[Diagnostic] = []
    if spec.sampling.method == "grid":
        variant_runs = 1
        for factor in spec.factors:
            if factor.mode == "bounds":
                warnings.append(
                    Diagnostic(
                        level="error",
                        code="factor_requires_steps",
                        message=(
                            f"grid sampling requires 'steps' (or explicit 'values') for "
                            f"factor {factor.parameter!r}"
                        ),
                    )
                )
                continue
            variant_runs *= factor.cardinality()
        if not spec.factors:
            variant_runs = 0
            warnings.append(
                Diagnostic(
                    level="warning",
                    code="no_factors",
                    message="experiment declares no factors; only the baseline will run",
                )
            )
    else:
        variant_runs = int(spec.sampling.n_samples or 0)
        if spec.sampling.method == "sobol" and not is_power_of_two(variant_runs):
            warnings.append(
                Diagnostic(
                    level="warning",
                    code="sobol_non_power_of_two",
                    message=(
                        f"Sobol balance properties require a power-of-two sample size; "
                        f"got n_samples={variant_runs}"
                    ),
                )
            )

    total = 1 + variant_runs
    if total > spec.execution.max_runs:
        warnings.append(
            Diagnostic(
                level="error",
                code="run_budget_exceeded",
                message=(
                    f"estimated {total} runs exceeds execution.max_runs="
                    f"{spec.execution.max_runs}"
                ),
            )
        )
    return RunEstimate(
        method=spec.sampling.method,
        baseline_runs=1,
        variant_runs=variant_runs,
        total_runs=total,
        warnings=tuple(warnings),
    )


def validate_experiment(
    spec: ExperimentSpec, schema: ModelSchema, *, require_human_approval: bool = False
) -> tuple[Diagnostic, ...]:
    """Validate a spec against a concrete model schema.

    Returns a (possibly empty) tuple of diagnostics. Any ``level == "error"``
    diagnostic means the experiment must not be executed.
    """
    diagnostics: list[Diagnostic] = []

    def warn(code: str, message: str) -> None:
        diagnostics.append(Diagnostic(level="warning", code=code, message=message))

    def error(code: str, message: str) -> None:
        diagnostics.append(Diagnostic(level="error", code=code, message=message))

    if spec.model_ref.model_id != schema.model_id:
        error(
            "model_mismatch",
            f"spec references model {spec.model_ref.model_id!r} but schema is "
            f"{schema.model_id!r}",
        )
    if spec.model_ref.version is not None and spec.model_ref.version != schema.version:
        warn(
            "model_version_mismatch",
            f"spec pins model version {spec.model_ref.version!r} but schema is "
            f"{schema.version!r}",
        )
    if spec.schema_version != EXPERIMENT_SCHEMA_VERSION:
        warn(
            "schema_version_mismatch",
            f"spec schema_version {spec.schema_version!r} differs from engine "
            f"{EXPERIMENT_SCHEMA_VERSION!r}; validation assumes the current schema",
        )

    # Baseline coverage and types.
    for name, value in spec.baseline.items():
        if not schema.has_parameter(name):
            error("unknown_baseline_parameter", f"baseline sets unknown parameter {name!r}")
            continue
        param = schema.parameter(name)
        if param.type == "categorical" and str(value) not in param.options:
            error(
                "invalid_categorical_value",
                f"baseline value {value!r} for {name!r} is not in {param.options}",
            )
        if param.type in ("float", "int") and not isinstance(value, bool):
            if param.lower is not None and float(value) < param.lower:
                error(
                    "baseline_out_of_bounds",
                    f"baseline {name}={value} is below lower bound {param.lower}",
                )
            if param.upper is not None and float(value) > param.upper:
                error(
                    "baseline_out_of_bounds",
                    f"baseline {name}={value} is above upper bound {param.upper}",
                )

    for param in schema.state_parameters():
        if param.name not in spec.baseline:
            error(
                "missing_initial_condition",
                f"initial condition {param.name!r} is not set in the baseline",
            )

    # Factors.
    if spec.factors and spec.sampling.method != "grid":
        # range factors are the only meaningful source for stochastic designs
        for factor in spec.factors:
            if factor.mode == "list":
                warn(
                    "discrete_factor_sampled",
                    f"factor {factor.parameter!r} defines explicit values but sampling "
                    f"method is {spec.sampling.method!r}; bounds will be derived from those values",
                )

    for factor in spec.factors:
        if not schema.has_parameter(factor.parameter):
            error("unknown_factor", f"factor references unknown parameter {factor.parameter!r}")
            continue
        param = schema.parameter(factor.parameter)
        if param.type in ("bool", "categorical"):
            error(
                "factor_not_numeric",
                f"factor {factor.parameter!r} has non-numeric type {param.type!r}; "
                "vary it with explicit baseline scenarios instead",
            )
            continue
        if factor.mode == "bounds":
            lower = factor.lower if factor.lower is not None else param.lower
            upper = factor.upper if factor.upper is not None else param.upper
            if lower is None or upper is None:
                error(
                    "factor_missing_bounds",
                    f"factor {factor.parameter!r} has no bounds, and the model parameter "
                    "declares none either",
                )
                continue
            low, high = lower, upper
        else:
            values = factor.grid_values()
            low, high = min(values), max(values)
        if param.lower is not None and low < param.lower:
            error(
                "factor_out_of_bounds",
                f"factor {factor.parameter!r} reaches {low} below declared lower bound "
                f"{param.lower}; extrapolation is not allowed",
            )
        if param.upper is not None and high > param.upper:
            error(
                "factor_out_of_bounds",
                f"factor {factor.parameter!r} reaches {high} above declared upper bound "
                f"{param.upper}; extrapolation is not allowed",
            )

    for constraint in spec.constraints:
        if not schema.has_parameter(constraint.parameter):
            warn(
                "unknown_constraint_parameter",
                f"constraint references unknown parameter {constraint.parameter!r}",
            )

    # Outputs.
    if not spec.outputs:
        warn("no_outputs_declared", "no outputs declared; every model output will be compared")
    for name in spec.outputs:
        if not any(output.name == name for output in schema.outputs):
            error("unknown_output", f"spec declares unknown output {name!r}")

    # Analyses.
    if not spec.analyses:
        warn("no_analyses_declared", "no analyses declared; default delta analysis will be used")

    # Budget.
    estimate = estimate_run_count(spec)
    for diagnostic in estimate.warnings:
        diagnostics.append(diagnostic)
    if estimate.total_runs > spec.execution.max_runs:
        error(
            "run_budget_exceeded",
            f"estimated {estimate.total_runs} runs exceeds execution.max_runs="
            f"{spec.execution.max_runs}",
        )

    if require_human_approval:
        warn("human_approval_required", "execution requires explicit human approval")

    return dedupe_diagnostics(diagnostics)
