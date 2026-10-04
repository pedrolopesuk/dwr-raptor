"""Integration tests: projects, capabilities, progress jobs and the planner API."""

from __future__ import annotations

import json

import pytest

from drw.api import handle
from drw.store import DEFAULT_PROJECT_ID, ExperimentStore

pytestmark = pytest.mark.integration


@pytest.fixture
def store(tmp_path) -> ExperimentStore:
    return ExperimentStore(tmp_path / "workspace")


def _sample(store: ExperimentStore) -> dict:
    response = handle({"op": "sample_experiment", "params": {}}, store=store)
    assert response["ok"]
    return response["data"]["spec"]


def test_default_project_exists_and_is_listed_first(store):
    projects = handle({"op": "list_projects", "params": {}}, store=store)["data"]["projects"]
    assert projects[0]["project_id"] == DEFAULT_PROJECT_ID


def test_create_and_list_projects(store):
    created = handle(
        {"op": "create_project", "params": {"name": "Climate sweep", "model_id": "lorenz"}},
        store=store,
    )["data"]["project"]
    assert created["project_id"].startswith("proj-")
    ids = [p["project_id"] for p in handle({"op": "list_projects", "params": {}}, store=store)["data"]["projects"]]
    assert created["project_id"] in ids


def test_run_associates_experiment_with_project_and_journals_progress(store):
    spec = _sample(store)
    project = handle(
        {"op": "create_project", "params": {"name": "Prey study"}}, store=store
    )["data"]["project"]
    job_id = "job-" + "0" * 16

    response = handle(
        {
            "op": "run",
            "params": {"spec": spec, "project_id": project["project_id"], "job_id": job_id},
        },
        store=store,
    )
    assert response["ok"]
    data = response["data"]
    assert data["project_id"] == project["project_id"]
    assert data["job_id"] == job_id

    listing = handle(
        {"op": "list_experiments", "params": {"project_id": project["project_id"]}}, store=store
    )["data"]["experiments"]
    assert [e["experiment_id"] for e in listing] == [data["experiment_id"]]
    # The default project does not contain it.
    default_listing = handle(
        {"op": "list_experiments", "params": {"project_id": DEFAULT_PROJECT_ID}}, store=store
    )["data"]["experiments"]
    assert default_listing == []

    status = handle({"op": "job_status", "params": {"job_id": job_id}}, store=store)["data"]
    assert status["phase"] == "finished"
    assert status["terminal"] is True
    assert status["total_runs"] == 2
    assert status["completed_runs"] == 2
    assert status["status"] == "succeeded"
    assert [e["event"] for e in status["events"]][:2] == ["started", "run_completed"]


def test_invalid_spec_produces_no_job_events(store):
    spec = _sample(store)
    spec["baseline"]["alpha"] = 999  # out of bounds
    job_id = "job-" + "1" * 16
    response = handle(
        {"op": "run", "params": {"spec": spec, "job_id": job_id}}, store=store
    )
    assert response["ok"] is False
    assert response["error"]["code"] == "validation_error"
    status = handle({"op": "job_status", "params": {"job_id": job_id}}, store=store)["data"]
    assert status["phase"] == "pending"
    assert status["events"] == []


def test_capabilities_op(store):
    caps = handle(
        {"op": "capabilities", "params": {"model_id": "predator-prey"}}, store=store
    )["data"]["capabilities"]
    assert any(p["name"] == "alpha" for p in caps["factorable_parameters"])
    assert caps["sensitivity"] == "oat"


def test_plan_experiment_proposes_without_executing(store):
    response = handle(
        {
            "op": "plan_experiment",
            "params": {
                "model_id": "predator-prey",
                "question": "How does the prey peak change if alpha increases by 10%?",
            },
        },
        store=store,
    )
    assert response["ok"]
    plan = response["data"]
    assert plan["spec"] is not None
    assert plan["validation_ok"] is True
    assert plan["used_ai"] is False
    assert plan["provider"] == "rule-based"
    assert plan["assumptions"]
    # Planning must never create an experiment.
    assert handle({"op": "list_experiments", "params": {}}, store=store)["data"]["experiments"] == []


def test_plan_experiment_asks_when_the_question_is_too_vague(store):
    response = handle(
        {"op": "plan_experiment", "params": {"model_id": "predator-prey", "question": "vary it"}},
        store=store,
    )
    assert response["ok"]
    plan = response["data"]
    assert plan["spec"] is None
    assert plan["questions"]
    assert handle({"op": "list_experiments", "params": {}}, store=store)["data"]["experiments"] == []


def test_planner_status_is_safe(store):
    status = handle({"op": "planner_status", "params": {}}, store=store)["data"]
    assert set(status) >= {"llm_configured", "provider", "note"}
    assert "key" not in json.dumps(status).lower()


def test_legacy_experiment_without_project_id_is_read_as_default(store):
    experiment_id = "exp-" + "a" * 12
    directory = store.experiment_dir(experiment_id)
    directory.mkdir(parents=True)
    (directory / "spec.json").write_text("{}", encoding="utf-8")
    (directory / "results.json").write_text("{}", encoding="utf-8")
    # Legacy meta predating projects:
    (directory / "meta.json").write_text(
        json.dumps({"experiment_id": experiment_id, "name": "legacy"}), encoding="utf-8"
    )

    listing = handle({"op": "list_experiments", "params": {}}, store=store)["data"]["experiments"]
    legacy = next(e for e in listing if e["experiment_id"] == experiment_id)
    assert legacy["project_id"] == DEFAULT_PROJECT_ID

    loaded = handle(
        {"op": "get_experiment", "params": {"experiment_id": experiment_id}}, store=store
    )["data"]["experiment"]
    assert loaded["meta"]["project_id"] == DEFAULT_PROJECT_ID
