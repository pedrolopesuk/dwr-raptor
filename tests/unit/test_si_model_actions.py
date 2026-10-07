"""Unit tests for the SI model-generation and simulation actions."""

from __future__ import annotations

import pytest

from drw.schema.model import ModelRef
from drw.schema.model_spec import (
    ModelSpecification,
    ModelSpecParameter,
    ModelSpecProvenance,
    ModelSpecRelationship,
    ModelSpecVariable,
)
from drw.schema.si import SIPlan, SIPlanStep
from drw.schema.simulation import SimulationConfig, SimulationSpec
from drw.si.actions import SIActionError, default_registry
from drw.si.context import build_action_context
from drw.si.executor import approve_step, execute_step
from drw.si.store import new_state
from drw.store import ExperimentStore

pytestmark = pytest.mark.unit

_AT = "2026-01-01T00:00:00+00:00"


def _specification() -> dict:
    return ModelSpecification(
        model_id="decay",
        version="1.0.0",
        description="First-order decay.",
        domain="physics",
        kind="ode",
        parameters=(
            ModelSpecParameter(
                name="k", unit="1/s", nominal=0.5, lower=0.01, upper=5.0
            ),
        ),
        variables=(ModelSpecVariable(name="y", kind="state", unit="count"),),
        relationships=(
            ModelSpecRelationship(
                name="dy_dt", expression="-k * y", depends_on=("k", "y"), rate_of="y"
            ),
        ),
        initial_conditions={"y": 1.0},
        execution={"t_span": [0.0, 5.0], "n_points": 51},
        provenance=ModelSpecProvenance(created_at=_AT),
    ).model_dump(mode="json")


def _ctx(root):
    return build_action_context(
        ExperimentStore(root),
        investigation_id="draft",
        project_id="default",
        state=new_state("draft", "default"),
    )


def _plan(*steps: SIPlanStep) -> SIPlan:
    return SIPlan(plan_id="plan-x", objective="o", steps=list(steps))


def _step(step_id: str, action_id: str, inputs: dict, approval: str = "required", **kw):
    return SIPlanStep(
        step_id=step_id,
        purpose="p",
        action_id=action_id,
        inputs=inputs,
        approval=approval,
        **kw,
    )


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    root = tmp_path / "ws"
    monkeypatch.setenv("DRW_WORKSPACE", str(root))
    return root


def test_create_model_requires_approval(workspace):
    ctx = _ctx(workspace)
    plan = _plan(_step("step-1", "create_model", {"specification": _specification()}))
    with pytest.raises(SIActionError) as exc:
        execute_step(plan, "step-1", ctx)
    assert exc.value.code == "approval_required"
    assert ctx.models.list() == []


def test_create_model_compiles_and_persists_after_approval(workspace):
    ctx = _ctx(workspace)
    plan = _plan(_step("step-1", "create_model", {"specification": _specification()}))
    approve_step(plan, "step-1")
    execution, interpretation = execute_step(plan, "step-1", ctx)
    assert execution.status == "executed"
    assert execution.ok is True
    model_id = execution.artifacts["model_id"]
    assert model_id.startswith("mdl-")
    assert ctx.models.exists(model_id)
    assert execution.result["compiler"]["version"]
    assert interpretation.establishes
    assert any(
        "reality" in item.lower() or "valid" in item.lower()
        for item in interpretation.does_not_establish
    )


def test_create_model_fails_closed_for_an_unsupported_specification(workspace):
    ctx = _ctx(workspace)
    specification = _specification()
    specification["kind"] = "algebraic"
    plan = _plan(_step("step-1", "create_model", {"specification": specification}))
    approve_step(plan, "step-1")
    execution, _ = execute_step(plan, "step-1", ctx)
    assert execution.status == "failed"
    assert execution.error_code == "unsupported_model_kind"
    assert ctx.models.list() == []


def test_create_model_preview_rejects_invalid_input(workspace):
    ctx = _ctx(workspace)
    preview = default_registry().preview(
        "create_model", {"specification": {"not": "a specification"}}, ctx
    )
    assert any(d.level == "error" for d in preview.input_diagnostics)
    assert preview.requires_approval is True


def test_simulate_requires_approval_and_a_created_model(workspace):
    ctx = _ctx(workspace)

    # The model was never created: the simulation fails closed.
    missing = SimulationSpec(
        model_ref=ModelRef(model_id="mdl-000000000000", version="1.0.0"),
        model_hash="",
        parameters={},
        initial_conditions={},
        config=SimulationConfig(t_span=(0.0, 5.0), n_points=51),
    )
    plan = _plan(
        _step("step-1", "simulate", {"simulation": missing.model_dump(mode="json")})
    )
    approve_step(plan, "step-1")
    execution, _ = execute_step(plan, "step-1", ctx)
    assert execution.status == "failed"
    assert execution.error_code == "unknown_model"


def test_simulate_runs_and_stores_a_synthetic_dataset(workspace):
    ctx = _ctx(workspace)

    # Create the model through the real action first.
    create_plan = _plan(
        _step("create", "create_model", {"specification": _specification()})
    )
    approve_step(create_plan, "create")
    create_execution, _ = execute_step(create_plan, "create", ctx)
    model_id = create_execution.artifacts["model_id"]
    model_hash = create_execution.result["model_hash"]

    spec = SimulationSpec(
        model_ref=ModelRef(model_id=model_id, version="1.0.0"),
        model_hash=model_hash,
        parameters={"k": 0.5},
        initial_conditions={"y": 1.0},
        scenario="nominal",
        config=SimulationConfig(t_span=(0.0, 5.0), n_points=51, seed=0),
    )
    plan = _plan(
        _step(
            "simulate",
            "simulate",
            {"simulation": spec.model_dump(mode="json"), "model_id": model_id},
        )
    )
    approve_step(plan, "simulate")
    execution, interpretation = execute_step(plan, "simulate", ctx)
    assert execution.status == "executed", execution.error_message
    assert execution.result["synthetic"] is True
    dataset_id = execution.artifacts["dataset_id"]
    assert ctx.datasets.exists(dataset_id)
    assert "simulation_id" in execution.artifacts
    assert "not evidence about the world" in interpretation.text.lower()
    assert any(
        "real" in item.lower() or "reality" in item.lower()
        for item in interpretation.does_not_establish
    )


def test_dependency_ordering_blocks_simulation_before_model_creation(workspace):
    ctx = _ctx(workspace)
    spec = SimulationSpec(
        model_ref=ModelRef(model_id="mdl-000000000000", version="1.0.0"),
        model_hash="",
        parameters={},
        initial_conditions={},
        config=SimulationConfig(t_span=(0.0, 5.0), n_points=51),
    )
    plan = _plan(
        _step("create", "create_model", {"specification": _specification()}),
        _step(
            "simulate",
            "simulate",
            {"simulation": spec.model_dump(mode="json")},
            depends_on=("create",),
        ),
    )
    with pytest.raises(SIActionError) as exc:
        execute_step(plan, "simulate", ctx)
    assert exc.value.code == "dependency_not_satisfied"
