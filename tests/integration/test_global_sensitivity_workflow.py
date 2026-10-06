"""Integration test: a global-sensitivity study over a real DRW model."""

from __future__ import annotations

import hashlib

import pytest

from drw.execution.runner import Runner
from drw.global_sensitivity import GlobalSensitivityError, sobol_indices_for_experiment
from drw.schema.experiment import AnalysisSpec, ExperimentSpec, FactorSpec, SamplingSpec
from drw.schema.model import ModelRef
from drw.store import ExperimentStore

pytestmark = pytest.mark.integration

N = 8
FACTORS = ["alpha", "beta"]
EVALUATIONS = N * (len(FACTORS) + 2)  # 32


@pytest.fixture
def stored(tmp_path):
    store = ExperimentStore(tmp_path / "ws")
    spec = ExperimentSpec(
        name="sobol study",
        hypothesis="which parameters drive the prey peak?",
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


def _snapshot(root):
    return {
        path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def test_sobol_study_runs_and_is_read_only(stored):
    store, experiment_id = stored
    directory = store.experiment_dir(experiment_id)
    before = _snapshot(directory)

    report = sobol_indices_for_experiment(
        experiment_id, store, output="peak_prey", factors=FACTORS,
        sample_count=N, seed=3, bootstrap_resamples=20,
    )

    assert report.output == "peak_prey"
    assert report.factors == FACTORS
    assert report.evaluations_requested == EVALUATIONS
    assert report.evaluations_completed == EVALUATIONS
    assert report.inconclusive is False
    assert report.variance is not None and report.variance > 0
    rows = {row.name: row for row in report.results}
    assert set(rows) == set(FACTORS)
    for row in report.results:
        assert row.s1 is not None and row.st is not None
        assert -1.0 <= row.s1 <= 2.0 and -1.0 <= row.st <= 2.0

    # The study does not touch the stored experiment (read-only, on-demand).
    assert store.list()
    assert len(store.load(experiment_id)["results"]["runs"]) == 2
    assert _snapshot(directory) == before


def test_invalid_factor_is_rejected(stored):
    store, experiment_id = stored
    with pytest.raises(GlobalSensitivityError, match="unknown factor"):
        sobol_indices_for_experiment(
            experiment_id, store, output="peak_prey", factors=["nope"],
            sample_count=N, seed=1,
        )
