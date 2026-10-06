"""Calibration optimizers (M12B, Phase C).

Adapters over the search strategies M12B supports. They never execute a model:
each receives the loop's counting objective function and returns an
:class:`OptimizerOutcome`. The loop owns the **hard evaluation cap**: a scipy
optimizer cannot exceed ``max_evaluations`` because the objective it calls raises
:class:`CalibrationBudgetExceeded` at the cap.

* :class:`PowellOptimizer` - default: bounded, derivative-free, deterministic.
* :class:`DifferentialEvolutionOptimizer` - opt-in global, seeded, deterministic.
* :class:`RandomSearchGenerator` - deterministic baseline/reference (not the
  default); it enumerates exactly the budget.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Protocol

import numpy as np

from drw.schema.calibration import OptimizerConfig

__all__ = [
    "CalibrationBudgetExceeded",
    "CalibrationCancelled",
    "CalibrationMaxFailed",
    "CalibrationStop",
    "CalibrationWallTimeExceeded",
    "DifferentialEvolutionOptimizer",
    "ObjectiveFunction",
    "Optimizer",
    "OptimizerOutcome",
    "PowellOptimizer",
    "RandomSearchGenerator",
    "build_optimizer",
]


# ---------------------------------------------------------------------------
# Loop-level stop signals (raised from inside the counting objective).
# ---------------------------------------------------------------------------


class CalibrationStop(Exception):
    """Base class for a loop-enforced stop."""


class CalibrationBudgetExceeded(CalibrationStop):
    """Raised when the hard ``max_evaluations`` cap is reached."""


class CalibrationWallTimeExceeded(CalibrationStop):
    """Raised when ``max_wall_seconds`` is exceeded."""


class CalibrationCancelled(CalibrationStop):
    """Raised when the caller's cancellation event is set."""


class CalibrationMaxFailed(CalibrationStop):
    """Raised when ``max_failed`` invalid candidates have been recorded."""


ObjectiveFunction = Callable[[Sequence[float]], float]


@dataclass(frozen=True)
class OptimizerOutcome:
    """How an optimizer finished."""

    converged: bool
    stop_reason: str
    iterations: int
    message: str = ""


class Optimizer(Protocol):
    name: str

    def minimize(
        self,
        *,
        x0: Sequence[float],
        bounds: Sequence[tuple[float, float]],
        func: ObjectiveFunction,
        max_iterations: int | None,
    ) -> OptimizerOutcome: ...


def _stop_reason(success: bool) -> str:
    """Map a scipy result to a stop reason.

    A scipy optimizer that returns without ``success`` stopped on one of its own
    iteration/evaluation/tolerance controls, so the honest reason is
    ``max_iterations``; a genuine optimizer fault is raised as an exception and
    mapped by the loop to ``optimizer_failure``.
    """
    return "optimizer_converged" if success else "max_iterations"


class PowellOptimizer:
    """Bounded, derivative-free local minimization (the default optimizer)."""

    name = "powell"

    def __init__(self, *, max_iterations: int | None = None) -> None:
        self.max_iterations = max_iterations

    def minimize(
        self,
        *,
        x0: Sequence[float],
        bounds: Sequence[tuple[float, float]],
        func: ObjectiveFunction,
        max_iterations: int | None = None,
    ) -> OptimizerOutcome:
        from scipy.optimize import minimize

        options: dict[str, object] = {}
        iterations = max_iterations if max_iterations is not None else self.max_iterations
        if iterations is not None:
            options["maxiter"] = int(iterations)
        result = minimize(
            func,
            np.asarray(x0, dtype=float),
            method="Powell",
            bounds=list(bounds),
            options=options,
        )
        # Powell stops on its own controls when it does not converge.
        reason = _stop_reason(bool(result.success))
        return OptimizerOutcome(
            converged=bool(result.success),
            stop_reason=reason,
            iterations=int(getattr(result, "nit", 0)),
            message=str(getattr(result, "message", "")),
        )


class DifferentialEvolutionOptimizer:
    """Opt-in global optimization (seeded, deterministic, single-worker)."""

    name = "differential_evolution"

    def __init__(
        self,
        *,
        seed: int,
        max_iterations: int | None = None,
        population_size: int | None = None,
        mutation: float | None = None,
        recombination: float | None = None,
    ) -> None:
        self.seed = seed
        self.max_iterations = max_iterations
        self.population_size = population_size
        self.mutation = mutation
        self.recombination = recombination

    def minimize(
        self,
        *,
        x0: Sequence[float],
        bounds: Sequence[tuple[float, float]],
        func: ObjectiveFunction,
        max_iterations: int | None = None,
    ) -> OptimizerOutcome:
        from scipy.optimize import differential_evolution

        iterations = max_iterations if max_iterations is not None else self.max_iterations
        kwargs: dict[str, object] = {"seed": self.seed, "polish": False, "workers": 1}
        if self.population_size is not None:
            kwargs["popsize"] = int(self.population_size)
        if self.mutation is not None:
            kwargs["mutation"] = float(self.mutation)
        if self.recombination is not None:
            kwargs["recombination"] = float(self.recombination)
        if iterations is not None:
            kwargs["maxiter"] = int(iterations)
        result = differential_evolution(func, bounds=list(bounds), **kwargs)
        reason = _stop_reason(bool(result.success))
        return OptimizerOutcome(
            converged=bool(result.success),
            stop_reason=reason,
            iterations=int(getattr(result, "nit", 0)),
            message=str(getattr(result, "message", "")),
        )


class RandomSearchGenerator:
    """Deterministic uniform sampling over the box (a reference strategy)."""

    name = "random_search"

    def __init__(self, *, seed: int) -> None:
        self.seed = seed

    def proposals(
        self, bounds: Sequence[tuple[float, float]], count: int
    ) -> list[list[float]]:
        rng = np.random.default_rng(self.seed)
        dimension = len(bounds)
        unit = rng.random((count, dimension))
        lower = np.array([low for low, _ in bounds], dtype=float)
        upper = np.array([high for _, high in bounds], dtype=float)
        scaled = lower + unit * (upper - lower)
        return [[float(value) for value in row] for row in scaled]


def build_optimizer(config: OptimizerConfig, *, seed: int) -> Optimizer:
    """Build the optimizer adapter for a configuration (scipy-backed)."""
    if config.name == "powell":
        return PowellOptimizer(max_iterations=config.max_iterations)
    if config.name == "differential_evolution":
        return DifferentialEvolutionOptimizer(
            seed=seed,
            max_iterations=config.max_iterations,
            population_size=config.population_size,
            mutation=config.mutation,
            recombination=config.recombination,
        )
    raise ValueError(f"optimizer {config.name!r} is not a scipy-backed optimizer")
