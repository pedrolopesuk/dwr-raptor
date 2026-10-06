"""What a registered model actually supports.

The AI planner and the UI both need a single, authoritative answer to "what can
be varied, sampled, analysed and executed for this model?". Deriving it here -
from the model's own :class:`~drw.schema.model.ModelSchema` - keeps the answer
honest: a capability is listed only when the engine implements it and the model
declares what it needs.
"""

from __future__ import annotations

from typing import Any

from drw.schema.model import ModelSchema

__all__ = ["IMPLEMENTED_ANALYSES", "SAMPLING_METHODS", "model_capabilities"]

#: Analysis methods the run engine actually produces artifacts for.
#: ``uncertainty`` is a descriptive summary over the sampled variant runs
#: (produced only when the experiment declares it).
IMPLEMENTED_ANALYSES: tuple[str, ...] = ("delta", "relative_delta", "uncertainty")
#: Sampling methods the sampler implements.
SAMPLING_METHODS: tuple[str, ...] = ("grid", "random", "latin_hypercube", "sobol")


def model_capabilities(schema: ModelSchema) -> dict[str, Any]:
    """Return the supported capabilities for ``schema``."""
    # Imported locally so this foundational module does not pull the analysis
    # engine (and scipy) into every importer. The study limits remain
    # single-sourced in drw.global_sensitivity / drw.identifiability and are only
    # *exposed* here, so the UI never duplicates the default sample count, the
    # evaluation cap, the step scale or the time-series feature set.
    from drw.global_sensitivity import DEFAULT_SAMPLE_COUNT, MAX_EVALUATIONS
    from drw.identifiability import (
        CONDITION_THRESHOLD,
        DEFAULT_STEP_SCALE,
        IDENTIFIABILITY_METHOD,
        TIMESERIES_FEATURES,
    )
    from drw.identifiability import MAX_EVALUATIONS as IDENTIFIABILITY_MAX_EVALUATIONS
    from drw.schema.calibration import (
        DEFAULT_OBJECTIVE_METRIC,
        DEFAULT_OPTIMIZER,
        OBJECTIVE_METRICS,
        OPTIMIZER_NAMES,
    )

    numeric = [p for p in schema.parameters if p.type in ("float", "int")]
    factorable = [p for p in numeric if p.has_bounds()]
    fixed = [p for p in numeric if not p.has_bounds()]
    state = schema.state_parameters()
    timeseries = [o for o in schema.outputs if o.kind == "timeseries"]
    scalars = [o for o in schema.outputs if o.kind == "scalar"]

    limitations: list[str] = []
    if not factorable:
        limitations.append(
            "no numeric parameter declares both bounds, so no parameter can be varied"
        )
    if not scalars:
        limitations.append("no scalar output is available for sensitivity ranking")
    if not timeseries:
        limitations.append("no time-series output is available for plotting deltas")

    return {
        "model_id": schema.model_id,
        "version": schema.version,
        "parameter_names": list(schema.parameter_names()),
        "factorable_parameters": [
            {"name": p.name, "unit": p.unit, "lower": p.lower, "upper": p.upper}
            for p in factorable
        ],
        "fixed_parameters": [p.name for p in fixed],
        "state_parameters": [p.name for p in state],
        "categorical_parameters": [p.name for p in schema.parameters if p.type == "categorical"],
        "timeseries_outputs": [o.name for o in timeseries],
        "scalar_outputs": [o.name for o in scalars],
        "sampling_methods": list(SAMPLING_METHODS),
        "analysis_methods": list(IMPLEMENTED_ANALYSES),
        "sensitivity": "oat" if scalars else None,
        "isolation": "subprocess",
        # Authoritative global-sensitivity study configuration (single source:
        # drw.global_sensitivity). Additive; the core remains the enforcement point.
        "global_sensitivity": {
            "default_sample_count": DEFAULT_SAMPLE_COUNT,
            "max_evaluations": MAX_EVALUATIONS,
        },
        # Authoritative local-identifiability study configuration (single source:
        # drw.identifiability). Additive; the core remains the enforcement point.
        "identifiability": {
            "method": IDENTIFIABILITY_METHOD,
            "default_step_scale": DEFAULT_STEP_SCALE,
            "condition_threshold": CONDITION_THRESHOLD,
            "max_evaluations": IDENTIFIABILITY_MAX_EVALUATIONS,
            "timeseries_features": list(TIMESERIES_FEATURES),
        },
        # Authoritative calibration configuration (single source: drw.calibration /
        # drw.schema.calibration). Additive; the core remains the enforcement point.
        "calibration": {
            "default_optimizer": DEFAULT_OPTIMIZER,
            "optimizers": list(OPTIMIZER_NAMES),
            "objective_metrics": list(OBJECTIVE_METRICS),
            "default_objective_metric": DEFAULT_OBJECTIVE_METRIC,
            "default_max_evaluations": 100,
            "default_max_wall_seconds": 600.0,
            "identifiability_modes": ["off", "warn", "require"],
            "supported_parameter_types": ["float"],
        },
        "limitations": limitations,
    }
