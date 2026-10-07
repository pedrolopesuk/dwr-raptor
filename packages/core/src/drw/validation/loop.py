"""Frozen-parameter validation execution loop (M12C-C).

The loop is the orchestration layer. It is **strictly serial**, owns its own
hard budget and never contains an optimizer. For each validation dataset it:

1. checks independence (mechanical, structured) and fails the dataset closed on
   leakage unless the run is explicitly marked descriptive,
2. validates the mapping with M11,
3. builds a throwaway single-run :class:`~drw.schema.experiment.ExperimentSpec`
   whose baseline is the **frozen** calibration vector,
4. executes it through the **existing** :class:`~drw.execution.runner.Runner`,
5. compares it to the dataset with **M12A** ``evaluate_run``,
6. asserts the executed parameter snapshot equals the frozen vector,
7. optionally re-evaluates the calibration dataset for a descriptive gap,
8. applies the optional user acceptance criteria and records the context.

It never executes a model directly, never re-implements comparison and cannot
refit.
"""

from __future__ import annotations

import math
import threading
import time
from collections import Counter
from collections.abc import Mapping, Sequence
from typing import Any

import scipy

from drw.evaluation import evaluate_run
from drw.execution.environment import environment_fingerprint, fingerprint_hash
from drw.execution.runner import ExperimentValidationError, Runner
from drw.observations import science_hash, validate_mapping
from drw.schema.calibration import CalibrationResult
from drw.schema.experiment import ExecutionSpec, ExperimentSpec, VerificationSpec
from drw.schema.model import ModelSchema
from drw.schema.observation import Dataset, ObservationMapping
from drw.schema.result import Diagnostic
from drw.schema.serialization import content_hash
from drw.schema.validation import (
    DEFAULT_VALIDATION_DISCLOSURE,
    AcceptanceCriterion,
    AcceptanceOutcome,
    AcceptanceStatus,
    AgreementStatus,
    IndependenceReport,
    IndependenceStatus,
    ValidationCalibrationSnapshot,
    ValidationConfig,
    ValidationConfigError,
    ValidationContext,
    ValidationDataset,
    ValidationDatasetResult,
    ValidationParameterMismatch,
    ValidationProvenance,
    ValidationResult,
    compute_validation_hash,
    compute_validation_result_hash,
    resolve_validation,
)
from drw.validation.independence import (
    coordinate_range_comparisons,
    evaluate_independence,
    unseen_groups,
)

__all__ = ["build_context", "validate", "validate_for_experiment"]

_METRIC_NONE_REASON = "metric unavailable or non-finite"


def build_context(
    calibration_dataset: Dataset,
    validation_dataset: Dataset,
    mapping: ObservationMapping,
    group_key: str | None = None,
    regime: str = "",
) -> ValidationContext:
    """Minimal, mechanically-derived interpolation/extrapolation context."""
    comparisons = coordinate_range_comparisons(calibration_dataset, validation_dataset, mapping)
    unseen = unseen_groups(calibration_dataset, validation_dataset, group_key)
    outside = [item.coordinate for item in comparisons if item.classification == "outside_range"]
    if outside:
        note = (
            "Validation data lies outside the range exercised during calibration along "
            f"{', '.join(outside)}; agreement here does not imply agreement outside the tested "
            "region."
        )
    else:
        note = (
            "Validation data lies within the calibration coordinate range where comparable; this "
            "does not imply agreement outside the tested region."
        )
    return ValidationContext(
        coordinate_ranges=comparisons, unseen_groups=unseen, regime=regime, note=note
    )


def _first_error_code(diagnostics: Sequence[Diagnostic], fallback: str) -> str:
    for diagnostic in diagnostics:
        if diagnostic.level == "error":
            return diagnostic.code
    return fallback


def _finite_or_none(value: float | None) -> float | None:
    if value is None or not math.isfinite(value):
        return None
    return float(value)


def _metric_keys(mapping: ObservationMapping, metric: str) -> list[str]:
    if len(mapping.pairs) == 1:
        return [metric]
    return [f"{pair.observation}->{pair.output}:{metric}" for pair in mapping.pairs]


