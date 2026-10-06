"""Calibration execution loop (M12B, Phase C).

The loop is the orchestration layer. It is **strictly serial** and owns the hard
evaluation budget. For each candidate it:

1. validates the parameter vector,
2. builds a throwaway single-run :class:`~drw.schema.experiment.ExperimentSpec`
   whose baseline is the candidate,
3. executes it through the **existing** :class:`~drw.execution.runner.Runner`,
4. compares the run to the dataset with **M12A** ``evaluate_run``,
5. extracts the objective through the :class:`ObjectiveOracle`,
6. records the candidate and updates the optimizer.

It never executes a model directly, never re-implements comparison, never invents
an initial value, never widens bounds and never turns a failure into a scientific
number (+inf is only the optimizer interface sentinel).
"""

from __future__ import annotations

import math
import threading
import time
from collections import Counter
from collections.abc import Mapping, Sequence
from typing import Any

import scipy

from drw.calibration.objective import ObjectiveOracle
from drw.calibration.optimizers import (
    CalibrationBudgetExceeded,
    CalibrationCancelled,
    CalibrationMaxFailed,
    CalibrationStop,
    CalibrationWallTimeExceeded,
    OptimizerOutcome,
    RandomSearchGenerator,
    build_optimizer,
)
from drw.evaluation import evaluate_run
from drw.execution.environment import environment_fingerprint, fingerprint_hash
from drw.execution.runner import ExperimentValidationError, Runner
from drw.observations import science_hash
from drw.schema.calibration import (
    DEFAULT_DISCLOSURE,
    CalibrationCandidateSummary,
    CalibrationConfig,
    CalibrationConfigError,
    CalibrationObjective,
    CalibrationProvenance,
    CalibrationResult,
    compute_calibration_hash,
    compute_result_hash,
    resolve_calibration,
)
from drw.schema.experiment import ExecutionSpec, ExperimentSpec, VerificationSpec
from drw.schema.model import ModelSchema
from drw.schema.observation import Dataset
from drw.schema.result import Diagnostic
from drw.schema.serialization import content_hash

__all__ = ["calibrate", "calibrate_for_experiment"]


def _hint(report: Any) -> dict[str, Any]:
    return {
        "mode": None,  # filled by the caller
        "method": report.method,
        "verdict": report.verdict,
        "inconclusive": report.inconclusive,
        "numerical_rank": report.numerical_rank,
        "dimensions": report.dimensions,
        "condition_number": report.condition_number,
        "factors": list(report.factors),
        "reasons": list(report.reasons),
        "evaluations_completed": report.evaluations_completed,
        "note": report.note,
    }


