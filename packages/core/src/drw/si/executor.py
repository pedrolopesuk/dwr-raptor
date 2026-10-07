"""Approval enforcement and deterministic step execution.

Read-only actions may run without approval; every action that creates or modifies
an artifact requires the step to be explicitly ``approved`` first. Execution only
ever goes through the action registry - SI never calls an internal function
directly - and every outcome is a structured :class:`SIExecutionResult` with an
interpretation.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime

from drw.schema.si import (
    SIExecutionResult,
    SIInterpretation,
    SIPlan,
    SIPlanStep,
)
from drw.si.actions import (
    SIActionContext,
    SIActionError,
    SIActionRegistry,
    default_registry,
)
from drw.si.interpreter import interpret

__all__ = [
    "approve_step",
    "dependencies_satisfied",
    "execute_step",
    "next_runnable_step",
    "reject_step",
]


def _now() -> str:
    return datetime.now(UTC).isoformat()


def approve_step(plan: SIPlan, step_id: str) -> SIPlanStep:
    """Mark a step approved (the explicit user decision)."""
    step = plan.step(step_id)
    if step.status in ("executed", "failed"):
        raise SIActionError("bad_request", f"step {step_id!r} has already run")
    step.approval = "approved"
    step.status = "approved"
    return step


def reject_step(plan: SIPlan, step_id: str) -> SIPlanStep:
    """Mark a step rejected; it will not run."""
    step = plan.step(step_id)
    step.approval = "rejected"
    step.status = "rejected"
    return step


def dependencies_satisfied(plan: SIPlan, step: SIPlanStep) -> bool:
    """Whether every dependency has executed successfully."""
    for dependency in step.depends_on:
        try:
            candidate = plan.step(dependency)
        except KeyError:
            return False
        if candidate.status != "executed":
            return False
    return True


def next_runnable_step(plan: SIPlan) -> SIPlanStep | None:
    """The next step that is proposed/approved and whose dependencies have run."""
    for step in plan.steps:
        if step.status in ("proposed", "approved") and dependencies_satisfied(
            plan, step
        ):
            return step
    return None


def execute_step(
    plan: SIPlan,
    step_id: str,
    ctx: SIActionContext,
    *,
    registry: SIActionRegistry | None = None,
    now: Callable[[], str] | None = None,
) -> tuple[SIExecutionResult, SIInterpretation]:
    """Execute one step, enforcing approval and dependency order.

    Raises :class:`SIActionError` for a request-level problem (unknown step,
    missing approval, unsatisfied dependency). A failure *inside* an action is
    captured as a failed :class:`SIExecutionResult`, not raised.
    """
    active_registry = registry or default_registry()
    clock = now or _now
    step = plan.step(step_id)

    if step.status in ("executed", "failed", "rejected", "unsupported"):
        raise SIActionError(
            "bad_request", f"step {step_id!r} is not runnable (status {step.status!r})"
        )
    if not dependencies_satisfied(plan, step):
        raise SIActionError(
            "dependency_not_satisfied",
            f"step {step_id!r} depends on a step that has not executed successfully",
        )

    try:
        action = active_registry.get(step.action_id)
    except SIActionError as exc:
        execution = _failed(step, exc.code, exc.message, clock)
        interpretation = interpret(
            execution,
            interpretation_id=_interpretation_id(step),
            at=execution.finished_at or _now(),
        )
        step.status = execution.status
        step.execution = execution
        return execution, interpretation

    if action.requires_approval and step.approval != "approved":
        raise SIActionError(
            "approval_required",
            f"action {action.action_id!r} creates an artifact and requires explicit approval",
        )

    if not action.supported:
        reason = (
            action.limitations[0]
            if action.limitations
            else "This action is not supported yet."
        )
        execution = _result(
            step,
            action.action_id,
            "unsupported",
            False,
            summary=reason,
            error_code="unsupported_action",
            error_message=reason,
            clock=clock,
        )
        interpretation = interpret(
            execution,
            interpretation_id=_interpretation_id(step),
            at=execution.finished_at or _now(),
        )
        step.status = "unsupported"
        step.execution = execution
        return execution, interpretation

    if (
        action.execute is None
    ):  # pragma: no cover - every supported action has an executor
        execution = _failed(
            step, "unsupported_action", "the action has no executor", clock
        )
        step.status = execution.status
        step.execution = execution
        return execution, interpret(
            execution,
            interpretation_id=_interpretation_id(step),
            at=execution.finished_at or _now(),
        )

    started = clock()
    try:
        outcome = action.execute(dict(step.inputs), ctx)
    except SIActionError as exc:
        execution = _result(
            step,
            action.action_id,
            "failed",
            False,
            summary=exc.message,
            error_code=exc.code,
            error_message=exc.message,
            diagnostics=tuple(_diagnostics(exc.diagnostics)),
            started_at=started,
            clock=clock,
        )
    except KeyError as exc:
        execution = _result(
            step,
            action.action_id,
            "failed",
            False,
            summary=str(exc).strip("'"),
            error_code="not_found",
            error_message=str(exc).strip("'"),
            started_at=started,
            clock=clock,
        )
    except Exception as exc:  # the executor must never leak a traceback
        execution = _result(
            step,
            action.action_id,
            "failed",
            False,
            summary=f"{type(exc).__name__}: {exc}",
            error_code="internal_error",
            error_message=f"{type(exc).__name__}: {exc}",
            started_at=started,
            clock=clock,
        )
    else:
        execution = _result(
            step,
            action.action_id,
            "executed",
            True,
            summary=outcome.summary,
            result=outcome.result,
            artifacts=outcome.artifacts,
            diagnostics=outcome.diagnostics,
            started_at=started,
            clock=clock,
        )

    step.status = execution.status
    step.execution = execution
    interpretation = interpret(
        execution,
        interpretation_id=_interpretation_id(step),
        at=execution.finished_at or _now(),
    )
    return execution, interpretation


def _interpretation_id(step: SIPlanStep) -> str:
    return f"interp-{step.step_id}"


def _diagnostics(raw: object) -> list:
    from drw.schema.result import Diagnostic

    items = raw if isinstance(raw, (list, tuple)) else []
    out: list[Diagnostic] = []
    for item in items:
        if isinstance(item, Diagnostic):
            out.append(item)
        elif isinstance(item, dict) and "message" in item:
            level = item.get("level", "error")
            out.append(
                Diagnostic(
                    level=level if level in ("info", "warning", "error") else "error",
                    code=str(item.get("code", "action_error")),
                    message=str(item["message"]),
                )
            )
    return out


def _result(
    step: SIPlanStep,
    action_id: str,
    status: str,
    ok: bool,
    *,
    summary: str = "",
    result: dict | None = None,
    artifacts: dict | None = None,
    diagnostics: tuple = (),
    error_code: str | None = None,
    error_message: str | None = None,
    started_at: str | None = None,
    clock: Callable[[], str],
) -> SIExecutionResult:
    return SIExecutionResult(
        step_id=step.step_id,
        action_id=action_id,
        status=status,  # type: ignore[arg-type]
        ok=ok,
        summary=summary,
        result=result or {},
        artifacts=artifacts or {},
        diagnostics=diagnostics,
        error_code=error_code,
        error_message=error_message,
        started_at=started_at,
        finished_at=clock(),
    )


def _failed(
    step: SIPlanStep, code: str, message: str, clock: Callable[[], str]
) -> SIExecutionResult:
    return _result(
        step,
        step.action_id,
        "failed",
        False,
        summary=message,
        error_code=code,
        error_message=message,
        clock=clock,
    )