def extract_metrics(
    evaluation: Any, mapping: ObservationMapping
) -> dict[str, float | None]:
    """Extract the requested M12A metrics per pair (never recomputed)."""
    metrics: dict[str, float | None] = {}
    pairs = list(evaluation.pairs)
    for metric in evaluation.config.metrics:
        if len(mapping.pairs) == 1:
            value = pairs[0].metrics.get(metric) if pairs else None
            metrics[metric] = _finite_or_none(value)
        else:
            for pair in mapping.pairs:
                match = next(
                    (p for p in pairs if p.observation == pair.observation and p.output == pair.output),
                    None,
                )
                value = match.metrics.get(metric) if match is not None else None
                metrics[f"{pair.observation}->{pair.output}:{metric}"] = _finite_or_none(value)
    return metrics


def _aggregate_exclusions(evaluation: Any) -> dict[str, int]:
    counts: Counter[str] = Counter()
    for pair in evaluation.pairs:
        counts.update(pair.exclusion_counts)
    return dict(sorted(counts.items()))


def _lookup_metric(
    metrics: Mapping[str, float | None],
    criterion: AcceptanceCriterion,
    mapping: ObservationMapping,
) -> float | None:
    composite = None
    if criterion.observation is not None:
        composite = f"{criterion.observation}->{criterion.output}:{criterion.metric}"
    bare = criterion.metric if len(mapping.pairs) == 1 else None
    for key in (composite, bare, criterion.metric):
        if key is not None and key in metrics:
            return metrics[key]
    return None


def _compare(op: str, value: float, threshold: float) -> bool:
    if op == "<=":
        return value <= threshold
    if op == "<":
        return value < threshold
    if op == ">=":
        return value >= threshold
    return value > threshold


def apply_acceptance(
    criteria: Sequence[AcceptanceCriterion],
    metrics: Mapping[str, float | None],
    mapping: ObservationMapping,
) -> tuple[AcceptanceOutcome, ...]:
    """Apply user acceptance criteria; a null/non-finite metric is never ``met``."""
    outcomes: list[AcceptanceOutcome] = []
    for criterion in criteria:
        value = _lookup_metric(metrics, criterion, mapping)
        if value is None or not math.isfinite(value):
            outcomes.append(
                AcceptanceOutcome(
                    metric=criterion.metric,
                    observation=criterion.observation,
                    output=criterion.output,
                    op=criterion.op,
                    threshold=criterion.threshold,
                    observed=None,
                    status="indeterminate",
                    message=_METRIC_NONE_REASON,
                )
            )
            continue
        met = _compare(criterion.op, value, criterion.threshold)
        outcomes.append(
            AcceptanceOutcome(
                metric=criterion.metric,
                observation=criterion.observation,
                output=criterion.output,
                op=criterion.op,
                threshold=criterion.threshold,
                observed=value,
                status="met" if met else "not_met",
            )
        )
    return tuple(outcomes)


def _criteria_for(item: ValidationDataset, config: ValidationConfig) -> tuple[AcceptanceCriterion, ...]:
    if item.acceptance is not None:
        return tuple(item.acceptance)
    return tuple(config.acceptance)


