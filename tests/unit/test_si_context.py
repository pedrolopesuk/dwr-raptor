"""Unit tests for the SI context builder and synthetic/real separation."""

from __future__ import annotations

import pytest

from drw.observations import build_dataset
from drw.schema.observation import ObservationSet, Provenance, Variable
from drw.si.context import build_action_context, build_context
from drw.si.store import new_state
from drw.store import ExperimentStore

pytestmark = pytest.mark.unit


def _dataset(name: str, source_kind: str, values: list[float]):
    provenance = Provenance(
        source_kind=source_kind,
        imported_at="2026-01-01T00:00:00+00:00",
        dataset_version="1.0.0",
    )
    return build_dataset(
        name,
        ObservationSet(
            variables=(
                Variable(
                    name="peak_prey", kind="float", role="measurement", unit="count"
                ),
            ),
            columns={"peak_prey": values},
        ),
        provenance,
    )


@pytest.fixture
def store(tmp_path) -> ExperimentStore:
    return ExperimentStore(tmp_path / "ws")


def test_context_is_structured_and_selective(store):
    ctx = build_action_context(
        store,
        investigation_id="draft",
        project_id="default",
        model_id="predator-prey",
        state=new_state("draft", "default"),
    )
    context = build_context(ctx, question="what happens if alpha changes?")
    assert context["question"] == "what happens if alpha changes?"
    assert context["model"]["model_id"] == "predator-prey"
    assert context["model"]["model_hash"]
    assert "parameters" in context["model"]
    assert any(ref["action_id"] == "create_experiment" for ref in context["actions"])
    # The context carries summaries, never raw result payloads.
    assert "runs" not in context
    assert "comparisons" not in context


def test_context_separates_synthetic_from_real_datasets(store):
    from drw.dataset_store import DatasetStore

    datasets = DatasetStore(store.root)
    datasets.save(_dataset("real", "file", [1.0, 2.0, 3.0]))
    datasets.save(_dataset("simulated", "synthetic", [1.0, 1.0, 1.0]))

    ctx = build_action_context(store, investigation_id="draft", project_id="default")
    context = build_context(ctx, question="q")
    by_name = {item["name"]: item for item in context["datasets"]}
    assert by_name["real"]["synthetic"] is False
    assert by_name["real"]["source_kind"] == "file"
    assert by_name["simulated"]["synthetic"] is True
    assert by_name["simulated"]["source_kind"] == "synthetic"


def test_context_summary_counts_synthetic_separately(store):
    from drw.dataset_store import DatasetStore

    DatasetStore(store.root).save(_dataset("simulated", "synthetic", [1.0]))
    ctx = build_action_context(store, investigation_id="draft", project_id="default")
    context = build_context(ctx, question="q")
    from drw.si.context import context_summary_lines

    lines = " ".join(context_summary_lines(context))
    assert "0 empirical dataset(s), 1 synthetic dataset(s)" in lines
