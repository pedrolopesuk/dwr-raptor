"""M12C validation: a thin orchestration layer around the existing engine.

Validation freezes a completed calibration's ``best.parameters``, executes the
model with those parameters over one or more independent validation datasets
through the :class:`~drw.execution.runner.Runner`, compares each run to its
dataset with M12A :func:`~drw.evaluation.evaluate_run`, and records structured
independence evidence. It never executes a model itself, never re-implements
comparison and contains **no optimizer**.
"""

from __future__ import annotations

from drw.validation.independence import (
    check_dataset_identity,
    check_experiment_lineage,
    check_group_key,
    check_measurement_process,
    check_time_window,
    coordinate_range_comparisons,
    evaluate_independence,
    unseen_groups,
)
from drw.validation.loop import (
    apply_acceptance,
    build_context,
    extract_metrics,
    validate,
    validate_for_experiment,
)

__all__ = [
    "apply_acceptance",
    "build_context",
    "check_dataset_identity",
    "check_experiment_lineage",
    "check_group_key",
    "check_measurement_process",
    "check_time_window",
    "coordinate_range_comparisons",
    "evaluate_independence",
    "extract_metrics",
    "unseen_groups",
    "validate",
    "validate_for_experiment",
]