class _Driver:
    """One serial validation over all configured datasets."""

    def __init__(
        self,
        *,
        config: ValidationConfig,
        schema: ModelSchema,
        calibration: CalibrationResult,
        calibration_dataset: Dataset,
        datasets: Mapping[str, Dataset],
        frozen: dict[str, Any],
        baseline: Mapping[str, Any],
        runner: Runner | None,
        spec_hash: str,
        environment: dict[str, Any],
        cancel_event: threading.Event | None,
    ) -> None:
        self.config = config
        self.schema = schema
        self.calibration = calibration
        self.calibration_dataset = calibration_dataset
        self.datasets = datasets
        self.frozen = frozen
        self.baseline = baseline
        self.runner: Any = runner if runner is not None else Runner()
        self.spec_hash = spec_hash
        self.environment = environment
        self.environment_hash = fingerprint_hash(environment)
        self.cancel_event = cancel_event
        self.evaluations = 0
        self.failed = 0
        self.descriptive = False
        self._start = time.monotonic()

    # -- budget -------------------------------------------------------------

    def _can_run(self) -> bool:
        if self.cancel_event is not None and self.cancel_event.is_set():
            return False
        if self.evaluations >= self.config.budget.max_evaluations:
            return False
        return time.monotonic() - self._start <= self.config.budget.max_wall_seconds

    # -- execution ----------------------------------------------------------

    def _spec(self, inputs: Mapping[str, Any]) -> ExperimentSpec:
        template = self.config.execution
        return ExperimentSpec(
            name="validation",
            hypothesis="Frozen-parameter validation of an independent dataset.",
            model_ref=self.config.model_ref,
            baseline=dict(inputs),
            factors=(),
            outputs=(),
            analyses=(),
            execution=ExecutionSpec(
                solver=template.solver,
                timeout_s=template.timeout_s,
                max_runs=1,
                isolation=template.isolation,
            ),
            verification=VerificationSpec(),
        )

    def _run_dataset(
        self, dataset: Dataset, mapping: ObservationMapping
    ) -> tuple[Any, Any, str | None]:
        """Execute one single-run spec and evaluate it. Returns (run, evaluation, failure)."""
        spec = self._spec(self.frozen)
        try:
            experiment = self.runner.run(spec, cancel_event=self.cancel_event)
        except ExperimentValidationError:
            return None, None, "validation_error"
        self.evaluations += 1
        run = experiment.runs[0]
        if run.timed_out:
            return run, None, "run_timed_out"
        if not run.succeeded:
            return run, None, "run_failed"
        evaluation = evaluate_run(
            run,
            schema=self.schema,
            dataset=dataset,
            mapping=mapping,
            config=self.config.evaluation,
            spec_hash=experiment.spec_hash,
            environment_hash=fingerprint_hash(experiment.environment),
            model_hash=experiment.model_hash,
        )
        return run, evaluation, None

    def _assert_frozen(self, evaluation: Any) -> None:
        snapshot = dict(evaluation.parameter_snapshot)
        expected = self.frozen
        if set(snapshot) != set(expected) or any(
            snapshot.get(name) != value for name, value in expected.items()
        ):
            raise ValidationParameterMismatch(
                "the executed parameter snapshot does not match the frozen calibrated vector"
            )

    # -- per-dataset --------------------------------------------------------

    def _empty_result(
        self,
        item: ValidationDataset,
        report: IndependenceReport,
        context: ValidationContext,
        *,
        failure: str,
        agreement: AgreementStatus,
        diagnostics: Sequence[Diagnostic] = (),
    ) -> ValidationDatasetResult:
        return ValidationDatasetResult(
            label=item.label,
            dataset=item.dataset,
            mapping_hash=content_hash(item.mapping),
            independence=report,
            context=context,
            run_id=None,
            run_status=None,
            evaluation_hash=None,
            metrics={},
            n_used=0,
            n_excluded=0,
            exclusion_counts={},
            calibration_metrics={},
            calibration_evaluation_hash=None,
            acceptance=(),
            agreement=agreement,
            failure=failure,
            diagnostics=tuple(diagnostics),
        )

    def _evaluate_dataset(self, item: ValidationDataset) -> ValidationDatasetResult:
        dataset = self.datasets[item.dataset.dataset_id]
        mapping = item.mapping
        report = evaluate_independence(item.independence, self.calibration_dataset, dataset, mapping)
        context = build_context(
            self.calibration_dataset,
            dataset,
            mapping,
            item.independence.group_key,
        )

        if report.status == "violated" and not self.config.allow_non_independent:
            return self._empty_result(
                item,
                report,
                context,
                failure="independence_violated",
                agreement="failed",
            )
        if report.status == "violated":
            self.descriptive = True

        mapping_diagnostics = validate_mapping(mapping, dataset=dataset, schema=self.schema)
        if any(diagnostic.level == "error" for diagnostic in mapping_diagnostics):
            return self._empty_result(
                item,
                report,
                context,
                failure=_first_error_code(mapping_diagnostics, "invalid_mapping"),
                agreement="failed",
                diagnostics=mapping_diagnostics,
            )
        if dataset.observation_set.row_count == 0:
            return self._empty_result(
                item,
                report,
                context,
                failure="empty_validation_dataset",
                agreement="failed",
            )

        run, evaluation, failure = self._run_dataset(dataset, mapping)
        if failure is not None or evaluation is None:
            return ValidationDatasetResult(
                label=item.label,
                dataset=item.dataset,
                mapping_hash=content_hash(mapping),
                independence=report,
                context=context,
                run_id=run.run_id if run is not None else None,
                run_status=run.status.value if run is not None else None,
                evaluation_hash=None,
                metrics={},
                agreement="failed",
                failure=failure or "run_failed",
            )

        self._assert_frozen(evaluation)
        metrics = extract_metrics(evaluation, mapping)
        n_used = evaluation.total_usable
        n_excluded = evaluation.total_excluded
        exclusion_counts = _aggregate_exclusions(evaluation)

        dataset_failure: str | None = None
        if not evaluation.ok:
            dataset_failure = _first_error_code(evaluation.diagnostics, "evaluation_failed")
        elif not any(value is not None for value in metrics.values()):
            dataset_failure = "metrics_unavailable"

        if dataset_failure is not None:
            agreement: AgreementStatus = (
                "failed" if not evaluation.ok else "inconclusive"
            )
        else:
            agreement = "evaluated"

        calibration_metrics, calibration_evaluation_hash, gap_diagnostics = (
            self._calibration_gap()
            if self.config.report_gap and dataset_failure is None
            else ({}, None, [])
        )

        acceptance = apply_acceptance(
            _criteria_for(item, self.config), metrics, mapping
        )

        return ValidationDatasetResult(
            label=item.label,
            dataset=item.dataset,
            mapping_hash=content_hash(mapping),
            independence=report,
            context=context,
            run_id=run.run_id,
            run_status=run.status.value,
            evaluation_hash=evaluation.evaluation_hash,
            metrics=metrics,
            n_used=n_used,
            n_excluded=n_excluded,
            exclusion_counts=exclusion_counts,
            calibration_metrics=calibration_metrics,
            calibration_evaluation_hash=calibration_evaluation_hash,
            acceptance=acceptance,
            agreement=agreement,
            failure=dataset_failure,
            diagnostics=tuple([*gap_diagnostics]),
        )

    def _calibration_gap(self) -> tuple[dict[str, float | None], str | None, list[Diagnostic]]:
        """Re-evaluate the frozen model on the calibration dataset with the same config."""
        if not self._can_run():
            return {}, None, [
                Diagnostic(
                    level="warning",
                    code="gap_not_reported",
                    message="the calibration-vs-validation gap was not computed (budget exhausted)",
                )
            ]
        mapping = self.calibration.config.mapping
        _run, evaluation, failure = self._run_dataset(self.calibration_dataset, mapping)
        if failure is not None or evaluation is None:
            return {}, None, [
                Diagnostic(
                    level="warning",
                    code="gap_not_reported",
                    message=f"the calibration-vs-validation gap could not be computed ({failure})",
                )
            ]
        metrics = extract_metrics(evaluation, mapping)
        return metrics, evaluation.evaluation_hash, []

    # -- result -------------------------------------------------------------

    def run(self) -> ValidationResult:
        results: list[ValidationDatasetResult] = []
        for item in self.config.datasets:
            if not self._can_run():
                dataset = self.datasets.get(item.dataset.dataset_id)
                report = IndependenceReport(status="unknown")
                context = ValidationContext()
                if dataset is not None:
                    report = evaluate_independence(
                        item.independence, self.calibration_dataset, dataset, item.mapping
                    )
                    context = build_context(
                        self.calibration_dataset, dataset, item.mapping, item.independence.group_key
                    )
                results.append(
                    self._empty_result(
                        item,
                        report,
                        context,
                        failure="budget_exhausted",
                        agreement="not_run",
                    )
                )
                continue
            result = self._evaluate_dataset(item)
            results.append(result)
            if result.failure is not None:
                self.failed += 1

        return self._finalize(tuple(results))

    def _finalize(self, results: tuple[ValidationDatasetResult, ...]) -> ValidationResult:
        calibration = self.calibration
        best = calibration.best
        snapshot = ValidationCalibrationSnapshot(
            calibration_id=self.config.calibration.calibration_id,
            result_hash=calibration.result_hash,
            calibration_hash=calibration.calibration_hash,
            model_id=calibration.model_ref.model_id,
            model_hash=calibration.provenance.model_hash,
            parameters=dict(best.parameters) if best is not None else {},
            dataset_content_hash=calibration.provenance.dataset_content_hash,
            dataset_science_hash=calibration.provenance.dataset_science_hash,
            mapping_hash=calibration.provenance.mapping_hash,
            evaluation_hash=calibration.provenance.evaluation_hash,
        )
        loaded = [self.datasets[item.dataset.dataset_id] for item in self.config.datasets]
        provenance = ValidationProvenance(
            experiment_id=self.config.experiment_id,
            spec_hash=self.spec_hash,
            model_id=self.schema.model_id,
            model_hash=self.schema.content_hash(),
            calibration_result_hash=calibration.result_hash,
            calibration_hash=calibration.calibration_hash,
            calibration_dataset_content_hash=calibration.provenance.dataset_content_hash,
            calibration_dataset_science_hash=calibration.provenance.dataset_science_hash,
            calibration_mapping_hash=calibration.provenance.mapping_hash,
            calibration_evaluation_hash=calibration.provenance.evaluation_hash,
            validation_dataset_content_hashes=tuple(item.content_hash for item in loaded),
            validation_science_hashes=tuple(science_hash(item) for item in loaded),
            mapping_hashes=tuple(content_hash(item.mapping) for item in self.config.datasets),
            evaluation_config_hash=content_hash(self.config.evaluation),
            evaluation_hashes=tuple(
                result.evaluation_hash for result in results if result.evaluation_hash
            ),
            environment_hash=self.environment_hash,
            engine_schema_version=self.config.schema_version,
            scipy_version=scipy.__version__,
            deterministic=True,
        )
        diagnostics: list[Diagnostic] = []
        if self.descriptive:
            diagnostics.append(
                Diagnostic(
                    level="warning",
                    code="descriptive_run",
                    message=(
                        "at least one dataset failed an independence check but the run was "
                        "explicitly allowed; it is descriptive and is not independent evidence"
                    ),
                )
            )
        if any(result.failure == "budget_exhausted" for result in results):
            diagnostics.append(
                Diagnostic(
                    level="warning",
                    code="budget_exhausted",
                    message="the validation budget was exhausted before every dataset ran",
                )
            )
        result = ValidationResult(
            validation_hash=compute_validation_hash(self.config),
            result_hash="",
            experiment_id=self.config.experiment_id,
            model_ref=self.config.model_ref,
            config=self.config,
            calibration=snapshot,
            datasets=results,
            agreement_status=_agreement_rollup(results),
            acceptance_status=_acceptance_rollup(results),
            independence_status=_independence_rollup(results),
            evaluations_requested=self.config.budget.max_evaluations,
            evaluations_completed=self.evaluations,
            evaluations_failed=self.failed,
            wall_seconds=time.monotonic() - self._start,
            descriptive=self.descriptive,
            diagnostics=tuple(diagnostics),
            provenance=provenance,
            note=DEFAULT_VALIDATION_DISCLOSURE,
        )
        return result.model_copy(update={"result_hash": compute_validation_result_hash(result)})


