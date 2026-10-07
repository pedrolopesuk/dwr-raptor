"""Unit tests for the structured SI contracts."""

from __future__ import annotations

import pytest

from drw.schema.si import (
    SIAnalysis,
    SIExecutionResult,
    SIInvestigationState,
    SIPlan,
    SIPlanStep,
    compute_plan_id,
)

pytestmark = pytest.mark.unit


def _step(step_id: str, action_id: str, **kwargs) -> SIPlanStep:
    return SIPlanStep(step_id=step_id, purpose="purpose", action_id=action_id, **kwargs)


def test_plan_id_is_deterministic_and_status_independent():
    steps = [
        _step("step-1", "inspect_investigation"),
        _step("step-2", "create_experiment", inputs={"spec": {"a": 1}}),
    ]
    first = compute_plan_id("objective", steps)
    steps[0].status = "executed"
    steps[0].approval = "approved"
    second = compute_plan_id("objective", steps)
    assert first == second
    assert first.startswith("plan-")


def test_plan_id_changes_with_inputs():
    a = compute_plan_id(
        "o", [_step("step-1", "sensitivity", inputs={"experiment_id": "exp-1"})]
    )
    b = compute_plan_id(
        "o", [_step("step-1", "sensitivity", inputs={"experiment_id": "exp-2"})]
    )
    assert a != b


def test_step_approval_and_runnability():
    mutating = _step("step-1", "create_experiment", approval="required")
    assert mutating.requires_approval is True
    assert mutating.runnable is False

    mutating.approval = "approved"
    mutating.status = "approved"
    assert mutating.runnable is True

    read_only = _step("step-1", "inspect_model", approval="not_required")
    assert read_only.requires_approval is False
    assert read_only.runnable is True

    rejected = _step(
        "step-1", "create_experiment", approval="rejected", status="rejected"
    )
    assert rejected.runnable is False


def test_plan_lookup_and_next_step():
    plan = SIPlan(
        plan_id="plan-x",
        objective="o",
        steps=[
            _step("step-1", "inspect_investigation"),
            _step("step-2", "create_experiment"),
        ],
    )
    assert plan.step("step-2").action_id == "create_experiment"
    assert plan.current_next_step().step_id == "step-1"
    plan.step("step-1").status = "executed"
    assert plan.current_next_step().step_id == "step-2"
    with pytest.raises(KeyError):
        plan.step("missing")


def test_execution_result_and_interpretation_are_structured():
    result = SIExecutionResult(
        step_id="step-1",
        action_id="create_experiment",
        status="executed",
        ok=True,
        artifacts={"experiment_id": "exp-000000000001"},
    )
    assert result.ok is True
    assert result.artifacts["experiment_id"] == "exp-000000000001"


def test_state_holds_analysis_and_current_plan():
    analysis = SIAnalysis(question="q", understanding="u")
    state = SIInvestigationState(
        investigation_id="draft",
        created_at="2026-01-01T00:00:00+00:00",
        updated_at="2026-01-01T00:00:00+00:00",
    )
    plan = SIPlan(
        plan_id="plan-x", objective="o", steps=[_step("step-1", "inspect_project")]
    )
    state.plans.append(plan)
    state.current_plan_id = plan.plan_id
    assert analysis.plan is None
    assert state.current_plan().plan_id == "plan-x"
    state.current_plan_id = "plan-missing"
    assert state.current_plan() is None
