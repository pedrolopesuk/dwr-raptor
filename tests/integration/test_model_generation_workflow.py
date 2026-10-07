"""Integration tests: model generation + simulation through the SI bridge."""

from __future__ import annotations

import pytest

from drw.api import handle
from drw.model_compiler import compile_model_spec
from drw.model_store import ModelStore
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
from drw.si.context import build_action_context
from drw.si.planner import plan_analysis
from drw.si.store import SIStore, new_state
from drw.store import ExperimentStore

pytestmark = pytest.mark.integration

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
        assumptions=("constant rate",),
        initial_conditions={"y": 1.0},
        execution={"t_span": [0.0, 5.0], "n_points": 51},
        provenance=ModelSpecProvenance(created_at=_AT),
    ).model_dump(mode="json")


def _seed_plan(root, *steps: SIPlanStep) -> None:
    store = SIStore(root)
    state = new_state("draft", "default")
    plan = SIPlan(
        plan_id="plan-generation", objective="build and simulate", steps=list(steps)
    )
    state.plans.append(plan)
    state.current_plan_id = plan.plan_id
    store.save(state)


def _step(step_id: str, action_id: str, inputs: dict, **kw) -> SIPlanStep:
    return SIPlanStep(
        step_id=step_id, purpose="p", action_id=action_id, inputs=inputs, **kw
    )


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    root = tmp_path / "ws"
    monkeypatch.setenv("DRW_WORKSPACE", str(root))
    return root, ExperimentStore(root)


def test_create_model_requires_approval_then_compiles(workspace):
    root, store = workspace
    _seed_plan(
        root, _step("create", "create_model", {"specification": _specification()})
    )

    preview = handle(
        {
            "op": "si_preview",
            "params": {"investigation_id": "draft", "step_id": "create"},
        },
        store=store,
    )
    assert preview["ok"], preview
    assert preview["data"]["preview"]["requires_approval"] is True
    assert preview["data"]["preview"]["effects"] == "modifies_model"

    refused = handle(
        {
            "op": "si_execute",
            "params": {
                "investigation_id": "draft",
                "step_id": "create",
                "approve": False,
            },
        },
        store=store,
    )
    assert refused["ok"] is False
    assert refused["error"]["code"] == "approval_required"
    assert ModelStore(root).list() == []

    approved = handle(
        {
            "op": "si_execute",
            "params": {
                "investigation_id": "draft",
                "step_id": "create",
                "approve": True,
            },
        },
        store=store,
    )
    assert approved["ok"], approved
    execution = approved["data"]["execution"]
    assert execution["status"] == "executed"
    model_id = execution["artifacts"]["model_id"]
    assert ModelStore(root).exists(model_id)
    assert execution["result"]["compiler"]["version"]
    assert approved["data"]["interpretation"]["establishes"]


def test_full_generation_and_simulation_loop(workspace):
    root, store = workspace

    # 1. create_model (approval required).
    _seed_plan(
        root, _step("create", "create_model", {"specification": _specification()})
    )
    created = handle(
        {
            "op": "si_execute",
            "params": {
                "investigation_id": "draft",
                "step_id": "create",
                "approve": True,
            },
        },
        store=store,
    )
    assert created["ok"], created
    execution = created["data"]["execution"]
    model_id = execution["artifacts"]["model_id"]
    model_hash = execution["result"]["model_hash"]

    # 2. simulate the compiled model (approval required).
    simulation = SimulationSpec(
        model_ref=ModelRef(model_id=model_id, version="1.0.0"),
        model_hash=model_hash,
        parameters={"k": 0.5},
        initial_conditions={"y": 1.0},
        scenario="nominal",
        config=SimulationConfig(t_span=(0.0, 5.0), n_points=51, seed=0),
    )
    _seed_plan(
        root,
        _step(
            "simulate",
            "simulate",
            {"simulation": simulation.model_dump(mode="json"), "model_id": model_id},
        ),
    )
    refused = handle(
        {
            "op": "si_execute",
            "params": {
                "investigation_id": "draft",
                "step_id": "simulate",
                "approve": False,
            },
        },
        store=store,
    )
    assert refused["ok"] is False
    assert refused["error"]["code"] == "approval_required"

    simulated = handle(
        {
            "op": "si_execute",
            "params": {
                "investigation_id": "draft",
                "step_id": "simulate",
                "approve": True,
            },
        },
        store=store,
    )
    assert simulated["ok"], simulated
    sim_execution = simulated["data"]["execution"]
    assert sim_execution["status"] == "executed", sim_execution["error_message"]
    assert sim_execution["result"]["synthetic"] is True
    dataset_id = sim_execution["artifacts"]["dataset_id"]
    interpretation = simulated["data"]["interpretation"]
    assert "not evidence about the world" in interpretation["text"].lower()

    # 3. The investigation records the created model, simulation and dataset.
    state = handle(
        {
            "op": "si_state",
            "params": {"investigation_id": "draft", "project_id": "default"},
        },
        store=store,
    )["data"]["state"]
    assert model_id in state["models"]
    assert dataset_id in state["datasets"]
    assert sim_execution["artifacts"]["simulation_id"] in state["simulations"]

    # 4. The generated model is now visible to the rest of DRW.
    models = handle({"op": "list_models", "params": {}}, store=store)["data"]["models"]
    assert model_id in {item["model_id"] for item in models}
    described = handle(
        {"op": "describe_model", "params": {"model_id": model_id}}, store=store
    )
    assert described["ok"]
    assert described["data"]["schema"]["runtime"] == "drw/compiled-ode"

    # 5. The synthetic dataset is refused by the empirical guard.
    from drw.dataset_store import DatasetStore
    from drw.schema.simulation import SyntheticObservationError, assert_empirical

    provenance = DatasetStore(root).provenance(dataset_id)
    assert provenance.source_kind == "synthetic"
    with pytest.raises(SyntheticObservationError):
        assert_empirical(provenance, what="Evaluation")


