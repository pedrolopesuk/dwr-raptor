"""Unit tests for approval enforcement and deterministic step execution."""

from __future__ import annotations

import pytest

from drw.schema.si import SIPlan, SIPlanStep
from drw.si.actions import SIActionError
from drw.si.context import build_action_context
from drw.si.executor import (
    approve_step,
    dependencies_satisfied,
    execute_step,
    next_runnable_step,
    reject_step,
)
from drw.si.store import new_state
from drw.store import ExperimentStore

pytestmark = pytest.mark.unit


def _plan(*steps: SIPlanStep) -> SIPlan:
    return SIPlan(plan_id="plan-x", objective="objective", steps=list(steps))


def _step(step_id: str, action_id: str, approval="required", **kwargs) -> SIPlanStep:
    return SIPlanStep(
        step_id=step_id, purpose="p", action_id=action_id, approval=approval, **kwargs
    )


def _ctx(tmp_path):
    store = ExperimentStore(tmp_path / "ws")
    return build_action_context(
        store,
        investigation_id="draft",
        project_id="default",
        state=new_state("draft", "default"),
    )


def test_read_only_step_executes_without_approval(tmp_path):
    ctx = _ctx(tmp_path)
    plan = _plan(_step("step-1", "inspect_investigation", approval="not_required"))
    execution, interpretation = execute_step(plan, "step-1", ctx)
    assert execution.status == "executed"
    assert execution.ok is True
    assert interpretation.step_id == "step-1"
    assert plan.step("step-1").execution is execution


def test_mutating_step_requires_explicit_approval(tmp_path):
    ctx = _ctx(tmp_path)
    plan = _plan(_step("step-1", "create_experiment"))
    with pytest.raises(SIActionError) as exc:
        execute_step(plan, "step-1", ctx)
    assert exc.value.code == "approval_required"
    assert plan.step("step-1").status == "proposed"


def test_approved_mutating_step_runs(tmp_path):
    ctx = _ctx(tmp_path)
    plan = _plan(_step("step-1", "create_experiment"))
    approve_step(plan, "step-1")
    execution, _ = execute_step(plan, "step-1", ctx)
    # The action is supported; the failure here is a missing/invalid spec, not approval.
    assert execution.status == "failed"
    assert execution.error_code == "bad_request"


def test_unsupported_action_is_recorded_not_executed(tmp_path):
    from drw.si.actions import SIAction, SIActionRegistry

    ctx = _ctx(tmp_path)
    registry = SIActionRegistry(
        [
            SIAction(
                action_id="not_yet",
                name="Not yet",
                description="A declared but unsupported capability.",
                category="simulation",
                read_only=False,
                supported=False,
                limitations=("this capability is not implemented",),
            )
        ]
    )
    plan = _plan(_step("step-1", "not_yet"))
    approve_step(plan, "step-1")
    execution, interpretation = execute_step(plan, "step-1", ctx, registry=registry)
    assert execution.status == "unsupported"
    assert execution.ok is False
    assert execution.error_code == "unsupported_action"
    assert "Not performed" in interpretation.text


def test_unknown_action_on_a_step_fails_closed(tmp_path):
    ctx = _ctx(tmp_path)
    plan = _plan(_step("step-1", "definitely_not_registered", approval="not_required"))
    execution, _ = execute_step(plan, "step-1", ctx)
    assert execution.status == "failed"
    assert execution.error_code == "unknown_action"


def test_dependency_must_be_satisfied(tmp_path):
    ctx = _ctx(tmp_path)
    plan = _plan(
        _step("step-1", "inspect_investigation", approval="not_required"),
        _step(
            "step-2",
            "inspect_model",
            approval="not_required",
            inputs={"model_id": "predator-prey"},
            depends_on=("step-1",),
        ),
    )
    assert dependencies_satisfied(plan, plan.step("step-2")) is False
    with pytest.raises(SIActionError) as exc:
        execute_step(plan, "step-2", ctx)
    assert exc.value.code == "dependency_not_satisfied"

    execute_step(plan, "step-1", ctx)
    assert dependencies_satisfied(plan, plan.step("step-2")) is True
    execution, _ = execute_step(plan, "step-2", ctx)
    assert execution.ok is True


def test_missing_dependency_never_becomes_runnable(tmp_path):
    plan = _plan(
        _step(
            "step-1", "inspect_project", approval="not_required", depends_on=("gone",)
        )
    )
    assert dependencies_satisfied(plan, plan.step("step-1")) is False
    assert next_runnable_step(plan) is None


def test_steps_cannot_run_twice(tmp_path):
    ctx = _ctx(tmp_path)
    plan = _plan(_step("step-1", "inspect_investigation", approval="not_required"))
    execute_step(plan, "step-1", ctx)
    with pytest.raises(SIActionError) as exc:
        execute_step(plan, "step-1", ctx)
    assert exc.value.code == "bad_request"


def test_reject_prevents_execution(tmp_path):
    ctx = _ctx(tmp_path)
    plan = _plan(_step("step-1", "create_experiment"))
    reject_step(plan, "step-1")
    assert plan.step("step-1").status == "rejected"
    with pytest.raises(SIActionError):
        execute_step(plan, "step-1", ctx)


def test_interpretation_carries_next_steps(tmp_path):
    ctx = _ctx(tmp_path)
    plan = _plan(_step("step-1", "inspect_project", approval="not_required"))
    _, interpretation = execute_step(plan, "step-1", ctx)
    assert interpretation.establishes == []
    assert interpretation.does_not_establish
