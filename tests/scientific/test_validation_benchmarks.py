"""Scientific (domain-neutral) benchmarks for M12C validation.

Uses a linear model (``y = a*x + b``) and, for the extrapolation/regime cases,
a deliberately different generating law. No astrophysics-specific models.
"""

from __future__ import annotations

import pytest

from drw.execution.runner import Runner
from drw.observations import build_dataset, science_hash
from drw.schema.calibration import (
    CalibrationCandidateSummary,
    CalibrationConfig,
    CalibrationObjective,
    CalibrationProvenance,
    CalibrationRef,
    CalibrationResult,
    ExecutionTemplate,
    ObjectiveConfig,
    ParameterSelection,
    short_calibration_id,
)
from drw.schema.calibration import compute_result_hash as compute_calibration_result_hash
from drw.schema.evaluation import EvaluationConfig
from drw.schema.model import ModelRef, ModelSchema, OutputSpec, ParameterSpec
from drw.schema.observation import (
    MappingPair,
    ObservationMapping,
    ObservationSet,
    Provenance,
    Variable,
)
from drw.schema.result import ModelResult, OutputValue, RunStatus, ValidationReport
from drw.schema.serialization import content_hash
from drw.schema.validation import (
    AcceptanceCriterion,
    IndependenceSpec,
    ValidationBudget,
    ValidationConfig,
    ValidationConfigError,
    ValidationDataset,
)
from drw.validation import validate

pytestmark = pytest.mark.scientific

AXIS = [float(index) for index in range(10)]
SCHEMA = ModelSchema(
    model_id="linear",
    parameters=(
        ParameterSpec(name="a", type="float", nominal=1.0, lower=0.0, upper=10.0),
        ParameterSpec(name="b", type="float", nominal=0.0, lower=-10.0, upper=10.0),
    ),
    outputs=(OutputSpec(name="y", kind="timeseries", unit="u"),),
)
TRUE = {"a": 2.0, "b": -1.0}


class LinearAdapter:
    def __init__(self) -> None:
        self.calls = 0

    def describe(self) -> ModelSchema:
        return SCHEMA

    def validate(self, inputs):
        return ValidationReport()

    def run(self, inputs, context):
        self.calls += 1
        a, b = float(inputs["a"]), float(inputs["b"])
        return ModelResult(
            status=RunStatus.SUCCEEDED,
            outputs={
                "y": OutputValue(
                    name="y",
                    kind="timeseries",
                    unit="u",
                    values=[a * x + b for x in AXIS],
                    axis=tuple(AXIS),
                )
            },
        )


# ---------------------------------------------------------------------------
# Fixtures.
# ---------------------------------------------------------------------------


def make_dataset(
    name: str,
    xs: list[float],
    ys: list[float | None],
    *,
    unit: str = "u",
    sites: list[str] | None = None,
    **prov,
) -> object:
    provenance = Provenance(
        source_kind=prov.pop("source_kind", "synthetic"),
        imported_at=prov.pop("imported_at", "2026-01-01T00:00:00+00:00"),
        dataset_version=prov.pop("dataset_version", "1.0.0"),
        **prov,
    )
    variables = [
        Variable(name="x", kind="float", role="coordinate"),
        Variable(name="y", kind="float", role="measurement", unit=unit, depends_on=("x",)),
    ]
    columns: dict[str, list[object]] = {"x": list(xs), "y": list(ys)}
    if sites is not None:
        variables.append(Variable(name="site", kind="categorical", role="metadata"))
        columns["site"] = list(sites)
    return build_dataset(
        name,
        ObservationSet(coordinates=("x",), variables=tuple(variables), columns=columns),
        provenance,
    )


def mapping_for(dataset, *, observation_unit: str = "u") -> ObservationMapping:
    return ObservationMapping(
        dataset=dataset.ref(),
        model_ref=ModelRef(model_id="linear"),
        pairs=(MappingPair(observation="y", output="y", coordinates=("x",)),),
    )


