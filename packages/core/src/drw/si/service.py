"""High-level SI orchestration used by the bridge and CLI.

This is where the loop is assembled: load durable state, build context, plan,
record the proposal, approve a step, execute it through the registry, interpret
the result, and update the investigation's durable state. It contains no science
and no provider logic - it wires the pieces together.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from drw.schema.si import (
    SIActionPreview,
    SIAnalysis,
    SIExecutionResult,
    SIInterpretation,
    SIInvestigationState,
    SIMessage,
    SIPlan,
)
from drw.si.actions import (
    SIActionContext,
    SIActionError,
    SIActionRegistry,
    default_registry,
)
from drw.si.context import build_action_context
from drw.si.executor import approve_step as _approve_step
from drw.si.executor import execute_step as _execute_step
from drw.si.executor import reject_step as _reject_step
from drw.si.planner import plan_analysis, preview_of
from drw.si.provider import SIProvider
from drw.si.store import SIStore

__all__ = [
    "approve_and_execute",
    "ask",
    "get_state",
    "list_actions",
    "preview_step",
    "reject_plan_step",
]


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _context(
    store: Any,
    state: SIInvestigationState,
    *,
    model_id: str | None,
) -> SIActionContext:
    project_id = state.project_id or "default"
    return build_action_context(
        store,
        investigation_id=state.investigation_id,
        project_id=project_id,
        model_id=model_id,
        state=state,
    )


def _sync_references(state: SIInvestigationState, ctx: SIActionContext) -> None:
    """Keep the investigation's referenced artifacts in sync with the stores."""
    if ctx.model_id and ctx.model_id not in state.models:
        state.models.append(ctx.model_id)

    def _sync(current: list[str], ids: list[str]) -> list[str]:
        merged = list(current)
        for item in ids:
            if item not in merged:
                merged.append(item)
        return merged

    try:
        experiments = [
            item["experiment_id"] for item in ctx.store.list(project_id=ctx.project_id)
        ]
    except Exception:  # pragma: no cover - defensive
        experiments = []
    state.experiments = _sync(state.experiments, experiments)

    if ctx.datasets is not None:
        state.datasets = _sync(
            state.datasets, [ref.dataset_id for ref in ctx.datasets.list()]
        )
    if ctx.models is not None:
        state.models = _sync(state.models, [ref.model_id for ref in ctx.models.list()])
    if ctx.simulations is not None:
        state.simulations = _sync(
            state.simulations, [ref.simulation_id for ref in ctx.simulations.list()]
        )
    if ctx.calibrations is not None:
        state.calibrations = _sync(
            state.calibrations, [ref.calibration_id for ref in ctx.calibrations.list()]
        )
    if ctx.validations is not None:
        state.validations = _sync(
            state.validations, [ref.validation_id for ref in ctx.validations.list()]
        )


def get_state(
    store: Any,
    investigation_id: str,
    *,
    project_id: str = "default",
    si_store: SIStore | None = None,
) -> SIInvestigationState:
    """Load or create the durable state for one investigation."""
    active_store = si_store or SIStore(store.root)
    state = active_store.load_or_create(investigation_id, project_id)
    ctx = _context(store, state, model_id=None)
    _sync_references(state, ctx)
    active_store.save(state, touch=False)
    return state


def ask(
    store: Any,
    investigation_id: str,
    question: str,
    *,
    project_id: str = "default",
    model_id: str | None = None,
    provider: SIProvider | None = None,
    registry: SIActionRegistry | None = None,
    si_store: SIStore | None = None,
) -> tuple[SIAnalysis, SIInvestigationState]:
    """Plan an answer to ``question`` and record it in the durable state."""
    active_store = si_store or SIStore(store.root)
    state = active_store.load_or_create(investigation_id, project_id)
    ctx = _context(store, state, model_id=model_id)
    _sync_references(state, ctx)

    analysis = plan_analysis(question, ctx, provider=provider, registry=registry)

    if not state.objective and question.strip():
        state.objective = question.strip()

    state.messages.append(
        SIMessage(
            message_id=f"msg-{len(state.messages) + 1}",
            role="user",
            text=question,
            at=_now(),
        )
    )
    state.messages.append(
        SIMessage(
            message_id=f"msg-{len(state.messages) + 2}",
            role="si",
            text=analysis.understanding,
            analysis=analysis,
            at=_now(),
        )
    )
    if analysis.plan is not None:
        if not any(plan.plan_id == analysis.plan.plan_id for plan in state.plans):
            state.plans.append(analysis.plan)
        state.current_plan_id = analysis.plan.plan_id
        next_step = analysis.plan.current_next_step()
        state.current_next_step = next_step.step_id if next_step is not None else None
        for question_text in analysis.plan.open_questions:
            if question_text not in state.unresolved_questions:
                state.unresolved_questions.append(question_text)
    for item in analysis.missing_information:
        if item not in state.unresolved_questions:
            state.unresolved_questions.append(item)

    active_store.save(state)
    return analysis, state