def _agreement_rollup(results: Sequence[ValidationDatasetResult]) -> AgreementStatus:
    states = [result.agreement for result in results]
    if not states:
        return "not_run"
    if all(state == "not_run" for state in states):
        return "not_run"
    if all(state in ("failed", "not_run") for state in states):
        return "failed"
    if any(state in ("failed", "not_run") for state in states):
        return "partial"
    if all(state == "evaluated" for state in states):
        return "evaluated"
    if all(state == "inconclusive" for state in states):
        return "inconclusive"
    return "partial"


def _acceptance_rollup(results: Sequence[ValidationDatasetResult]) -> AcceptanceStatus:
    outcomes = [outcome for result in results for outcome in result.acceptance]
    if not outcomes:
        return "not_specified"
    if any(outcome.status == "not_met" for outcome in outcomes):
        return "not_met"
    if any(outcome.status == "indeterminate" for outcome in outcomes):
        return "indeterminate"
    if all(outcome.status == "met" for outcome in outcomes):
        return "met"
    return "not_specified"


def _independence_rollup(results: Sequence[ValidationDatasetResult]) -> IndependenceStatus:
    states = [result.independence.status for result in results]
    if not states:
        return "unknown"
    if any(state == "violated" for state in states):
        return "violated"
    if all(state == "verified" for state in states):
        return "verified"
    if all(state == "unknown" for state in states):
        return "unknown"
    if all(state == "declared_only" for state in states):
        return "declared_only"
    return "partially_verified"


