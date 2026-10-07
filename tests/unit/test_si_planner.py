"""Unit tests for SI plan generation and untrusted-provider handling."""

from __future__ import annotations

import pytest

from drw.si.context import build_action_context
from drw.si.planner import plan_analysis
from drw.si.provider import SIProviderError
from drw.store import ExperimentStore

pytestmark = pytest.mark.unit


def _ctx(tmp_path, model_id="predator-prey"):
    store = ExperimentStore(tmp_path / "ws")
    return build_action_context(
        store, investigation_id="draft", project_id="default", model_id=model_id
    )


def test_rule_based_design_question_proposes_a_real_experiment(tmp_path):
    ctx = _ctx(tmp_path)
    analysis = plan_analysis(
        "Design an experiment to see how alpha changes the prey peak.", ctx
    )
    assert analysis.used_ai is False
    assert analysis.provider == "rule-based"
    action_ids = [step.action_id for step in analysis.plan.steps]
    assert action_ids[0] == "inspect_investigation"
    assert "create_experiment" in action_ids
    create = next(
        step for step in analysis.plan.steps if step.action_id == "create_experiment"
    )
    assert create.approval == "required"
    assert "spec" in create.inputs


def test_read_only_steps_need_no_approval(tmp_path):
    ctx = _ctx(tmp_path)
    analysis = plan_analysis("What is the current state of this investigation?", ctx)
    for step in analysis.plan.steps:
        if step.action_id.startswith("inspect_") or step.action_id == "list_datasets":
            assert step.approval == "not_required"


def test_missing_dataset_is_reported(tmp_path):
    ctx = _ctx(tmp_path)
    analysis = plan_analysis("Evaluate the model against my observations.", ctx)
    assert any("dataset" in item.lower() for item in analysis.missing_information)


def test_calibration_request_reports_what_is_required(tmp_path):
    from drw.dataset_store import DatasetStore
    from drw.observations import build_dataset
    from drw.schema.observation import ObservationSet, Provenance, Variable

    store = ExperimentStore(tmp_path / "ws")
    DatasetStore(store.root).save(
        build_dataset(
            "real peaks",
            ObservationSet(
                variables=(
                    Variable(
                        name="peak_prey", kind="float", role="measurement", unit="count"
                    ),
                ),
                columns={"peak_prey": [1.0, 2.0, 3.0]},
            ),
            Provenance(
                source_kind="file",
                imported_at="2026-01-01T00:00:00+00:00",
                dataset_version="1.0.0",
            ),
        )
    )
    ctx = build_action_context(
        store, investigation_id="draft", project_id="default", model_id="predator-prey"
    )
    analysis = plan_analysis("Please calibrate the model parameters.", ctx)
    assert analysis.unsupported_requests
    assert any("calibration" in item.lower() for item in analysis.unsupported_requests)


def test_identifiability_without_experiment_reports_missing_information(tmp_path):
    ctx = _ctx(tmp_path)
    analysis = plan_analysis(
        "Which parameters can I distinguish from one another?", ctx
    )
    assert any("experiment" in item.lower() for item in analysis.missing_information)


class _FakeProvider:
    name = "fake"

    def __init__(self, payload):
        self.payload = payload
        self.calls = 0

    def respond(self, *, question, context):
        self.calls += 1
        if isinstance(self.payload, Exception):
            raise self.payload
        return self.payload


def test_provider_with_supported_step_is_used(tmp_path):
    provider = _FakeProvider(
        {
            "understanding": "You want to inspect the registered models.",
            "steps": [
                {
                    "action_id": "list_models",
                    "inputs": {},
                    "purpose": "List the models.",
                },
            ],
        }
    )
    analysis = plan_analysis("What models exist?", _ctx(tmp_path), provider=provider)
    assert provider.calls == 1
    assert analysis.used_ai is True
    assert analysis.understanding == "You want to inspect the registered models."
    assert [step.action_id for step in analysis.plan.steps] == ["list_models"]


def test_provider_unknown_action_is_ignored_with_a_caveat(tmp_path):
    provider = _FakeProvider(
        {"steps": [{"action_id": "shell_exec", "inputs": {"cmd": "rm -rf /"}}]}
    )
    analysis = plan_analysis("What models exist?", _ctx(tmp_path), provider=provider)
    assert analysis.used_ai is False
    assert any(
        step.action_id == "inspect_investigation" for step in analysis.plan.steps
    )
    assert any("unknown action" in caveat.lower() for caveat in analysis.caveats)


def test_provider_step_with_invalid_inputs_is_ignored(tmp_path):
    # ``simulate`` is supported, but a step that omits the required 'simulation'
    # input must not survive validation.
    provider = _FakeProvider({"steps": [{"action_id": "simulate", "inputs": {}}]})
    analysis = plan_analysis(
        "Simulate the trajectory.", _ctx(tmp_path), provider=provider
    )
    assert analysis.used_ai is False
    assert any("ignored ai step" in caveat.lower() for caveat in analysis.caveats)


def test_provider_invalid_step_inputs_are_dropped(tmp_path):
    provider = _FakeProvider(
        {
            "steps": [
                {"action_id": "create_experiment", "inputs": {"spec": {"bad": True}}}
            ]
        }
    )
    analysis = plan_analysis("Design an experiment.", _ctx(tmp_path), provider=provider)
    assert analysis.used_ai is False
    assert any("ignored ai step" in caveat.lower() for caveat in analysis.caveats)


def test_malformed_provider_output_falls_back(tmp_path):
    provider = _FakeProvider(["not", "an", "object"])
    analysis = plan_analysis("What models exist?", _ctx(tmp_path), provider=provider)
    assert analysis.used_ai is False
    assert analysis.plan is not None
    assert any("no usable plan" in caveat.lower() for caveat in analysis.caveats)


def test_provider_failure_falls_back(tmp_path):
    provider = _FakeProvider(SIProviderError("provider down"))
    analysis = plan_analysis("What models exist?", _ctx(tmp_path), provider=provider)
    assert analysis.used_ai is False
    assert any("unavailable" in caveat.lower() for caveat in analysis.caveats)


def test_provider_only_proposes_registered_supported_actions(tmp_path):
    """A provider cannot smuggle in an action that is not read-only-safe or supported."""
    provider = _FakeProvider(
        {
            "steps": [
                {"action_id": "create_model", "inputs": {}},
                {"action_id": "list_models", "inputs": {}},
            ]
        }
    )
    analysis = plan_analysis("Inspect.", _ctx(tmp_path), provider=provider)
    assert [step.action_id for step in analysis.plan.steps] == ["list_models"]
    assert analysis.used_ai is True