def make_calibration(
    cal_dataset, *, parameters: dict[str, float] | None = None, best: bool = True
) -> CalibrationResult:
    values = dict(TRUE if parameters is None else parameters)
    cal_mapping = mapping_for(cal_dataset)
    config = CalibrationConfig(
        experiment_id="exp-000000000000",
        model_ref=ModelRef(model_id="linear"),
        free=(
            ParameterSelection(name="a", lower=0.0, upper=10.0),
            ParameterSelection(name="b", lower=-10.0, upper=10.0),
        ),
        objective=ObjectiveConfig(),
        execution=ExecutionTemplate(),
        dataset=cal_dataset.ref(),
        mapping=cal_mapping,
        evaluation=EvaluationConfig(),
    )
    candidate = (
        CalibrationCandidateSummary(index=0, parameters=values, run_id="r0", run_status="succeeded", objective=0.0)
        if best
        else None
    )
    payload = {
        "calibration_hash": "a" * 64,
        "result_hash": "",
        "experiment_id": "exp-000000000000",
        "model_ref": ModelRef(model_id="linear"),
        "config": config,
        "status": "converged" if best else "failed",
        "stop_reason": "optimizer_converged" if best else "all_candidates_failed",
        "converged": best,
        "best": candidate,
        "objective": CalibrationObjective(metric="rmse", observation="y", output="y", value=0.0 if best else None),
        "evaluations_requested": 5,
        "evaluations_completed": 5,
        "evaluations_invalid": 0,
        "iterations": 3,
        "wall_seconds": 0.5,
        "history": [candidate] if candidate is not None else [],
        "provenance": CalibrationProvenance(
            experiment_id="exp-000000000000",
            model_id="linear",
            model_hash=SCHEMA.content_hash(),
            environment_hash="c" * 64,
            scipy_version="1.11.0",
            dataset_content_hash=cal_dataset.content_hash,
            dataset_science_hash=science_hash(cal_dataset),
            mapping_hash=content_hash(cal_mapping),
            evaluation_config_hash=content_hash(EvaluationConfig()),
        ),
    }
    result = CalibrationResult(**payload)
    return result.model_copy(update={"result_hash": compute_calibration_result_hash(result)})


def calibration_ref(result: CalibrationResult) -> CalibrationRef:
    return CalibrationRef(
        calibration_id=short_calibration_id(result.result_hash),
        result_hash=result.result_hash,
        experiment_id=result.experiment_id,
        model_id="linear",
        status=result.status,
    )


def make_config(
    cal_dataset,
    cal_result: CalibrationResult,
    val_datasets: list[tuple[object, dict]],
    *,
    evaluation: EvaluationConfig | None = None,
    budget: ValidationBudget | None = None,
    acceptance: tuple[AcceptanceCriterion, ...] = (),
    report_gap: bool = False,
    allow_non_independent: bool = False,
) -> ValidationConfig:
    items = []
    for dataset, independence in val_datasets:
        items.append(
            ValidationDataset(
                dataset=dataset.ref(),
                mapping=mapping_for(dataset),
                independence=IndependenceSpec(vs_dataset=cal_dataset.ref(), **independence),
            )
        )
    return ValidationConfig(
        experiment_id="exp-000000000000",
        model_ref=ModelRef(model_id="linear"),
        calibration=calibration_ref(cal_result),
        datasets=tuple(items),
        evaluation=evaluation or EvaluationConfig(),
        budget=budget or ValidationBudget(max_evaluations=10),
        acceptance=acceptance,
        report_gap=report_gap,
        allow_non_independent=allow_non_independent,
    )


def run(config, cal_dataset, cal_result, val_datasets, adapter):
    datasets = {dataset.dataset_id: dataset for dataset, _ in val_datasets}
    return validate(
        config,
        schema=SCHEMA,
        calibration=cal_result,
        datasets=datasets,
        calibration_dataset=cal_dataset,
        baseline={},
        runner=Runner(adapter=adapter),
    )


def linear_calibration_dataset() -> object:
    return make_dataset("cal", AXIS, [2.0 * x - 1.0 for x in AXIS])


def linear_validation_dataset(name: str = "val", *, offset: float = 0.001) -> object:
    """A distinct dataset drawn from the same law (aligned to the model axis)."""
    return make_dataset(name, AXIS, [2.0 * x - 1.0 + offset for x in AXIS])