def _resolve_plan(state: SIInvestigationState, plan_id: str | None) -> SIPlan:
    if plan_id is not None:
        return state.plan(plan_id)
    plan = state.current_plan()
    if plan is None:
        raise SIActionError("not_found", "this investigation has no plan yet")
    return plan


def preview_step(
    store: Any,
    investigation_id: str,
    step_id: str,
    *,
    project_id: str = "default",
    model_id: str | None = None,
    plan_id: str | None = None,
    registry: SIActionRegistry | None = None,
    si_store: SIStore | None = None,
) -> SIActionPreview:
    """Exactly what a step will run, for the user to inspect before approval."""
    active_store = si_store or SIStore(store.root)
    state = active_store.load_or_create(investigation_id, project_id)
    plan = _resolve_plan(state, plan_id)
    step = plan.step(step_id)
    ctx = _context(store, state, model_id=model_id)
    return preview_of(step, ctx, registry=registry)


def approve_and_execute(
    store: Any,
    investigation_id: str,
    step_id: str,
    *,
    project_id: str = "default",
    model_id: str | None = None,
    plan_id: str | None = None,
    approved: bool = True,
    registry: SIActionRegistry | None = None,
    si_store: SIStore | None = None,
) -> tuple[SIExecutionResult, SIInterpretation, SIInvestigationState]:
    """Approve (explicitly) and execute one plan step, then update durable state.

    Read-only steps run without the approval flag. A step that creates or modifies
    an artifact requires ``approved=True`` - there is no implicit execution.
    """
    active_store = si_store or SIStore(store.root)
    state = active_store.load_or_create(investigation_id, project_id)
    plan = _resolve_plan(state, plan_id)
    ctx = _context(store, state, model_id=model_id)

    active_registry = registry or default_registry()
    action = active_registry.get(plan.step(step_id).action_id)
    if action.requires_approval:
        if not approved:
            raise SIActionError(
                "approval_required",
                f"action {action.action_id!r} creates an artifact and requires explicit "
                "approval (approved=true)",
            )
        _approve_step(plan, step_id)

    execution, interpretation = _execute_step(
        plan, step_id, ctx, registry=active_registry
    )

    state.executions.append(execution)
    state.interpretations.append(interpretation)
    state.decisions.append(
        f"{execution.status}: {execution.action_id} -> {execution.summary}"
    )
    for question_text in list(state.unresolved_questions):
        if question_text in plan.open_questions and execution.ok:
            state.unresolved_questions.remove(question_text)

    _sync_references(state, ctx)
    next_step = plan.current_next_step()
    state.current_next_step = next_step.step_id if next_step is not None else None
    active_store.save(state)
    return execution, interpretation, state


def reject_plan_step(
    store: Any,
    investigation_id: str,
    step_id: str,
    *,
    project_id: str = "default",
    plan_id: str | None = None,
    si_store: SIStore | None = None,
) -> SIInvestigationState:
    """Reject a step so it will not run."""
    active_store = si_store or SIStore(store.root)
    state = active_store.load_or_create(investigation_id, project_id)
    plan = _resolve_plan(state, plan_id)
    _reject_step(plan, step_id)
    next_step = plan.current_next_step()
    state.current_next_step = next_step.step_id if next_step is not None else None
    active_store.save(state)
    return state


def list_actions(registry: SIActionRegistry | None = None) -> list[dict[str, Any]]:
    """The action registry metadata (read-only capability discovery)."""
    active = registry or default_registry()
    from drw.schema.serialization import to_plain

    return [to_plain(ref) for ref in active.refs()]