def test_simulation_is_idempotent_through_the_bridge(workspace):
    root, store = workspace
    compiled = compile_model_spec(ModelSpecification.model_validate(_specification()))
    ModelStore(root).save(compiled)
    simulation = SimulationSpec(
        model_ref=ModelRef(model_id=compiled.model_id, version="1.0.0"),
        model_hash=compiled.schema.content_hash(),
        parameters={"k": 0.5},
        initial_conditions={"y": 1.0},
        config=SimulationConfig(t_span=(0.0, 5.0), n_points=51),
    )
    _seed_plan(
        root,
        _step(
            "simulate", "simulate", {"simulation": simulation.model_dump(mode="json")}
        ),
    )
    first = handle(
        {
            "op": "si_execute",
            "params": {
                "investigation_id": "draft",
                "step_id": "simulate",
                "approve": True,
            },
        },
        store=store,
    )
    assert first["ok"], first
    dataset_id = first["data"]["execution"]["artifacts"]["dataset_id"]

    # Re-seed and execute again: identical requests are idempotent (not re-run).
    _seed_plan(
        root,
        _step(
            "simulate", "simulate", {"simulation": simulation.model_dump(mode="json")}
        ),
    )
    second = handle(
        {
            "op": "si_execute",
            "params": {
                "investigation_id": "draft",
                "step_id": "simulate",
                "approve": True,
            },
        },
        store=store,
    )
    assert second["ok"], second
    assert second["data"]["execution"]["result"].get("idempotent") is True
    assert second["data"]["execution"]["artifacts"]["dataset_id"] == dataset_id


def test_rule_based_planner_does_not_invent_a_model(workspace):
    _root, store = workspace
    ctx = build_action_context(
        store, investigation_id="draft", project_id="default", model_id="predator-prey"
    )
    analysis = plan_analysis("I don't have a model yet. Can you construct one?", ctx)
    action_ids = [step.action_id for step in analysis.plan.steps]
    assert "create_model" not in action_ids
    assert any(
        "model specification" in item.lower() for item in analysis.missing_information
    )


class _BadProvider:
    name = "fake"

    def respond(self, *, question, context):
        return {
            "steps": [
                {
                    "action_id": "create_model",
                    "inputs": {
                        "specification": {
                            "model_id": "x",
                            "kind": "algebraic",
                            "provenance": {"created_at": _AT},
                        }
                    },
                    "purpose": "compile",
                }
            ]
        }


def test_malformed_provider_output_cannot_bypass_validation(workspace):
    _root, store = workspace
    ctx = build_action_context(
        store, investigation_id="draft", project_id="default", model_id="predator-prey"
    )
    analysis = plan_analysis("build a model", ctx, provider=_BadProvider())
    assert analysis.used_ai is False
    assert all(step.action_id != "create_model" for step in analysis.plan.steps)
    assert any("ignored ai step" in caveat.lower() for caveat in analysis.caveats)
