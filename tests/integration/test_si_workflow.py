"""Integration tests: the SI loop through the bridge, with real execution.

These exercise the full vertical slice deterministically (no LLM provider
configured): ask -> plan -> preview -> approve -> execute -> interpret, plus the
safety properties (approval enforcement, synthetic-data refusal, unsupported
actions, no arbitrary execution).
"""

from __future__ import annotations

import pytest

from drw.api import handle
from drw.dataset_store import DatasetStore
from drw.execution.runner import Runner
from drw.model_spec_store import ModelSpecStore
from drw.observations import build_dataset
from drw.schema.experiment import (
    AnalysisSpec,
    ExecutionSpec,
    ExperimentSpec,
    FactorSpec,
)
from drw.schema.model import ModelRef
from drw.schema.observation import (
    MappingPair,
    ObservationMapping,
    ObservationSet,
    Provenance,
    Variable,
)
from drw.schema.si import SIPlan, SIPlanStep
from drw.si.store import SIStore, new_state
from drw.store import ExperimentStore

pytestmark = pytest.mark.integration


def _store(tmp_path) -> ExperimentStore:
    return ExperimentStore(tmp_path / "ws")


def _seed_plan(store: ExperimentStore, steps: list[SIPlanStep]) -> None:
    si_store = SIStore(store.root)
    state = new_state("draft", "default")
    plan = SIPlan(plan_id="plan-manual", objective="manual plan", steps=steps)
    state.plans.append(plan)
    state.current_plan_id = plan.plan_id
    si_store.save(state)


def _ask_design(store: ExperimentStore) -> dict:
    response = handle(
        {
            "op": "si_ask",
            "params": {
                "investigation_id": "draft",
                "question": "Design an experiment to see how alpha changes the prey peak.",
                "model_id": "predator-prey",
                "project_id": "default",
            },
        },
        store=store,
    )
    assert response["ok"], response
    return response["data"]


def test_si_loop_plans_approves_executes_and_interprets(tmp_path):
    store = _store(tmp_path)
    data = _ask_design(store)
    steps = data["analysis"]["plan"]["steps"]
    action_ids = [step["action_id"] for step in steps]
    assert action_ids[0] == "inspect_investigation"
    assert "create_experiment" in action_ids
    create = next(step for step in steps if step["action_id"] == "create_experiment")

    preview = handle(
        {
            "op": "si_preview",
            "params": {
                "investigation_id": "draft",
                "step_id": create["step_id"],
                "model_id": "predator-prey",
            },
        },
        store=store,
    )
    assert preview["ok"], preview
    assert preview["data"]["preview"]["requires_approval"] is True
    assert preview["data"]["preview"]["effects"] == "creates_experiment"

    for step in steps:
        if step["action_id"] == "create_experiment":
            continue
        response = handle(
            {
                "op": "si_execute",
                "params": {
                    "investigation_id": "draft",
                    "step_id": step["step_id"],
                    "model_id": "predator-prey",
                    "approve": True,
                },
            },
            store=store,
        )
        assert response["ok"], response
        assert response["data"]["execution"]["ok"] is True

    response = handle(
        {
            "op": "si_execute",
            "params": {
                "investigation_id": "draft",
                "step_id": create["step_id"],
                "model_id": "predator-prey",
                "approve": True,
            },
        },
        store=store,
    )
    assert response["ok"], response
    execution = response["data"]["execution"]
    assert execution["status"] == "executed"
    assert execution["ok"] is True
    experiment_id = execution["artifacts"]["experiment_id"]
    assert store.exists(experiment_id)

    interpretation = response["data"]["interpretation"]
    assert interpretation["does_not_establish"]
    assert any(
        "reality" in item.lower() or "correct" in item.lower()
        for item in interpretation["does_not_establish"]
    )

    state = handle(
        {
            "op": "si_state",
            "params": {"investigation_id": "draft", "project_id": "default"},
        },
        store=store,
    )["data"]["state"]
    assert experiment_id in state["experiments"]
    assert any(item["action_id"] == "create_experiment" for item in state["executions"])
    assert state["decisions"]


def test_si_execute_without_approval_is_refused_and_creates_nothing(tmp_path):
    store = _store(tmp_path)
    data = _ask_design(store)
    create = next(
        step
        for step in data["analysis"]["plan"]["steps"]
        if step["action_id"] == "create_experiment"
    )
    response = handle(
        {
            "op": "si_execute",
            "params": {
                "investigation_id": "draft",
                "step_id": create["step_id"],
                "model_id": "predator-prey",
                "approve": False,
            },
        },
        store=store,
    )
    assert response["ok"] is False
    assert response["error"]["code"] == "approval_required"
    assert store.list() == []


def test_read_only_step_runs_without_the_approval_flag(tmp_path):
    store = _store(tmp_path)
    data = _ask_design(store)
    read = next(
        step
        for step in data["analysis"]["plan"]["steps"]
        if step["action_id"] == "inspect_investigation"
    )
    response = handle(
        {
            "op": "si_execute",
            "params": {
                "investigation_id": "draft",
                "step_id": read["step_id"],
                "model_id": "predator-prey",
                "approve": False,
            },
        },
        store=store,
    )
    assert response["ok"], response
    assert response["data"]["execution"]["ok"] is True


def test_si_actions_expose_the_controlled_registry(tmp_path):
    store = _store(tmp_path)
    response = handle({"op": "si_actions", "params": {}}, store=store)
    assert response["ok"]
    by_id = {item["action_id"]: item for item in response["data"]["actions"]}
    assert by_id["inspect_project"]["read_only"] is True
    assert by_id["create_experiment"]["requires_approval"] is True
    assert by_id["create_model"]["supported"] is True
    assert by_id["simulate"]["supported"] is True
    assert response["data"]["provider"]["llm_configured"] is False
    # No action offers arbitrary execution.
    assert not any(
        token in action_id
        for action_id in by_id
        for token in ("shell", "subprocess", "python", "bash")
    )


