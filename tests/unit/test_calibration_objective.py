"""Unit tests for the M12B objective oracle (Phase B)."""

from __future__ import annotations

import pytest

from drw.calibration.objective import (
    OBJECTIVE_SENTINEL,
    ObjectiveOracle,
    resolve_objective_pair,
)
from drw.schema.calibration import ObjectiveConfig
from drw.schema.evaluation import (
    EvaluationConfig,
    EvaluationProvenance,
    EvaluationResult,
    PairEvaluation,
)
from drw.schema.model import ModelRef
from drw.schema.observation import (
    DatasetRef,
    MappingPair,
    ObservationMapping,
    short_dataset_id,
)
from drw.schema.result import Diagnostic

pytestmark = pytest.mark.unit

HASH = "a" * 64
REF = DatasetRef(dataset_id=short_dataset_id(HASH), content_hash=HASH, name="d")


def make_mapping(pairs=(("y", "y"),)) -> ObservationMapping:
    return ObservationMapping(
        dataset=REF,
        model_ref=ModelRef(model_id="model"),
        pairs=tuple(MappingPair(observation=o, output=m) for o, m in pairs),
    )


def make_pair(metrics, *, observation="y", output="y", usable=3, excluded=1) -> PairEvaluation:
    return PairEvaluation(
        observation=observation,
        output=output,
        kind="timeseries",
        unit="u",
        alignment="exact",
        tolerance=0.0,
        interpolated=False,
        points=[],
        exclusions=[],
        usable_count=usable,
        excluded_count=excluded,
        exclusion_counts={},
        metrics=metrics,
        diagnostics=[],
    )


def make_evaluation(pairs, *, ok=True, diagnostics=()) -> EvaluationResult:
    return EvaluationResult(
        evaluation_hash="e" * 64,
        dataset=REF,
        experiment_id="exp-000000000000",
        run_id="exp-000000000000-r0000",
        attempt=1,
        model_ref=ModelRef(model_id="model"),
        model_hash="b" * 64,
        parameter_snapshot={"a": 1.0},
        mapping=make_mapping(),
        mapping_hash="c" * 64,
        config=EvaluationConfig(),
        pairs=list(pairs),
        total_usable=sum(p.usable_count for p in pairs),
        total_excluded=sum(p.excluded_count for p in pairs),
        ok=ok,
        diagnostics=list(diagnostics),
        provenance=EvaluationProvenance(
            dataset_content_hash=HASH, mapping_hash="c" * 64
        ),
    )


def oracle(metric="rmse", observation=None, output=None, pairs=(("y", "y"),)) -> ObjectiveOracle:
    return ObjectiveOracle(
        ObjectiveConfig(metric=metric, observation=observation, output=output),
        make_mapping(pairs),
    )


def test_perfect_fit_objective_is_zero():
    outcome = oracle().from_evaluation(make_evaluation([make_pair({"rmse": 0.0})]))
    assert outcome.value == 0.0
    assert outcome.failure is None
    assert outcome.n_used == 3 and outcome.n_excluded == 1


def test_wrong_fit_objective_is_metric_value():
    outcome = oracle().from_evaluation(make_evaluation([make_pair({"rmse": 2.5})]))
    assert outcome.value == pytest.approx(2.5)


def test_weighted_objective_is_read_from_m12a():
    outcome = oracle(metric="weighted_rmse").from_evaluation(
        make_evaluation([make_pair({"weighted_rmse": 1.2})])
    )
    assert outcome.value == pytest.approx(1.2)


def test_invalid_evaluation_yields_null_objective_with_code():
    diagnostics = [Diagnostic(level="error", code="incompatible_units", message="m vs K")]
    outcome = oracle().from_evaluation(make_evaluation([], ok=False, diagnostics=diagnostics))
    assert outcome.value is None
    assert outcome.failure == "incompatible_units"


def test_no_usable_observations_yields_null_objective():
    diagnostics = [
        Diagnostic(level="error", code="no_usable_observations", message="none usable")
    ]
    outcome = oracle().from_evaluation(make_evaluation([], ok=False, diagnostics=diagnostics))
    assert outcome.value is None
    assert outcome.failure == "no_usable_observations"


def test_null_metric_yields_objective_undefined():
    outcome = oracle().from_evaluation(make_evaluation([make_pair({"mae": 1.0})]))
    assert outcome.value is None
    assert outcome.failure == "objective_undefined"


def test_non_finite_metric_protected():
    outcome = oracle().from_evaluation(make_evaluation([make_pair({"rmse": float("inf")})]))
    assert outcome.value is None
    assert outcome.failure == "non_finite_objective"


def test_missing_pair_yields_pair_not_found():
    outcome = oracle().from_evaluation(
        make_evaluation([make_pair({"rmse": 1.0}, observation="other", output="other")])
    )
    assert outcome.value is None
    assert outcome.failure == "pair_not_found"


def test_multi_pair_requires_selector():
    with pytest.raises(ValueError, match="select one mapping pair"):
        resolve_objective_pair(ObjectiveConfig(), make_mapping(pairs=(("y", "y"), ("p", "p"))))


def test_multi_pair_with_selector_resolves():
    pair = resolve_objective_pair(
        ObjectiveConfig(observation="p", output="p"),
        make_mapping(pairs=(("y", "y"), ("p", "p"))),
    )
    assert (pair.observation, pair.output) == ("p", "p")


def test_sentinel_maps_none_to_inf_only_for_optimizer():
    assert oracle().sentinel(None) == OBJECTIVE_SENTINEL
    assert oracle().sentinel(0.0) == 0.0
    assert float("inf") == OBJECTIVE_SENTINEL