def validate(
    config: ValidationConfig,
    *,
    schema: ModelSchema,
    calibration: CalibrationResult,
    datasets: Mapping[str, Dataset],
    calibration_dataset: Dataset,
    baseline: Mapping[str, Any] | None = None,
    runner: Runner | None = None,
    cancel_event: threading.Event | None = None,
    spec_hash: str = "",
    environment: dict[str, Any] | None = None,
) -> ValidationResult:
    """Run a frozen-parameter validation over every configured dataset."""
    if config.data_role != "validation":
        raise ValidationConfigError(f"unsupported data_role {config.data_role!r}")
    baseline = dict(baseline or {})
    frozen = resolve_validation(config, schema, calibration, baseline)
    driver = _Driver(
        config=config,
        schema=schema,
        calibration=calibration,
        calibration_dataset=calibration_dataset,
        datasets=datasets,
        frozen=frozen,
        baseline=baseline,
        runner=runner,
        spec_hash=spec_hash,
        environment=environment if environment is not None else environment_fingerprint(),
        cancel_event=cancel_event,
    )
    return driver.run()


def validate_for_experiment(
    experiment_id: str,
    store: Any,
    config: ValidationConfig,
    *,
    runner: Runner | None = None,
    cancel_event: threading.Event | None = None,
) -> ValidationResult:
    """Run a validation for a stored experiment, resolving its persisted calibration."""
    from drw.calibration_store import CalibrationStore
    from drw.dataset_store import DatasetStore
    from drw.models.registry import build_model

    if config.experiment_id != experiment_id:
        raise ValidationConfigError(
            f"config.experiment_id {config.experiment_id!r} does not match {experiment_id!r}"
        )
    loaded = store.load(experiment_id)  # KeyError -> not found
    spec = ExperimentSpec.model_validate(loaded["spec"])
    schema = build_model(spec.model_ref.model_id).describe()

    calibrations = CalibrationStore(store.root)
    calibration = calibrations.load(config.calibration.calibration_id)  # KeyError -> not found
    if calibration.result_hash != config.calibration.result_hash:
        raise ValidationConfigError("calibration_hash_mismatch")

    dataset_store = DatasetStore(store.root)
    datasets = {
        item.dataset.dataset_id: dataset_store.load(item.dataset.dataset_id)
        for item in config.datasets
    }
    calibration_dataset = dataset_store.load(calibration.config.dataset.dataset_id)
    spec_hash = loaded["results"].get("spec_hash") or spec.content_hash()
    return validate(
        config,
        schema=schema,
        calibration=calibration,
        datasets=datasets,
        calibration_dataset=calibration_dataset,
        baseline=dict(spec.baseline),
        runner=runner,
        cancel_event=cancel_event,
        spec_hash=spec_hash,
    )