def test_malformed_action_fails_closed_through_the_bridge(tmp_path):
    store = _store(tmp_path)
    _seed_plan(
        store,
        [
            SIPlanStep(
                step_id="step-1",
                purpose="simulate without a specification",
                action_id="simulate",
                approval="required",
            )
        ],
    )
    response = handle(
        {
            "op": "si_execute",
            "params": {
                "investigation_id": "draft",
                "step_id": "step-1",
                "approve": True,
            },
        },
        store=store,
    )
    assert response["ok"], response
    execution = response["data"]["execution"]
    # The step is recorded as a structured failure, not executed.
    assert execution["status"] == "failed"
    assert execution["ok"] is False
    assert execution["error_code"] == "bad_request"
    assert store.list() == []
    from drw.dataset_store import DatasetStore

    assert DatasetStore(tmp_path / "ws").list() == []


def test_synthetic_observations_are_never_used_as_evidence(tmp_path):
    workspace = tmp_path / "ws"
    store = ExperimentStore(workspace)
    datasets = DatasetStore(workspace)

    spec = ExperimentSpec(
        name="base",
        hypothesis="baseline",
        model_ref=ModelRef(model_id="predator-prey", version="1.0.0"),
        baseline={
            "alpha": 1.1,
            "beta": 0.4,
            "delta": 0.1,
            "gamma": 0.4,
            "prey0": 10.0,
            "predator0": 5.0,
        },
        factors=(FactorSpec(parameter="alpha", values=[1.1]),),
        outputs=("prey",),
        analyses=(AnalysisSpec(method="delta"),),
        execution=ExecutionSpec(isolation="in_process", timeout_s=30.0),
    )
    result = Runner().run(spec)
    store.save(result)
    peak = result.baseline.metrics["peak_prey"]

    synthetic = build_dataset(
        "simulated peaks",
        ObservationSet(
            variables=(
                Variable(
                    name="peak_prey", kind="float", role="measurement", unit="count"
                ),
            ),
            columns={"peak_prey": [peak, peak + 0.1]},
        ),
        Provenance(
            source_kind="synthetic",
            imported_at="2026-01-01T00:00:00+00:00",
            dataset_version="1.0.0",
        ),
    )
    datasets.save(synthetic)
    mapping = ObservationMapping(
        dataset=synthetic.ref(),
        model_ref=ModelRef(model_id="predator-prey"),
        pairs=(MappingPair(observation="peak_prey", output="peak_prey"),),
    )
    _seed_plan(
        store,
        [
            SIPlanStep(
                step_id="step-1",
                purpose="evaluate",
                action_id="evaluate",
                inputs={
                    "experiment_id": result.experiment_id,
                    "mapping": mapping.model_dump(mode="json"),
                },
                approval="required",
            )
        ],
    )
    response = handle(
        {
            "op": "si_execute",
            "params": {
                "investigation_id": "draft",
                "step_id": "step-1",
                "model_id": "predator-prey",
                "approve": True,
            },
        },
        store=store,
    )
    assert response["ok"], response
    execution = response["data"]["execution"]
    assert execution["status"] == "failed"
    assert execution["error_code"] == "synthetic_not_empirical"


def test_generated_model_specification_requires_approval(tmp_path):
    store = _store(tmp_path)
    specification = {
        "model_id": "projectile",
        "version": "1.0.0",
        "description": "vertical projectile",
        "domain": "physics",
        "kind": "ode",
        "parameters": [
            {"name": "g", "unit": "m/s^2", "nominal": 9.81, "lower": 1.0, "upper": 20.0}
        ],
        "variables": [{"name": "v", "kind": "state", "unit": "m/s"}],
        "relationships": [{"name": "dvdt", "expression": "-g", "depends_on": ["g"]}],
        "assumptions": ["constant gravity"],
        "initial_conditions": {"v": 0.0},
        "provenance": {"created_at": "2026-01-01T00:00:00+00:00"},
    }
    _seed_plan(
        store,
        [
            SIPlanStep(
                step_id="step-1",
                purpose="store the specification",
                action_id="create_model_spec",
                inputs={"specification": specification},
                approval="required",
            )
        ],
    )
    refused = handle(
        {
            "op": "si_execute",
            "params": {
                "investigation_id": "draft",
                "step_id": "step-1",
                "approve": False,
            },
        },
        store=store,
    )
    assert refused["ok"] is False
    assert refused["error"]["code"] == "approval_required"
    assert ModelSpecStore(store.root).list() == []

    approved = handle(
        {
            "op": "si_execute",
            "params": {
                "investigation_id": "draft",
                "step_id": "step-1",
                "approve": True,
            },
        },
        store=store,
    )
    assert approved["ok"], approved
    execution = approved["data"]["execution"]
    assert execution["status"] == "executed"
    spec_id = execution["artifacts"]["spec_id"]
    stored = ModelSpecStore(store.root)
    assert stored.exists(spec_id)
    assert stored.load(spec_id).model_id == "projectile"


def test_bridge_refuses_arbitrary_operations(tmp_path):
    store = _store(tmp_path)
    response = handle(
        {"op": "run_python", "params": {"code": "import os; os.system('echo hi')"}},
        store=store,
    )
    assert response["ok"] is False
    assert response["error"]["code"] == "unknown_op"
