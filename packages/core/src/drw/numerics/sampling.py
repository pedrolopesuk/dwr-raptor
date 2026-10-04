"""SCI-002: deterministic parameter sampling.

Expands an :class:`~drw.schema.experiment.ExperimentSpec` into a design matrix of
variant parameter overrides. Grid designs follow a fixed factor order; stochastic
designs (random / Latin hypercube / Sobol) are fully determined by the declared
seed, so the same spec always yields the same design.

The baseline is *not* part of the design matrix: it is run separately by the
engine and acts as the frozen reference for differential analysis.
"""

from __future__ import annotations

import itertools
import warnings

import numpy as np
from scipy.stats import qmc

from drw.schema.experiment import ExperimentSpec, FactorSpec, is_power_of_two
from drw.schema.model import ModelSchema, ParameterSpec
from drw.schema.result import Diagnostic

__all__ = ["SamplingDesign", "expand_design"]


class SamplingDesign:
    """A materialized design matrix plus any warnings produced while building it."""

    __slots__ = ("method", "samples", "seed", "warnings")

    def __init__(
        self,
        samples: list[dict[str, float]],
        *,
        method: str,
        seed: int,
        warnings: tuple[Diagnostic, ...] = (),
    ) -> None:
        self.samples = samples
        self.method = method
        self.seed = seed
        self.warnings = warnings

    def __len__(self) -> int:
        return len(self.samples)


def _coerce(value: float, param: ParameterSpec) -> float:
    if param.type == "int":
        return float(round(value))
    return float(value)


def _bounds(factor: FactorSpec, param: ParameterSpec) -> tuple[float, float]:
    if factor.mode == "list":
        values = [float(v) for v in factor.values]
        return min(values), max(values)
    # range or bounds mode: fall back to the model parameter's declared bounds
    # when the factor does not narrow them.
    lower = factor.lower if factor.lower is not None else param.lower
    upper = factor.upper if factor.upper is not None else param.upper
    if lower is None or upper is None:
        raise ValueError(
            f"factor {factor.parameter!r} has no bounds, and the model parameter "
            "declares none either"
        )
    return float(lower), float(upper)


def expand_design(spec: ExperimentSpec, schema: ModelSchema) -> SamplingDesign:
    """Return the deterministic design matrix for ``spec``."""
    factors = list(spec.factors)
    design_warnings: list[Diagnostic] = []

    if not factors:
        return SamplingDesign([], method=spec.sampling.method, seed=spec.sampling.seed)

    if spec.sampling.method == "grid":
        if spec.sampling.n_samples is not None:
            design_warnings.append(
                Diagnostic(
                    level="warning",
                    code="n_samples_ignored",
                    message=(
                        "sampling.n_samples is ignored by the grid method; the run count "
                        "comes from the factor cardinalities"
                    ),
                )
            )
        value_lists = [factor.grid_values() for factor in factors]
        samples: list[dict[str, float]] = []
        for combination in itertools.product(*value_lists):
            samples.append(
                {
                    factor.parameter: _coerce(value, schema.parameter(factor.parameter))
                    for factor, value in zip(factors, combination, strict=True)
                }
            )
        return SamplingDesign(
            samples, method="grid", seed=spec.sampling.seed, warnings=tuple(design_warnings)
        )

    n_samples = int(spec.sampling.n_samples or 0)
    if n_samples < 1:
        raise ValueError(f"sampling method {spec.sampling.method!r} requires n_samples >= 1")

    for factor in factors:
        if factor.mode == "range":
            design_warnings.append(
                Diagnostic(
                    level="warning",
                    code="factor_steps_ignored",
                    message=(
                        f"factor {factor.parameter!r} declares 'steps', which is ignored by "
                        f"{spec.sampling.method!r} sampling; only its bounds are used"
                    ),
                )
            )

    if spec.sampling.method == "sobol" and not is_power_of_two(n_samples):
        design_warnings.append(
            Diagnostic(
                level="warning",
                code="sobol_non_power_of_two",
                message=(
                    f"Sobol balance properties require a power-of-two sample size; "
                    f"got n_samples={n_samples}"
                ),
            )
        )

    dimension = len(factors)
    lower = np.array([_bounds(f, schema.parameter(f.parameter))[0] for f in factors], dtype=float)
    upper = np.array([_bounds(f, schema.parameter(f.parameter))[1] for f in factors], dtype=float)
    if np.any(upper <= lower):
        bad = [f.parameter for f, lo, hi in zip(factors, lower, upper, strict=True) if hi <= lo]
        raise ValueError(f"factors with degenerate bounds: {bad}")

    if not lower.flags.writeable:  # defensive; scale() does not mutate bounds
        lower = lower.copy()
        upper = upper.copy()

    seed = spec.sampling.seed
    if spec.sampling.method == "random":
        rng = np.random.default_rng(seed)
        unit = rng.random((n_samples, dimension))
    elif spec.sampling.method == "latin_hypercube":
        unit = qmc.LatinHypercube(d=dimension, seed=seed).random(n_samples)
    elif spec.sampling.method == "sobol":
        # We surface the power-of-two guidance ourselves as a structured
        # diagnostic, so the SciPy UserWarning is redundant here.
        with warnings.catch_warnings():
            warnings.filterwarnings("ignore", message=".*power of 2.*", category=UserWarning)
            unit = qmc.Sobol(d=dimension, scramble=True, seed=seed).random(n_samples)
    else:  # pragma: no cover - guarded by the Literal type
        raise ValueError(f"unsupported sampling method {spec.sampling.method!r}")

    scaled = qmc.scale(unit, lower, upper)
    samples = [
        {
            factor.parameter: _coerce(row[index], schema.parameter(factor.parameter))
            for index, factor in enumerate(factors)
        }
        for row in scaled
    ]
    return SamplingDesign(
        samples,
        method=spec.sampling.method,
        seed=seed,
        warnings=tuple(design_warnings),
    )
