"""One-at-a-time (OAT) local sensitivity ranking.

Shared by the CLI demo (:mod:`drw.demo`) and the JSON bridge (:mod:`drw.api`) so
the ranking is computed in exactly one place.

Interpretation caveats, which callers should surface to users:

* **Absolute delta is scale-dependent.** A normalized ``elasticity`` (relative
  output change / relative input change) is reported for cross-parameter
  comparison.
* **OAT is local and cannot detect interactions or non-identifiability.** For
  example the early prey peak depends on the product ``beta * predator0``, so
  their one-at-a-time effects are nearly identical.
* **A perturbation clipped to a parameter bound is not the requested change.**
  Rows flag ``clamped`` and report the actual ``perturbed_value``.

Global (variance-based) sensitivity is deliberately out of scope.
"""

from __future__ import annotations

import math
from typing import Any

from drw.execution.runner import Runner
from drw.schema.experiment import AnalysisSpec, ExperimentSpec, FactorSpec
from drw.schema.model import ModelRef, ModelSchema, ParameterSpec

__all__ = [
    "PERTURBATION",
    "elasticity",
    "oat_sensitivity",
    "perturbed_value",
    "primary_output",
]

PERTURBATION = 1.10  # +10%


def primary_output(schema: ModelSchema) -> str:
    """The output used to rank sensitivity: the first scalar output, else the first output."""
    for output in schema.outputs:
        if output.kind == "scalar":
            return output.name
    return schema.outputs[0].name


def _clamp_to_bounds(value: float, param: ParameterSpec) -> float:
    if param.lower is not None:
        value = max(value, param.lower)
    if param.upper is not None:
        value = min(value, param.upper)
    return value


def perturbed_value(
    param: ParameterSpec, baseline: float, factor: float = PERTURBATION
) -> float:
    """The perturbed value, clamped to the parameter's declared bounds."""
    value = baseline * factor
    if value == baseline:  # nominal is zero: fall back to an additive nudge
        value = baseline + 1.0
    return _clamp_to_bounds(value, param)


def elasticity(
    baseline_value: float,
    perturbed_value: float,
    reference_peak: float | None,
    variant_peak: float | None,
) -> float | None:
    """Relative output change divided by relative input change (``None`` if undefined)."""
    if reference_peak in (None, 0.0) or variant_peak is None or baseline_value == 0.0:
        return None
    relative_input = (perturbed_value - baseline_value) / baseline_value
    if relative_input == 0.0:
        return None
    relative_output = (variant_peak - reference_peak) / reference_peak
    return relative_output / relative_input


def oat_sensitivity(
    schema: ModelSchema,
    baseline_inputs: dict[str, Any],
    reference_peak: float | None,
    peak_output: str,
    *,
    perturbation: float = PERTURBATION,
    runner: Runner | None = None,
) -> list[dict[str, Any]]:
    """Rank every numeric parameter by its one-at-a-time influence on ``peak_output``."""
    active_runner = runner or Runner()
    rows: list[dict[str, Any]] = []
    for param in schema.parameters:
        if param.type not in ("float", "int"):
            continue
        baseline_value = float(baseline_inputs[param.name])
        candidate = perturbed_value(param, baseline_value, perturbation)
        if candidate == baseline_value:
            continue
        requested = baseline_value * perturbation
        clamped = baseline_value != 0.0 and not math.isclose(
            candidate, requested, rel_tol=1e-12, abs_tol=0.0
        )

        spec = ExperimentSpec(
            name=f"sensitivity:{param.name}",
            hypothesis=f"Local +10% response of {peak_output} to {param.name}.",
            model_ref=ModelRef(model_id=schema.model_id, version=schema.version),
            baseline=dict(baseline_inputs),
            factors=(FactorSpec(parameter=param.name, values=(candidate,)),),
            outputs=(peak_output,),
            analyses=(AnalysisSpec(method="delta"),),
        )
        result = active_runner.run(spec)
        comparison = result.comparisons[0]
        variant_peak = result.variants[0].metrics.get(peak_output)
        rows.append(
            {
                "parameter": param.name,
                "unit": param.unit,
                "baseline_value": baseline_value,
                "perturbed_value": candidate,
                "clamped": clamped,
                "reference_peak": reference_peak,
                "variant_peak": variant_peak,
                "abs_delta": comparison.metrics["max_abs_delta"],
                "max_abs_relative_delta": comparison.metrics.get("max_abs_relative_delta"),
                "elasticity": elasticity(baseline_value, candidate, reference_peak, variant_peak),
            }
        )

    rows.sort(key=lambda row: abs(row["abs_delta"] or 0.0), reverse=True)
    return rows
