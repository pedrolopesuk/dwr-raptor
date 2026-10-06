"""Integration test: a local identifiability study over a real stored experiment."""

from __future__ import annotations

import hashlib
from dataclasses import replace

import pytest

from drw.api import handle
from drw.cli import main as cli_main
from drw.execution.runner import Runner
from drw.identifiability import (
    IdentifiabilityError,
    default_factors,
    identifiability_for_experiment,
)
from drw.models.registry import build_model
from drw.schema.experiment import AnalysisSpec, ExperimentSpec, FactorSpec, SamplingSpec
from drw.schema.model import ModelRef
from drw.schema.result import RunStatus
from drw.store import ExperimentStore

pytestmark = pytest.mark.integration

FACTORS = ["beta", "predator0"]
OUTPUTS = ["prey"]
EVALUATIONS = 2 * len(FACTORS) + 1  # 5


@pytest.fixture
def stored(tmp_path):
    store = ExperimentStore(tmp_path / "ws")
    spec = ExperimentSpec(
        name="identifiability study",
        hypothesis="are beta and predator0 distinguishable from the prey output?",
        model_ref=ModelRef(model_id="predator-prey", version="1.0.0"),
        baseline={
            "alpha": 1.1, "beta": 0.4, "delta": 0.1, "gamma": 0.4,
            "prey0": 10.0, "predator0": 5.0,
        },
        factors=(FactorSpec(parameter="alpha", values=[1.1]),),
        outputs=("prey",),
        sampling=SamplingSpec(method="grid"),
        analyses=(AnalysisSpec(method="delta"),),
    )
    result = Runner().run(spec)
    store.save(result)
    return store, result.experiment_id


def _snapshot(directory):
    return {
        path.relative_to(directory).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(directory.rglob("*"))
        if path.is_file()
    }


def test_study_runs_is_deterministic_and_read_only(stored):
    store, experiment_id = stored
    directory = store.experiment_dir(experiment_id)
    before = _snapshot(directory)

    first = identifiability_for_experiment(
        experiment_id, store, factors=FACTORS, outputs=OUTPUTS
    )
    second = identifiability_for_experiment(
        experiment_id, store, factors=FACTORS, outputs=OUTPUTS
    )

    assert first.experiment_id == experiment_id
    assert first.dimensions == len(FACTORS)
    assert first.evaluations_requested == EVALUATIONS
    assert first.evaluations_completed == EVALUATIONS
    assert first.verdict == "rank-deficient"
    assert first.model_dump() == second.model_dump()  # deterministic

    # The study does not touch the stored experiment (read-only, on-demand).
    assert _snapshot(directory) == before


def test_default_factors_are_used_when_none_are_given(stored):
    store, experiment_id = stored
    report = identifiability_for_experiment(experiment_id, store, outputs=["peak_prey"])
    assert report.factors == default_factors(build_model("predator-prey").describe())


def test_cli_and_bridge_agree_with_the_core(stored, capsys):
    store, experiment_id = stored
    core = identifiability_for_experiment(
        experiment_id, store, factors=FACTORS, outputs=OUTPUTS
    )

    bridge = handle(
        {
            "op": "identifiability",
            "params": {"experiment_id": experiment_id, "factors": FACTORS, "outputs": OUTPUTS},
        },
        store=store,
    )
    assert bridge["ok"] is True
    report = bridge["data"]["report"]
    assert report["verdict"] == core.verdict
    assert report["numerical_rank"] == core.numerical_rank
    assert report["singular_values"] == pytest.approx(core.singular_values)

    # The CLI prints the same scientific result (verdict + rank) and exits 0 for
    # a conclusive study.
    code = cli_main(
        [
            "identifiability", experiment_id, "--factors", "beta,predator0",
            "--outputs", "prey", "--workspace", str(store.root),
        ]
    )
    out = capsys.readouterr().out
    assert code == 0
    assert "verdict: RANK-DEFICIENT" in out
    assert "numerical rank: 1/2" in out


def test_invalid_factor_is_rejected(stored):
    store, experiment_id = stored
    with pytest.raises(IdentifiabilityError, match="unknown factor"):
        identifiability_for_experiment(experiment_id, store, factors=["nope"])
    response = handle(
        {"op": "identifiability", "params": {"experiment_id": experiment_id, "factors": ["nope"]}},
        store=store,
    )
    assert response["ok"] is False and response["error"]["code"] == "bad_request"


def test_over_cap_request_is_rejected_before_execution(stored):
    store, experiment_id = stored
    with pytest.raises(IdentifiabilityError, match="evaluations"):
        identifiability_for_experiment(
            experiment_id, store, factors=FACTORS, max_evaluations=EVALUATIONS - 1
        )


class _FlakyRunner:
    """Wraps a Runner and forces one evaluation to fail."""

    def __init__(self, inner: Runner, fail_index: int) -> None:
        self.inner = inner
        self.fail_index = fail_index
        self.calls = 0

    def run(self, spec, **kwargs):
        index = self.calls
        self.calls += 1
        result = self.inner.run(spec, **kwargs)
        if index != self.fail_index:
            return result
        record = result.runs[0].model_copy(
            update={"status": RunStatus.FAILED, "result": None, "error": "simulated failure"}
        )
        return replace(result, runs=[record])


def test_failed_evaluation_becomes_inconclusive(stored):
    store, experiment_id = stored
    report = identifiability_for_experiment(
        experiment_id, store, factors=FACTORS, outputs=OUTPUTS,
        runner=_FlakyRunner(Runner(), fail_index=2),
    )
    assert report.inconclusive is True
    assert report.verdict == "inconclusive"
    assert report.numerical_rank is None
    assert any("run_failed" in reason for reason in report.reasons)


def test_progress_journal_reports_measured_completion(stored):
    store, experiment_id = stored
    job_id = "job-" + "e" * 16

    response = handle(
        {
            "op": "identifiability",
            "params": {
                "experiment_id": experiment_id, "factors": FACTORS, "outputs": OUTPUTS,
                "job_id": job_id,
            },
        },
        store=store,
    )
    assert response["ok"] is True, response

    status = handle({"op": "job_status", "params": {"job_id": job_id}}, store=store)["data"]
    assert status["phase"] == "finished"
    assert status["terminal"] is True
    assert status["status"] == "succeeded"
    assert status["total_runs"] == EVALUATIONS
    assert status["completed_runs"] == EVALUATIONS
    events = status["events"]
    assert events[0]["event"] == "started"
    assert events[-1]["event"] == "finished"
    assert sum(1 for event in events if event["event"] == "run_completed") == EVALUATIONS


def test_unknown_experiment_is_not_found(tmp_path):
    store = ExperimentStore(tmp_path / "ws")
    response = handle(
        {"op": "identifiability", "params": {"experiment_id": "exp-000000000000"}}, store=store
    )
    assert response["ok"] is False and response["error"]["code"] == "not_found"


def test_non_list_factors_are_a_bad_request(stored):
    store, experiment_id = stored
    response = handle(
        {"op": "identifiability", "params": {"experiment_id": experiment_id, "factors": "beta"}},
        store=store,
    )
    assert response["ok"] is False and response["error"]["code"] == "bad_request"
