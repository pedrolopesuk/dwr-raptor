"""The "killer demo" (specification section 11.2).

One command answers: *"Show how the system changes when a parameter increases by
10%, and which other parameters most influence the peak output."*

It runs a baseline-vs-+10% differential experiment on a reference model, exports
an evidence package, then writes a one-at-a-time (OAT) sensitivity ranking
computed by :mod:`drw.sensitivity` (the same implementation the JSON bridge
exposes to the UI). Execution uses the default isolated subprocess runner
(ADR-0005).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from drw.execution.evidence import build_evidence_package
from drw.execution.runner import Runner
from drw.models.registry import build_model
from drw.schema.experiment import AnalysisSpec, ExperimentSpec, FactorSpec, ReportingSpec
from drw.schema.model import ModelRef, ModelSchema
from drw.schema.serialization import dumps_pretty
from drw.sensitivity import oat_sensitivity, perturbed_value, primary_output

__all__ = ["DEMO_MODEL", "build_demo_experiment", "run_demo"]

DEMO_MODEL = "predator-prey"


def _baseline_inputs(schema: ModelSchema) -> dict[str, Any]:
    baseline: dict[str, Any] = {}
    for param in schema.parameters:
        if param.nominal is None:
            raise ValueError(f"model {schema.model_id!r} parameter {param.name!r} has no nominal")
        baseline[param.name] = param.nominal
    return baseline


def build_demo_experiment(model_id: str = DEMO_MODEL) -> ExperimentSpec:
    """Build the baseline-vs-+10% experiment used by the demo and the UI sample."""
    schema = build_model(model_id).describe()
    baseline = _baseline_inputs(schema)
    target = next(
        (p for p in schema.parameters if p.role == "input"),
        next(p for p in schema.parameters if p.type in ("float", "int")),
    )
    target_value = perturbed_value(target, float(baseline[target.name]))
    return ExperimentSpec(
        name="DRW killer demo",
        hypothesis=(
            f"Increasing {target.name} by 10% changes the trajectory and the peak output; "
            "rank the other parameters by their influence on the peak."
        ),
        model_ref=ModelRef(model_id=model_id, version=schema.version),
        baseline=baseline,
        factors=(FactorSpec(parameter=target.name, values=(target_value,)),),
        outputs=tuple(o.name for o in schema.outputs if o.kind == "timeseries"),
        analyses=(AnalysisSpec(method="delta"), AnalysisSpec(method="relative_delta")),
        reporting=ReportingSpec(title="DRW killer demo", template="default"),
    )


def run_demo(
    model_id: str = DEMO_MODEL,
    out_dir: str | Path = ".drw/demo",
    *,
    zip_bundle: bool = False,
) -> dict[str, Any]:
    """Run the full demo and return a summary dictionary."""
    out = Path(out_dir)
    schema = build_model(model_id).describe()
    spec = build_demo_experiment(model_id)
    result = Runner().run(spec)
    manifest = build_evidence_package(result, out, zip_bundle=zip_bundle)

    metric = primary_output(schema)
    ranking = oat_sensitivity(
        schema,
        dict(result.baseline.inputs),
        result.baseline.metrics.get(metric),
        metric,
    )
    (out / "sensitivity.json").write_text(
        dumps_pretty(
            {
                "metric": metric,
                "perturbation": "+10%",
                "note": (
                    "OAT local sensitivity. abs_delta is scale-dependent; elasticity "
                    "(relative output change / relative input change) is the normalized, "
                    "cross-parameter comparison. OAT cannot detect interactions."
                ),
                "ranking": ranking,
            }
        )
        + "\n",
        encoding="utf-8",
    )

    return {
        "experiment_id": result.experiment_id,
        "manifest": manifest,
        "out_dir": out,
        "result": result,
        "ranking": ranking,
        "primary_output": metric,
    }
