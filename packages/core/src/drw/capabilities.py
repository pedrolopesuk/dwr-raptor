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
IMPLEMENTED_ANALYSES: tuple[str, ...] = ("delta", "relative_delta")
#: Sampling methods the sampler implements.
SAMPLING_METHODS: tuple[str, ...] = ("grid", "random", "latin_hypercube", "sobol")


def model_capabilities(schema: ModelSchema) -> dict[str, Any]:
    """Return the supported capabilities for ``schema``."""
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
        "limitations": limitations,
    }