# ---------------------------------------------------------------------------
# 1. Perfect generalisation.
# ---------------------------------------------------------------------------


def test_perfect_generalisation():
    cal = linear_calibration_dataset()
    cal_result = make_calibration(cal)
    val = linear_validation_dataset()
    independence = {"claimed_dimensions": ("dataset",)}
    config = make_config(
        cal,
        cal_result,
        [(val, independence)],
        acceptance=(AcceptanceCriterion(metric="rmse", op="<=", threshold=0.5),),
    )
    result = run(config, cal, cal_result, [(val, independence)], LinearAdapter())
    dataset_result = result.datasets[0]
    assert dataset_result.agreement == "evaluated"
    assert dataset_result.metrics["rmse"] is not None
    assert dataset_result.metrics["rmse"] < 0.01
    assert result.independence_status == "verified"
    assert result.acceptance_status == "met"
    assert result.descriptive is False


# ---------------------------------------------------------------------------
# 2. Regime change / overfit gap.
# ---------------------------------------------------------------------------


def test_gap_is_reported_when_regime_changes():
    cal = linear_calibration_dataset()
    cal_result = make_calibration(cal)
    val = make_dataset("val", AXIS, [5.0 * x + 1.0 for x in AXIS])
    config = make_config(
        cal,
        cal_result,
        [(val, {"claimed_dimensions": ("dataset",)})],
        acceptance=(AcceptanceCriterion(metric="rmse", op="<=", threshold=0.5),),
        report_gap=True,
    )
    result = run(config, cal, cal_result, [(val, {"claimed_dimensions": ("dataset",)})], LinearAdapter())
    dataset_result = result.datasets[0]
    assert dataset_result.agreement == "evaluated"
    assert dataset_result.metrics["rmse"] > 1.0
    assert dataset_result.calibration_metrics["rmse"] < 1e-9
    # Acceptance not met, and a met acceptance is never implied by usable metrics.
    assert result.acceptance_status == "not_met"


# ---------------------------------------------------------------------------
# 3-4. Leakage.
# ---------------------------------------------------------------------------


def test_leakage_identical_dataset_fails_closed():
    cal = linear_calibration_dataset()
    cal_result = make_calibration(cal)
    config = make_config(cal, cal_result, [(cal, {})])
    result = run(config, cal, cal_result, [(cal, {})], LinearAdapter())
    assert result.datasets[0].failure == "independence_violated"
    assert result.datasets[0].agreement == "failed"
    assert result.agreement_status == "failed"
    assert result.independence_status == "violated"


def test_descriptive_run_on_non_independent_data_is_disclosed():
    cal = linear_calibration_dataset()
    cal_result = make_calibration(cal)
    config = make_config(cal, cal_result, [(cal, {})], allow_non_independent=True)
    result = run(config, cal, cal_result, [(cal, {})], LinearAdapter())
    assert result.descriptive is True
    assert result.independence_status == "violated"
    assert any(d.code == "descriptive_run" for d in result.diagnostics)


def test_same_science_different_provenance_is_violated():
    cal = make_dataset("cal", AXIS, [2.0 * x - 1.0 for x in AXIS], source_id="a")
    other = make_dataset("val", AXIS, [2.0 * x - 1.0 for x in AXIS], source_id="b")
    cal_result = make_calibration(cal)
    config = make_config(cal, cal_result, [(other, {})])
    result = run(config, cal, cal_result, [(other, {})], LinearAdapter())
    assert result.datasets[0].failure == "independence_violated"


# ---------------------------------------------------------------------------
# 5. Temporal holdout.
# ---------------------------------------------------------------------------


def test_disjoint_time_window_is_verified():
    cal = make_dataset("cal", [0.0, 1.0, 2.0, 3.0], [1.0, 2.0, 3.0, 4.0])
    val = make_dataset("val", [10.0, 11.0, 12.0], [19.0, 21.0, 23.0])
    cal_result = make_calibration(cal)
    config = make_config(cal, cal_result, [(val, {"claimed_dimensions": ("time_window",)})])
    result = run(config, cal, cal_result, [(val, {"claimed_dimensions": ("time_window",)})], LinearAdapter())
    assert result.independence_status == "verified"


