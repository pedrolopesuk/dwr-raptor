"""Calibration objective oracle (M12B, Phase B).

The oracle converts an **M12A** :class:`~drw.schema.evaluation.EvaluationResult`
into the single scalar an optimizer minimises. It is the *only* bridge between
evaluation and optimisation: it never recomputes residuals, alignment, units,
uncertainty or metrics - it reads the metric M12A already produced.

Fail-closed: when M12A reports ``ok=False``, the selected metric is ``null``, or
the value is non-finite, the objective is ``None`` together with an explicit
failure code. A ``None`` objective is **never** turned into a scientific number;
an optimizer that requires a finite scalar receives ``+inf`` purely as an
*interface sentinel* (see :data:`OBJECTIVE_SENTINEL`). The stored/displayed
objective stays ``None``.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from drw.schema.calibration import ObjectiveConfig
from drw.schema.evaluation import EvaluationResult
from drw.schema.observation import ObservationMapping

__all__ = [
    "OBJECTIVE_SENTINEL",
    "ObjectiveOracle",
    "ObjectiveOutcome",
    "ResolvedPair",
    "resolve_objective_pair",
]

#: The internal optimizer-interface sentinel for an invalid objective (+inf).
#: It is disclosed in the result and is never a stored scientific value.
OBJECTIVE_SENTINEL = float("inf")


@dataclass(frozen=True)
class ResolvedPair:
    """The concrete mapping pair an objective refers to."""

    observation: str
    output: str


@dataclass(frozen=True)
class ObjectiveOutcome:
    """The objective value (or ``None``) plus its provenance."""

    value: float | None
    failure: str | None
    observation: str
    output: str
    n_used: int
    n_excluded: int
    evaluation_hash: str | None = None

    @property
    def valid(self) -> bool:
        return self.value is not None and self.failure is None


def resolve_objective_pair(
    objective: ObjectiveConfig, mapping: ObservationMapping
) -> ResolvedPair:
    """Resolve which mapping pair the objective scores.

    A selector is required when the mapping declares more than one pair (the
    request validator already enforces this); when exactly one pair exists it is
    used implicitly.
    """
    if objective.observation is not None and objective.output is not None:
        return ResolvedPair(objective.observation, objective.output)
    if len(mapping.pairs) != 1:
        raise ValueError(
            "the objective must select one mapping pair when the mapping declares "
            f"{len(mapping.pairs)} pairs"
        )
    pair = mapping.pairs[0]
    return ResolvedPair(pair.observation, pair.output)


class ObjectiveOracle:
    """Extracts a minimisable scalar from an M12A evaluation (never recomputes)."""

    def __init__(self, objective: ObjectiveConfig, mapping: ObservationMapping) -> None:
        self.metric = objective.metric
        self.pair = resolve_objective_pair(objective, mapping)

    def sentinel(self, value: float | None) -> float:
        """Map a possibly-invalid objective to a finite optimizer scalar."""
        return OBJECTIVE_SENTINEL if value is None else value

    def from_evaluation(self, evaluation: EvaluationResult) -> ObjectiveOutcome:
        pair_evaluation = next(
            (
                pair
                for pair in evaluation.pairs
                if pair.observation == self.pair.observation and pair.output == self.pair.output
            ),
            None,
        )
        n_used = pair_evaluation.usable_count if pair_evaluation is not None else 0
        n_excluded = pair_evaluation.excluded_count if pair_evaluation is not None else 0

        if not evaluation.ok:
            code = next(
                (d.code for d in evaluation.diagnostics if d.level == "error"),
                "evaluation_failed",
            )
            return ObjectiveOutcome(
                None, code, self.pair.observation, self.pair.output, n_used, n_excluded,
                evaluation.evaluation_hash,
            )
        if pair_evaluation is None:
            return ObjectiveOutcome(
                None, "pair_not_found", self.pair.observation, self.pair.output, 0, 0,
                evaluation.evaluation_hash,
            )
        value = pair_evaluation.metrics.get(self.metric)
        if value is None:
            return ObjectiveOutcome(
                None, "objective_undefined", self.pair.observation, self.pair.output,
                n_used, n_excluded, evaluation.evaluation_hash,
            )
        if not math.isfinite(float(value)):
            return ObjectiveOutcome(
                None, "non_finite_objective", self.pair.observation, self.pair.output,
                n_used, n_excluded, evaluation.evaluation_hash,
            )
        return ObjectiveOutcome(
            float(value), None, self.pair.observation, self.pair.output, n_used, n_excluded,
            evaluation.evaluation_hash,
        )
