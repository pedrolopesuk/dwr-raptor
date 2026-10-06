"""Integration tests: the uncertainty analysis over a real sampled experiment."""

from __future__ import annotations

import hashlib
import json
import math

import pytest

from drw.execution.evidence import build_evidence_package, verify_evidence
from drw.execution.runner import Runner
from drw.schema.experiment import (
    AnalysisSpec,
    ExperimentSpec,
    FactorSpec,
    SamplingSpec,
)
from drw.schema.model import ModelRef
from drw.schema.serialization import to_plain
from drw.store import ExperimentStore
from drw.uncertainty import uncertainty_for_experiment

pytestmark = pytest.mark.integration

N_SAMPLES = 6
SEED = 5


def _spec(*, with_uncertainty: bool) -> ExperimentSpec:
    analyses = [AnalysisSpec(method="delta")]
    if with_uncertainty:
        analyses.append(AnalysisSpec(method="uncertainty"))
    return ExperimentSpec(
        name="uncertainty demo",
        hypothesis="how does the prey peak vary across the sampled alpha/beta ranges?",
        model_ref=ModelRef(model_id="predator-prey", version="1.0.0"),
        baseline={
            "alpha": 1.1,
            "beta": 0.4,
            "delta": 0.1,
            "gamma": 0.4,
            "prey0": 10.0,
            "predator0": 5.0,
        },
        factors=(
            FactorSpec(parameter="alpha", lower=0.5, upper=2.0),
            FactorSpec(parameter="beta", lower=0.1, upper=1.0),
        ),
        outputs=(),
        sampling=SamplingSpec(method="latin_hypercube", n_samples=N_SAMPLES, seed=SEED),
        analyses=tuple(analyses),
    )


@pytest.fixture(scope="module")
def with_uncertainty():
    return Runner().run(_spec(with_uncertainty=True))


@pytest.fixture(scope="module")
def without_uncertainty():
    return Runner().run(_spec(with_uncertainty=False))


def test_uncertainty_summary_is_produced_from_the_existing_design(with_uncertainty):
    summary = with_uncertainty.uncertainty
    assert summary is not None
    assert summary.sampling_method == "latin_hypercube"
    assert summary.seed == SEED
    assert summary.requested_variants == N_SAMPLES  # no additional executions
    assert summary.valid_output_samples == N_SAMPLES and summary.excluded_output_samples == 0
    assert summary.quantiles == [5.0, 50.0, 95.0] and summary.quantile_method == "linear"
    peak = {output.output: output for output in summary.outputs}["peak_prey"]
    assert peak.valid_samples == N_SAMPLES and peak.sufficient is True
    for value in (peak.mean, peak.std, peak.minimum, peak.maximum, peak.p05, peak.p50, peak.p95):
        assert value is not None
    assert peak.minimum <= peak.p05 <= peak.p50 <= peak.p95 <= peak.maximum


def test_uncertainty_is_deterministic_for_a_fixed_seed(with_uncertainty):
    repeat = Runner().run(_spec(with_uncertainty=True))
    assert to_plain(repeat.uncertainty) == to_plain(with_uncertainty.uncertainty)


def test_delta_behavior_is_unchanged_by_the_uncertainty_analysis(with_uncertainty, without_uncertainty):
    # Same sampling design, so the runs - and therefore the comparisons - are identical
    # whether or not the uncertainty analysis is declared.
    assert len(with_uncertainty.comparisons) == len(without_uncertainty.comparisons) > 0
    assert without_uncertainty.uncertainty is None
    for a, b in zip(with_uncertainty.comparisons, without_uncertainty.comparisons, strict=True):
        assert a.output == b.output
        assert a.alignment == b.alignment
        assert a.delta == b.delta
        assert _metrics_equal(a.metrics, b.metrics)


def _metrics_equal(left: dict, right: dict) -> bool:
    if left.keys() != right.keys():
        return False
    for key, value in left.items():
        other = right[key]
        if isinstance(value, float) and isinstance(other, float) and math.isnan(value) and math.isnan(other):
            continue
        if value != other:
            return False
    return True


def test_evidence_package_carries_an_additive_uncertainty_artifact(with_uncertainty, tmp_path):
    manifest_path = build_evidence_package(with_uncertainty, tmp_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    kinds = {entry["kind"] for entry in manifest["files"]}
    assert "uncertainty" in kinds
    # The additive file is hashed like every other artifact and verifies.
    entry = next(item for item in manifest["files"] if item["path"] == "uncertainty.json")
    data = (tmp_path / "uncertainty.json").read_bytes()
    assert hashlib.sha256(data).hexdigest() == entry["sha256"]

    report = verify_evidence(manifest_path)
    assert report.ok is True
    assert {artifact.path for artifact in report.artifacts} >= {
        "experiment-spec.json",
        "model-schema.json",
        "results.json",
        "report.md",
        "uncertainty.json",
    }
    assert (tmp_path / "report.md").read_text(encoding="utf-8").count("## Uncertainty") == 1


def test_experiments_without_the_analysis_are_unchanged(without_uncertainty, tmp_path):
    manifest_path = build_evidence_package(without_uncertainty, tmp_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert {entry["kind"] for entry in manifest["files"]} == {
        "experiment_spec",
        "model_schema",
        "results",
        "report",
    }
    assert not (tmp_path / "uncertainty.json").exists()
    assert "## Uncertainty" not in (tmp_path / "report.md").read_text(encoding="utf-8")


def test_uncertainty_for_a_stored_experiment_is_read_only(with_uncertainty, tmp_path):
    store = ExperimentStore(tmp_path / "ws")
    store.save(with_uncertainty)
    directory = store.experiment_dir(with_uncertainty.experiment_id)
    before = {
        path.relative_to(directory).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(directory.rglob("*"))
        if path.is_file()
    }

    summary = uncertainty_for_experiment(with_uncertainty.experiment_id, store)

    assert summary.requested_variants == N_SAMPLES
    assert to_plain(summary) == to_plain(with_uncertainty.uncertainty)
    after = {
        path.relative_to(directory).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(directory.rglob("*"))
        if path.is_file()
    }
    assert after == before