def test_overlapping_time_window_is_violated():
    cal = make_dataset("cal", [0.0, 1.0, 2.0, 3.0], [1.0, 2.0, 3.0, 4.0])
    val = make_dataset("val", [2.0, 3.0, 4.0], [3.0, 4.0, 5.0])
    cal_result = make_calibration(cal)
    config = make_config(cal, cal_result, [(val, {"claimed_dimensions": ("time_window",)})])
    result = run(config, cal, cal_result, [(val, {"claimed_dimensions": ("time_window",)})], LinearAdapter())
    assert result.datasets[0].failure == "independence_violated"


# ---------------------------------------------------------------------------
# 6. Grouped holdout.
# ---------------------------------------------------------------------------


def test_disjoint_group_keys_verified():
    cal = make_dataset("cal", AXIS, [2.0 * x - 1.0 for x in AXIS], sites=["A"] * 10)
    val = make_dataset("val", AXIS, [2.0 * x - 1.0 for x in AXIS], sites=["B"] * 10)
    cal_result = make_calibration(cal)
    ind = {"claimed_dimensions": ("entity",), "group_key": "site"}
    config = make_config(cal, cal_result, [(val, ind)])
    result = run(config, cal, cal_result, [(val, ind)], LinearAdapter())
    assert result.independence_status == "verified"


def test_shared_group_keys_violated():
    cal = make_dataset("cal", AXIS, [2.0 * x - 1.0 for x in AXIS], sites=["A"] * 10)
    val = make_dataset("val", AXIS, [2.0 * x - 1.0 for x in AXIS], sites=["A"] * 10)
    cal_result = make_calibration(cal)
    ind = {"claimed_dimensions": ("entity",), "group_key": "site"}
    config = make_config(cal, cal_result, [(val, ind)])
    result = run(config, cal, cal_result, [(val, ind)], LinearAdapter())
    assert result.datasets[0].failure == "independence_violated"


# ---------------------------------------------------------------------------
# 7. Extrapolation context.
# ---------------------------------------------------------------------------


def test_extrapolation_context_is_recorded():
    cal = make_dataset("cal", [0.0, 1.0, 2.0, 3.0], [1.0, 2.0, 3.0, 4.0])
    val = make_dataset("val", [10.0, 11.0, 12.0], [19.0, 21.0, 23.0])
    cal_result = make_calibration(cal)
    config = make_config(cal, cal_result, [(val, {})])
    result = run(config, cal, cal_result, [(val, {})], LinearAdapter())
    context = result.datasets[0].context
    assert context.coordinate_ranges[0].classification == "outside_range"
    assert "outside the tested region" in context.note


# ---------------------------------------------------------------------------
# 8. Incompatible units.
# ---------------------------------------------------------------------------


def test_incompatible_units_fail_closed():
    cal = linear_calibration_dataset()
    cal_result = make_calibration(cal)
    val = make_dataset("val", AXIS, [2.0 * x - 1.0 for x in AXIS], unit="K")
    config = make_config(cal, cal_result, [(val, {})])
    result = run(config, cal, cal_result, [(val, {})], LinearAdapter())
    assert result.datasets[0].failure == "incompatible_units"


# ---------------------------------------------------------------------------
# 9. Empty / all-excluded datasets.
# ---------------------------------------------------------------------------


def test_empty_dataset_fails_closed():
    cal = linear_calibration_dataset()
    cal_result = make_calibration(cal)
    empty = make_dataset("empty", [], [])
    config = make_config(cal, cal_result, [(empty, {})])
    result = run(config, cal, cal_result, [(empty, {})], LinearAdapter())
    assert result.datasets[0].failure == "empty_validation_dataset"


def test_all_observations_excluded_fails_closed():
    cal = linear_calibration_dataset()
    cal_result = make_calibration(cal)
    val = make_dataset("val", AXIS, [None] * 10)
    config = make_config(cal, cal_result, [(val, {})])
    result = run(config, cal, cal_result, [(val, {})], LinearAdapter())
    assert result.datasets[0].failure == "no_usable_observations"


