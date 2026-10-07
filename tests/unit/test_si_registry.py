"""Unit tests for the SI action registry: stable ids, access classes, safety."""

from __future__ import annotations

import pytest

from drw.schema.si import SIExecutionResult
from drw.si.actions import SIActionError, default_registry
from drw.si.interpreter import interpret

pytestmark = pytest.mark.unit

_MUTATING = {
    "create_experiment",
    "evaluate",
    "calibrate",
    "validate",
    "sensitivity",
    "identifiability",
    "create_model_spec",
    "create_model",
    "simulate",
}


@pytest.fixture
def registry():
    return default_registry()


def test_registry_exposes_expected_actions(registry):
    ids = {ref.action_id for ref in registry.refs()}
    assert {
        "inspect_project",
        "inspect_investigation",
        "list_models",
        "inspect_model",
        "list_datasets",
        "inspect_experiment",
        "inspect_evidence",
    } <= ids
    assert ids >= _MUTATING


def test_action_ids_are_unique(registry):
    ids = [ref.action_id for ref in registry.refs()]
    assert len(ids) == len(set(ids))


def test_requires_approval_is_exactly_not_read_only(registry):
    for ref in registry.refs():
        assert ref.requires_approval == (not ref.read_only)


def test_mutating_actions_require_approval(registry):
    mutating = {ref.action_id for ref in registry.refs() if not ref.read_only}
    assert mutating == _MUTATING


def test_model_generation_actions_are_now_supported(registry):
    unsupported = {ref.action_id for ref in registry.refs() if not ref.supported}
    assert unsupported == set()
    for action_id in ("create_model", "simulate"):
        assert registry.get(action_id).supported is True
        assert registry.get(action_id).requires_approval is True


def test_unknown_action_raises_a_controlled_error(registry):
    with pytest.raises(SIActionError) as exc:
        registry.get("delete_everything")
    assert exc.value.code == "unknown_action"


def test_no_action_grants_arbitrary_execution(registry):
    forbidden = ("shell", "exec", "subprocess", "python", "bash")
    for ref in registry.refs():
        assert not any(token in ref.action_id for token in forbidden)


def test_preview_reports_access_and_effects(registry, tmp_path):
    from drw.si.context import build_action_context
    from drw.store import ExperimentStore

    store = ExperimentStore(tmp_path / "ws")
    ctx = build_action_context(store, investigation_id="draft", project_id="default")
    preview = registry.preview("create_experiment", {"spec": {"not": "valid"}}, ctx)
    assert preview.requires_approval is True
    assert preview.supported is True
    assert preview.effects == "creates_experiment"
    assert any(d.level == "error" for d in preview.input_diagnostics)

    read = registry.preview("list_models", {}, ctx)
    assert read.read_only is True
    assert read.requires_approval is False
    assert read.input_diagnostics == ()


def test_interpretation_separates_establishes_from_does_not():
    result = SIExecutionResult(
        step_id="step-1",
        action_id="validate",
        status="executed",
        ok=True,
    )
    interpretation = interpret(
        result, interpretation_id="i1", at="2026-01-01T00:00:00+00:00"
    )
    assert interpretation.establishes
    assert any(
        "true" in item or "causality" in item.lower()
        for item in interpretation.does_not_establish
    )


def test_failed_execution_interpretation_states_nothing_was_produced():
    result = SIExecutionResult(
        step_id="step-1",
        action_id="create_experiment",
        status="failed",
        ok=False,
        error_code="validation_error",
        error_message="bad spec",
    )
    interpretation = interpret(
        result, interpretation_id="i1", at="2026-01-01T00:00:00+00:00"
    )
    assert interpretation.establishes == []
    assert "failed" in interpretation.text