class _Driver:
    """One serial calibration search."""

    def __init__(
        self,
        *,
        config: CalibrationConfig,
        schema: ModelSchema,
        dataset: Dataset,
        baseline: Mapping[str, Any],
        runner: Runner | None,
        spec_hash: str,
        environment: dict[str, Any],
        cancel_event: threading.Event | None,
        journal: Any | None,
    ) -> None:
        self.config = config
        self.schema = schema
        self.dataset = dataset
        self.runner: Any = runner if runner is not None else Runner()
        self.cancel_event = cancel_event
        self.journal = journal
        self.resolved = resolve_calibration(config, schema, dict(baseline))
        self.oracle = ObjectiveOracle(config.objective, config.mapping)
        self.spec_hash = spec_hash
        self.environment = environment
        self.environment_hash = fingerprint_hash(environment)
        self.candidates: list[CalibrationCandidateSummary] = []
        self.count = 0
        self.completed = 0
        self.invalid = 0
        self._start = time.monotonic()

    # -- budget / stop checks ----------------------------------------------

    def _check_stop(self) -> None:
        if self.cancel_event is not None and self.cancel_event.is_set():
            raise CalibrationCancelled
        if time.monotonic() - self._start > self.config.budget.max_wall_seconds:
            raise CalibrationWallTimeExceeded
        if self.count >= self.config.budget.max_evaluations:
            raise CalibrationBudgetExceeded

    # -- candidate evaluation ----------------------------------------------

    def _attempt(self, theta: Sequence[float]) -> float | None:
        self._check_stop()
        candidate = self._evaluate(theta)
        self.candidates.append(candidate)
        if candidate.objective is None:
            self.invalid += 1
        if self.journal is not None:
            self.journal.append(
                "candidate_completed",
                index=candidate.index,
                objective=candidate.objective,
                failure=candidate.failure,
                run_status=candidate.run_status,
            )
        max_failed = self.config.budget.max_failed
        if max_failed is not None and self.invalid >= max_failed:
            raise CalibrationMaxFailed
        return candidate.objective

    def _objective(self, theta: Sequence[float]) -> float:
        return self.oracle.sentinel(self._attempt(list(theta)))

    def _evaluate(self, theta: Sequence[float]) -> CalibrationCandidateSummary:
        index = self.count
        self.count += 1
        parameters = {name: float(value) for name, value in zip(self.resolved.names, theta, strict=True)}

        for value, (lower, upper) in zip(theta, self.resolved.bounds, strict=True):
            if not math.isfinite(float(value)) or value < lower or value > upper:
                return CalibrationCandidateSummary(
                    index=index, parameters=parameters, failure="invalid_parameter_state"
                )

        inputs: dict[str, Any] = {**self.resolved.fixed, **parameters}
        spec = self._spec(inputs)
        try:
            experiment = self.runner.run(spec, cancel_event=self.cancel_event)
        except ExperimentValidationError as exc:
            return CalibrationCandidateSummary(
                index=index,
                parameters=parameters,
                failure="validation_error",
                diagnostics=list(exc.diagnostics),
            )
        run = experiment.runs[0]
        self.completed += 1
        evaluation = evaluate_run(
            run,
            schema=self.schema,
            dataset=self.dataset,
            mapping=self.config.mapping,
            config=self.config.evaluation,
            spec_hash=experiment.spec_hash,
            environment_hash=fingerprint_hash(experiment.environment),
            model_hash=experiment.model_hash,
        )
        outcome = self.oracle.from_evaluation(evaluation)
        return CalibrationCandidateSummary(
            index=index,
            parameters=parameters,
            run_id=run.run_id,
            run_status=run.status.value,
            evaluation_hash=evaluation.evaluation_hash,
            objective=outcome.value,
            failure=outcome.failure,
            n_used=outcome.n_used,
            n_excluded=outcome.n_excluded,
            duration_s=run.duration_s,
            diagnostics=list(evaluation.diagnostics) if outcome.value is None else [],
        )

    def _spec(self, inputs: Mapping[str, Any]) -> ExperimentSpec:
        template = self.config.execution
        return ExperimentSpec(
            name="calibration",
            hypothesis="Calibration candidate evaluation.",
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

    # -- search -------------------------------------------------------------

    def _search(self) -> tuple[OptimizerOutcome | None, CalibrationStop | None]:
        if self.config.optimizer.name == "random_search":
            generator = RandomSearchGenerator(seed=self.config.seed)
            try:
                for theta in generator.proposals(
                    self.resolved.bounds, self.config.budget.max_evaluations
                ):
                    self._attempt(theta)
            except CalibrationStop as stop:
                return None, stop
            return OptimizerOutcome(False, "max_evaluations", self.count, "random search"), None
        try:
            adapter = build_optimizer(self.config.optimizer, seed=self.config.seed)
            outcome = adapter.minimize(
                x0=self.resolved.initial,
                bounds=self.resolved.bounds,
                func=self._objective,
                max_iterations=self.config.optimizer.max_iterations,
            )
            return outcome, None
        except CalibrationStop as stop:
            return None, stop
        except Exception as exc:  # an optimizer fault is not a scientific result
            return (
                OptimizerOutcome(False, "optimizer_failure", self.count, f"{type(exc).__name__}: {exc}"),
                None,
            )

    # -- identifiability (advisory) ----------------------------------------

    def _identifiability(self) -> dict[str, Any] | None:
        mode = self.config.identifiability
        if mode == "off":
            return None
        from drw.identifiability import identifiability

        inputs = {
            **self.resolved.fixed,
            **{item.name: item.initial for item in self.resolved.free},
        }
        report = identifiability(
            self.schema,
            baseline=inputs,
            factors=self.resolved.names,
            outputs=(self.oracle.pair.output,),
            runner=self.runner if isinstance(self.runner, Runner) else None,
        )
        hint = _hint(report)
        hint["mode"] = mode
        return hint

    # -- result -------------------------------------------------------------

    def run(self) -> CalibrationResult:
        hint = self._identifiability()
        if (
            hint is not None
            and self.config.identifiability == "require"
            and hint["verdict"] != "well-conditioned"
        ):
            return self._finalize(
                status="invalid",
                stop_reason="identifiability_required",
                converged=False,
                iterations=0,
                hint=hint,
            )

        outcome, stop = self._search()
        status, stop_reason, converged, iterations = self._status(outcome, stop)
        return self._finalize(
            status=status,
            stop_reason=stop_reason,
            converged=converged,
            iterations=iterations,
            hint=hint,
        )

    def _status(
        self, outcome: OptimizerOutcome | None, stop: CalibrationStop | None
    ) -> tuple[str, str, bool, int]:
        has_best = any(candidate.valid for candidate in self.candidates)
        if isinstance(stop, CalibrationCancelled):
            return "cancelled", "cancelled", False, self.count
        if isinstance(stop, CalibrationWallTimeExceeded):
            reason = "max_wall_seconds"
        elif isinstance(stop, CalibrationBudgetExceeded):
            reason = "max_evaluations"
        elif isinstance(stop, CalibrationMaxFailed):
            reason = "max_failed"
        elif outcome is not None:
            reason = outcome.stop_reason
        else:  # pragma: no cover - defensive
            reason = "optimizer_failure"

        if not has_best:
            if reason == "optimizer_converged":
                reason = "all_candidates_failed"
            return "failed", reason, False, (outcome.iterations if outcome else self.count)
        if outcome is not None and outcome.converged and stop is None:
            return "converged", "optimizer_converged", True, outcome.iterations
        if reason in ("max_evaluations", "max_wall_seconds"):
            return "budget_exhausted", reason, False, (outcome.iterations if outcome else self.count)
        return "not_converged", reason, False, (outcome.iterations if outcome else self.count)

    def _finalize(
        self,
        *,
        status: str,
        stop_reason: str,
        converged: bool,
        iterations: int,
        hint: dict[str, Any] | None,
    ) -> CalibrationResult:
        valid = [candidate for candidate in self.candidates if candidate.valid]
        best = min(valid, key=lambda item: item.objective) if valid else None

        note = DEFAULT_DISCLOSURE
        if hint is not None and hint["verdict"] != "well-conditioned":
            note += (
                " An advisory identifiability pre-check flagged this parameter set as "
                f"{hint['verdict']}: the reported point estimate may not be unique."
            )

        objective = CalibrationObjective(
            metric=self.config.objective.metric,
            observation=self.oracle.pair.observation,
            output=self.oracle.pair.output,
            aggregation=self.config.objective.aggregation,
            direction=self.config.objective.direction,
            value=best.objective if best is not None else None,
        )
        provenance = CalibrationProvenance(
            experiment_id=self.config.experiment_id,
            spec_hash=self.spec_hash,
            model_id=self.schema.model_id,
            model_hash=self.schema.content_hash(),
            environment_hash=self.environment_hash,
            scipy_version=scipy.__version__,
            dataset_content_hash=self.dataset.content_hash,
            dataset_science_hash=science_hash(self.dataset),
            mapping_hash=content_hash(self.config.mapping),
            evaluation_config_hash=content_hash(self.config.evaluation),
            evaluation_hash=best.evaluation_hash if best is not None else None,
        )
        result = CalibrationResult(
            calibration_hash=compute_calibration_hash(self.config),
            result_hash="",
            experiment_id=self.config.experiment_id,
            model_ref=self.config.model_ref,
            config=self.config,
            status=status,  # type: ignore[arg-type]
            stop_reason=stop_reason,  # type: ignore[arg-type]
            converged=converged,
            best=best,
            objective=objective,
            evaluations_requested=self.config.budget.max_evaluations,
            evaluations_completed=self.completed,
            evaluations_invalid=self.invalid,
            iterations=iterations,
            wall_seconds=time.monotonic() - self._start,
            identifiability=hint,
            history=self.candidates,
            diagnostics=self._diagnostics(status, stop_reason, hint),
            provenance=provenance,
            note=note,
        )
        return result.model_copy(update={"result_hash": compute_result_hash(result)})

    def _diagnostics(
        self, status: str, stop_reason: str, hint: dict[str, Any] | None
    ) -> list[Diagnostic]:
        diagnostics: list[Diagnostic] = []
        if hint is not None and hint["verdict"] != "well-conditioned":
            diagnostics.append(
                Diagnostic(
                    level="warning",
                    code="identifiability_warning",
                    message=(
                        f"identifiability pre-check verdict {hint['verdict']!r}; the reported "
                        "point estimate may not be unique"
                    ),
                )
            )
        failures = Counter(
            candidate.failure for candidate in self.candidates if candidate.failure is not None
        )
        if failures:
            diagnostics.append(
                Diagnostic(
                    level="warning",
                    code="invalid_candidates",
                    message=(
                        f"{self.invalid} candidate(s) produced no usable objective: "
                        + ", ".join(f"{code}={count}" for code, count in sorted(failures.items()))
                    ),
                )
            )
        if status == "failed":
            diagnostics.append(
                Diagnostic(
                    level="error",
                    code=stop_reason,
                    message="calibration produced no usable best candidate",
                )
            )
        elif status == "not_converged":
            diagnostics.append(
                Diagnostic(
                    level="warning",
                    code="not_converged",
                    message="the optimizer stopped before reporting convergence",
                )
            )
        return diagnostics


def calibrate(
    config: CalibrationConfig,
    *,
    schema: ModelSchema,
    dataset: Dataset,
    baseline: Mapping[str, Any],
    runner: Runner | None = None,
    cancel_event: threading.Event | None = None,
    journal: Any | None = None,
    spec_hash: str = "",
    environment: dict[str, Any] | None = None,
) -> CalibrationResult:
    """Run a calibration search (serial, bounded, deterministic given a seed)."""
    if config.data_role != "calibration":
        raise CalibrationConfigError(f"unsupported data_role {config.data_role!r}")
    driver = _Driver(
        config=config,
        schema=schema,
        dataset=dataset,
        baseline=baseline,
        runner=runner,
        spec_hash=spec_hash,
        environment=environment if environment is not None else environment_fingerprint(),
        cancel_event=cancel_event,
        journal=journal,
    )
    return driver.run()


def calibrate_for_experiment(
    experiment_id: str,
    store: Any,
    config: CalibrationConfig,
    *,
    runner: Runner | None = None,
    cancel_event: threading.Event | None = None,
    journal: Any | None = None,
) -> CalibrationResult:
    """Run a calibration for a stored experiment (read-only w.r.t. the experiment)."""
    from drw.dataset_store import DatasetStore
    from drw.models.registry import build_model

    if config.experiment_id != experiment_id:
        raise CalibrationConfigError(
            f"config.experiment_id {config.experiment_id!r} does not match {experiment_id!r}"
        )
    loaded = store.load(experiment_id)  # KeyError -> not found
    spec = ExperimentSpec.model_validate(loaded["spec"])
    schema = build_model(spec.model_ref.model_id).describe()
    dataset = DatasetStore(store.root).load(config.dataset.dataset_id)
    spec_hash = loaded["results"].get("spec_hash") or spec.content_hash()
    return calibrate(
        config,
        schema=schema,
        dataset=dataset,
        baseline=dict(spec.baseline),
        runner=runner,
        cancel_event=cancel_event,
        journal=journal,
        spec_hash=spec_hash,
    )