# ---------------------------------------------------------------------------
# 10. Failed calibration / structural failures.
# ---------------------------------------------------------------------------


def test_failed_calibration_fails_before_execution():
    cal = linear_calibration_dataset()
    cal_result = make_calibration(cal, best=False)
    config = make_config(cal, cal_result, [(cal, {})])
    adapter = LinearAdapter()
    with pytest.raises(ValidationConfigError, match="no best candidate"):
        run(config, cal, cal_result, [(cal, {})], adapter)
    assert adapter.calls == 0


# ---------------------------------------------------------------------------
# 11. Budget exhaustion across datasets.
# ---------------------------------------------------------------------------


def test_budget_exhaustion_preserves_partial_results():
    cal = linear_calibration_dataset()
    cal_result = make_calibration(cal)
    val_a = linear_validation_dataset("a", offset=0.001)
    val_b = linear_validation_dataset("b", offset=0.002)
    config = make_config(
        cal,
        cal_result,
        [(val_a, {}), (val_b, {})],
        budget=ValidationBudget(max_evaluations=1),
    )
    result = run(config, cal, cal_result, [(val_a, {}), (val_b, {})], LinearAdapter())
    assert result.datasets[0].agreement == "evaluated"
    assert result.datasets[1].failure == "budget_exhausted"
    assert result.datasets[1].agreement == "not_run"
    assert result.agreement_status == "partial"
    assert any(d.code == "budget_exhausted" for d in result.diagnostics)


# ---------------------------------------------------------------------------
# 12. No refit / no optimizer / Runner-only / no mutation.
# ---------------------------------------------------------------------------


def test_validation_cannot_refit_and_uses_runner_only(monkeypatch):
    import drw.calibration.optimizers as optimizers

    def _forbidden(*args, **kwargs):
        raise AssertionError("validation must not build an optimizer")

    monkeypatch.setattr(optimizers, "build_optimizer", _forbidden)

    cal = linear_calibration_dataset()
    cal_result = make_calibration(cal)
    before = dict(cal_result.best.parameters)
    val = linear_validation_dataset()
    adapter = LinearAdapter()
    config = make_config(cal, cal_result, [(val, {})], report_gap=False)
    result = run(config, cal, cal_result, [(val, {})], adapter)
    assert result.datasets[0].agreement == "evaluated"
    assert adapter.calls == 1  # exactly one run, through the Runner
    # The frozen calibration is never mutated.
    assert dict(cal_result.best.parameters) == before
    assert result.calibration.parameters == before
    assert result.provenance.deterministic is True


def test_repeated_validation_is_deterministic():
    cal = linear_calibration_dataset()
    cal_result = make_calibration(cal)
    val = linear_validation_dataset()
    config = make_config(cal, cal_result, [(val, {})])
    first = run(config, cal, cal_result, [(val, {})], LinearAdapter())
    second = run(config, cal, cal_result, [(val, {})], LinearAdapter())
    assert first.result_hash == second.result_hash


# ---------------------------------------------------------------------------
# 13. Metric unavailability / acceptance indeterminate.
# ---------------------------------------------------------------------------


def test_unavailable_metrics_are_inconclusive_not_met():
    cal = linear_calibration_dataset()
    cal_result = make_calibration(cal)
    val = linear_validation_dataset()
    evaluation = EvaluationConfig(
        metrics=("weighted_rmse",), residual_modes=("raw", "normalized")
    )
    config = make_config(
        cal,
        cal_result,
        [(val, {})],
        evaluation=evaluation,
        acceptance=(AcceptanceCriterion(metric="weighted_rmse", op="<=", threshold=0.5),),
    )
    result = run(config, cal, cal_result, [(val, {})], LinearAdapter())
    dataset_result = result.datasets[0]
    assert dataset_result.metrics["weighted_rmse"] is None
    assert dataset_result.failure == "metrics_unavailable"
    assert dataset_result.agreement == "inconclusive"
    assert dataset_result.acceptance[0].status == "indeterminate"
    assert result.acceptance_status == "indeterminate"
