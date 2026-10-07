"""Unit tests for the durable SI investigation store."""

from __future__ import annotations

import pytest

from drw.schema.si import SIPlan, SIPlanStep
from drw.si.store import (
    DRAFT_INVESTIGATION_ID,
    InvalidInvestigationId,
    SIStore,
    new_state,
)

pytestmark = pytest.mark.unit


@pytest.fixture
def store(tmp_path) -> SIStore:
    return SIStore(tmp_path / "ws")


def test_load_missing_returns_none(store):
    assert store.load("draft") is None
    assert store.exists("draft") is False


def test_save_load_round_trip(store):
    state = new_state("draft", "default")
    state.objective = "understand the prey peak"
    state.experiments.append("exp-000000000001")
    plan = SIPlan(
        plan_id="plan-x",
        objective=state.objective,
        steps=[SIPlanStep(step_id="step-1", purpose="p", action_id="inspect_project")],
    )
    state.plans.append(plan)
    state.current_plan_id = plan.plan_id
    store.save(state)

    assert store.exists("draft") is True
    reloaded = store.load("draft")
    assert reloaded is not None
    assert reloaded.objective == "understand the prey peak"
    assert reloaded.experiments == ["exp-000000000001"]
    assert reloaded.current_plan().steps[0].action_id == "inspect_project"


def test_load_or_create_is_idempotent(store):
    first = store.load_or_create("draft", "default")
    first.objective = "keep me"
    store.save(first)
    second = store.load_or_create("draft", "default")
    assert second.objective == "keep me"
    assert second.created_at == first.created_at


def test_save_touches_updated_at(store):
    state = new_state("draft", "default", at="2026-01-01T00:00:00+00:00")
    store.save(state)
    assert store.load("draft").updated_at != "2026-01-01T00:00:00+00:00"


def test_draft_sentinel_is_allowed(store):
    assert DRAFT_INVESTIGATION_ID == "draft"
    store.save(new_state("draft"))
    assert store.exists("draft")


@pytest.mark.parametrize(
    "bad_id",
    [
        "",
        "..",
        "../escape",
        "a/b",
        "exp-zzzz",
        "inv-123",
        "draft.json",
        "exp-00000000000g",
    ],
)
def test_invalid_ids_are_rejected(store, bad_id):
    with pytest.raises(InvalidInvestigationId):
        store.path(bad_id)


def test_list_returns_all_states(store):
    store.save(new_state("draft", "default"))
    store.save(new_state("exp-000000000001", "default"))
    ids = {state.investigation_id for state in store.list()}
    assert ids == {"draft", "exp-000000000001"}
