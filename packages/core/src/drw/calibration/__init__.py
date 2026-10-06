"""M12B calibration: a thin orchestration layer around the existing engine.

The optimizer proposes bounded parameter vectors; the :class:`~drw.execution.runner.Runner`
executes each candidate as a single-run experiment; M12A
:func:`~drw.evaluation.evaluate_run` compares the run to the observations; and the
objective oracle turns that comparison into one minimisable scalar. Calibration
never executes a model itself and never re-implements comparison.
"""

from __future__ import annotations

from drw.calibration.loop import calibrate, calibrate_for_experiment
from drw.calibration.objective import (
    OBJECTIVE_SENTINEL,
    ObjectiveOracle,
    ObjectiveOutcome,
    ResolvedPair,
    resolve_objective_pair,
)
from drw.calibration.optimizers import (
    CalibrationBudgetExceeded,
    CalibrationCancelled,
    CalibrationMaxFailed,
    CalibrationStop,
    CalibrationWallTimeExceeded,
    OptimizerOutcome,
    RandomSearchGenerator,
    build_optimizer,
)

__all__ = [
    "OBJECTIVE_SENTINEL",
    "CalibrationBudgetExceeded",
    "CalibrationCancelled",
    "CalibrationMaxFailed",
    "CalibrationStop",
    "CalibrationWallTimeExceeded",
    "ObjectiveOracle",
    "ObjectiveOutcome",
    "OptimizerOutcome",
    "RandomSearchGenerator",
    "ResolvedPair",
    "build_optimizer",
    "calibrate",
    "calibrate_for_experiment",
    "resolve_objective_pair",
]
