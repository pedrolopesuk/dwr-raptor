"""The SI context layer.

SI must not dump the whole project into every prompt. This module builds a
*deliberate* context: a compact, structured summary of what exists in the current
project and investigation, plus the list of actions SI may propose. The provider
sees summaries and references, never raw simulation data or results.
"""

from __future__ import annotations

from typing import Any

from drw.schema.serialization import to_plain
from drw.schema.si import SIActionRef, SIInvestigationState
from drw.si.actions import SIActionContext, SIActionRegistry, default_registry

__all__ = ["build_action_context", "build_context", "context_summary_lines"]


def build_action_context(
    store: Any,
    *,
    investigation_id: str,
    project_id: str,
    model_id: str | None = None,
    state: SIInvestigationState | None = None,
) -> SIActionContext:
    """Wire an :class:`SIActionContext` to the real, shared DRW stores."""
    from drw.calibration_store import CalibrationStore
    from drw.dataset_store import DatasetStore
    from drw.model_spec_store import ModelSpecStore
    from drw.model_store import ModelStore
    from drw.simulation_store import SimulationStore
    from drw.validation_store import ValidationStore

    return SIActionContext(
        store=store,
        project_id=project_id,
        investigation_id=investigation_id,
        model_id=model_id,
        state=state,
        datasets=DatasetStore(store.root),
        calibrations=CalibrationStore(store.root),
        validations=ValidationStore(store.root),
        model_specs=ModelSpecStore(store.root),
        models=ModelStore(store.root),
        simulations=SimulationStore(store.root),
    )


def _model_summaries() -> list[dict[str, Any]]:
    from drw.models.registry import model_schemas

    return [
        {
            "model_id": model_id,
            "version": schema.version,
            "description": schema.description,
            "n_parameters": len(schema.parameters),
            "n_outputs": len(schema.outputs),
        }
        for model_id, schema in sorted(model_schemas().items())
    ]


def _model_detail(model_id: str) -> dict[str, Any] | None:
    from drw.capabilities import model_capabilities
    from drw.models.registry import build_model

    try:
        schema = build_model(model_id).describe()
    except KeyError:
        return None
    return {
        "model_id": schema.model_id,
        "version": schema.version,
        "description": schema.description,
        "model_hash": schema.content_hash(),
        "parameters": [
            {
                "name": p.name,
                "type": p.type,
                "role": p.role,
                "unit": p.unit,
                "nominal": p.nominal,
                "lower": p.lower,
                "upper": p.upper,
            }
            for p in schema.parameters
        ],
        "outputs": [
            {"name": o.name, "kind": o.kind, "unit": o.unit, "axis_unit": o.axis_unit}
            for o in schema.outputs
        ],
        "capabilities": model_capabilities(schema),
    }


def _dataset_summaries(ctx: SIActionContext) -> list[dict[str, Any]]:
    from drw.schema.simulation import is_synthetic

    items: list[dict[str, Any]] = []
    if ctx.datasets is None:
        return items
    for ref in ctx.datasets.list():
        entry = {
            "dataset_id": ref.dataset_id,
            "name": ref.name,
            "content_hash": ref.content_hash,
            "source_kind": None,
            "synthetic": False,
        }
        try:
            provenance = ctx.datasets.provenance(ref.dataset_id)
            entry["source_kind"] = provenance.source_kind
            entry["synthetic"] = is_synthetic(provenance)
        except Exception:  # pragma: no cover - best-effort metadata
            pass
        items.append(entry)
    return items


def _safe(fn: Any, default: Any) -> Any:
    try:
        return fn()
    except Exception:
        return default


def build_context(
    ctx: SIActionContext,
    *,
    question: str,
    registry: SIActionRegistry | None = None,
) -> dict[str, Any]:
    """Build the structured context SI reasons over (JSON-ready).

    Deliberately selective: counts and summaries, not raw result payloads.
    """
    active_registry = registry or default_registry()

    project = _safe(lambda: to_plain(ctx.store.get_project(ctx.project_id)), None)
    experiments = _safe(lambda: to_plain(ctx.store.list(project_id=ctx.project_id)), [])
    calibrations = (
        _safe(lambda: to_plain(ctx.calibrations.list()), []) if ctx.calibrations else []
    )
    validations = (
        _safe(lambda: to_plain(ctx.validations.list()), []) if ctx.validations else []
    )

    investigation: dict[str, Any] = {}
    if ctx.state is not None:
        plan = ctx.state.current_plan()
        investigation = {
            "investigation_id": ctx.state.investigation_id,
            "objective": ctx.state.objective,
            "hypotheses": list(ctx.state.hypotheses),
            "assumptions": list(ctx.state.assumptions),
            "models": list(ctx.state.models),
            "datasets": list(ctx.state.datasets),
            "experiments": list(ctx.state.experiments),
            "calibrations": list(ctx.state.calibrations),
            "validations": list(ctx.state.validations),
            "simulations": list(ctx.state.simulations),
            "unresolved_questions": list(ctx.state.unresolved_questions),
            "decisions": list(ctx.state.decisions),
            "current_plan_id": ctx.state.current_plan_id,
            "next_step": to_plain(plan.current_next_step())
            if plan is not None
            else None,
        }

    actions: list[SIActionRef] = active_registry.refs()
    compiled_models = (
        _safe(lambda: to_plain(ctx.models.list()), []) if ctx.models else []
    )
    simulations = (
        _safe(lambda: to_plain(ctx.simulations.list()), []) if ctx.simulations else []
    )

    return {
        "question": question,
        "project": project,
        "investigation": investigation,
        "model_id": ctx.model_id,
        "model": _model_detail(ctx.model_id) if ctx.model_id else None,
        "models": _model_summaries(),
        "compiled_models": compiled_models,
        "datasets": _dataset_summaries(ctx),
        "experiments": experiments,
        "calibrations": calibrations,
        "validations": validations,
        "simulations": simulations,
        "actions": [
            {
                "action_id": ref.action_id,
                "name": ref.name,
                "description": ref.description,
                "category": ref.category,
                "read_only": ref.read_only,
                "requires_approval": ref.requires_approval,
                "supported": ref.supported,
                "effects": ref.effects,
            }
            for ref in actions
        ],
    }


def context_summary_lines(context: dict[str, Any]) -> list[str]:
    """Human-readable lines describing the context (used by the rule-based planner)."""
    lines: list[str] = []
    model = context.get("model")
    if model:
        lines.append(
            f"Selected model {model['model_id']} v{model['version']} "
            f"({len(model['parameters'])} parameters, {len(model['outputs'])} outputs)."
        )
    else:
        lines.append("No model is selected.")
    datasets = context.get("datasets") or []
    real = [d for d in datasets if not d.get("synthetic")]
    synthetic = [d for d in datasets if d.get("synthetic")]
    lines.append(
        f"{len(real)} empirical dataset(s), {len(synthetic)} synthetic dataset(s) available."
    )
    experiments = context.get("experiments") or []
    lines.append(f"{len(experiments)} stored experiment(s) in this project.")
    calibrations = context.get("calibrations") or []
    validations = context.get("validations") or []
    lines.append(
        f"{len(calibrations)} stored calibration(s), {len(validations)} stored validation(s)."
    )
    return lines
