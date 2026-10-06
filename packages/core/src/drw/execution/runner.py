"""SCI-005: the deterministic local execution engine.

The runner turns a validated :class:`ExperimentSpec` into a sequence of
immutable :class:`RunRecord` objects:

* the baseline is always run first and acts as the frozen reference,
* the design matrix from :mod:`drw.numerics.sampling` supplies the variants,
* every run gets a deterministic id and seed,
* failed runs are preserved (a retry creates a new *attempt*, never a mutation).

Execution is local. By default each run is executed in an **isolated child
process** so the wall-clock timeout is hard-enforced (``isolation="subprocess"``,
see ADR-0005); ``isolation="in_process"`` is the legacy fast path that does not
enforce the timeout. No queue or distributed infrastructure is involved.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from drw.adapter import ModelAdapter
from drw.execution.context import RunContext
from drw.execution.environment import environment_fingerprint
from drw.execution.isolation import SubprocessExecutor
from drw.execution.result import ExperimentResult
from drw.numerics.alignment import AlignmentError
from drw.numerics.delta import Comparison, compare_run
from drw.numerics.sampling import expand_design
from drw.schema.experiment import (
    ExperimentSpec,
    dedupe_diagnostics,
    estimate_run_count,
    validate_experiment,
)
from drw.schema.result import (
    Diagnostic,
    ModelResult,
    RunRecord,
    RunStatus,
    allowed_run_transition,
)

__all__ = ["ExperimentValidationError", "Runner"]


class ExperimentValidationError(ValueError):
    """Raised when a spec fails deterministic validation and must not execute."""

    def __init__(self, diagnostics: tuple[Diagnostic, ...]) -> None:
        self.diagnostics = tuple(d for d in diagnostics if d.level == "error")
        message = "; ".join(d.message for d in self.diagnostics) or "invalid experiment"
        super().__init__(message)


def _utcnow() -> str:
    return datetime.now(UTC).isoformat()


def _scalar_metrics(result: ModelResult) -> dict[str, float]:
    return {
        name: float(value.values)
        for name, value in result.outputs.items()
        if value.kind == "scalar"
    }


def _first_error(diagnostics: tuple[Diagnostic, ...]) -> str | None:
    for diagnostic in diagnostics:
        if diagnostic.level == "error":
            return diagnostic.message
    return None


class Runner:
    """Execute experiments against a model adapter."""

    def __init__(
        self,
        adapter: ModelAdapter | None = None,
        executor: SubprocessExecutor | None = None,
    ) -> None:
        self._adapter = adapter
        self._executor = executor or SubprocessExecutor()

    # -- adapter / isolation resolution ------------------------------------

    def _resolve_adapter(self, spec: ExperimentSpec) -> ModelAdapter:
        if self._adapter is not None:
            return self._adapter
        # Imported lazily so the runner has no hard dependency on the registry.
        from drw.models.registry import build_model

        return build_model(spec.model_ref.model_id)

    def _resolve_isolation(
        self, spec: ExperimentSpec, schema
    ) -> tuple[str, tuple[Diagnostic, ...]]:
        """Decide the process boundary and disclose any downgrade.

        A caller-supplied adapter instance cannot be reconstructed in a child
        process, and a model that is not resolvable by id cannot be built there
        either, so both cases downgrade to in-process **with a warning**.
        """
        requested = spec.execution.isolation
        if self._adapter is not None:
            if requested == "subprocess":
                return "in_process", (
                    Diagnostic(
                        level="warning",
                        code="isolation_downgraded",
                        message=(
                            "a custom adapter instance was provided; running in-process, "
                            "so timeout_s is not enforced"
                        ),
                    ),
                )
            return "in_process", ()

        from drw.models.registry import registry

        if spec.model_ref.model_id not in registry:
            if requested == "subprocess":
                return "in_process", (
                    Diagnostic(
                        level="warning",
                        code="isolation_downgraded",
                        message=(
                            f"model {spec.model_ref.model_id!r} is not resolvable by id in the "
                            "registry; running in-process, so timeout_s is not enforced"
                        ),
                    ),
                )
            return "in_process", ()
        return requested, ()

    # -- public API ---------------------------------------------------------

    def run(
        self,
        spec: ExperimentSpec,
        *,
        experiment_id: str | None = None,
        out_dir: str | Path | None = None,
        cancel_event: threading.Event | None = None,
        on_run: Callable[[int, int, RunRecord], None] | None = None,
    ) -> ExperimentResult:
        adapter = self._resolve_adapter(spec)
        schema = adapter.describe()

        diagnostics = validate_experiment(spec, schema)
        if any(d.level == "error" for d in diagnostics):
            raise ExperimentValidationError(diagnostics)

        isolation, isolation_diagnostics = self._resolve_isolation(spec, schema)
        estimate = estimate_run_count(spec)
        environment = environment_fingerprint()
        spec_hash = spec.content_hash()
        model_hash = schema.content_hash()
        resolved_id = experiment_id or f"exp-{spec_hash[:12]}"

        design = expand_design(spec, schema)

        started_at = _utcnow()
        baseline_inputs = self._complete_inputs(spec, schema)
        total_runs = 1 + len(design.samples)

        runs: list[RunRecord] = []
        baseline = self._run_one(
            adapter,
            baseline_inputs,
            spec,
            schema,
            run_id=f"{resolved_id}-r0000",
            experiment_id=resolved_id,
            label="baseline",
            seed=spec.sampling.seed,
            environment=environment,
            isolation=isolation,
            cancel_event=cancel_event,
        )
        runs.append(baseline)
        if on_run is not None:
            on_run(1, total_runs, baseline)

        for index, sample in enumerate(design.samples, start=1):
            variant_inputs = dict(baseline_inputs)
            variant_inputs.update(sample)
            record = self._run_one(
                adapter,
                variant_inputs,
                spec,
                schema,
                run_id=f"{resolved_id}-r{index:04d}",
                experiment_id=resolved_id,
                label="variant",
                seed=spec.sampling.seed + index,
                environment=environment,
                isolation=isolation,
                cancel_event=cancel_event,
            )
            runs.append(record)
            if on_run is not None:
                on_run(1 + index, total_runs, record)

        comparisons, analysis_diagnostics = self._analyse(spec, runs)
        warnings = dedupe_diagnostics(
            (
                *diagnostics,
                *isolation_diagnostics,
                *design.warnings,
                *estimate.warnings,
                *analysis_diagnostics,
            )
        )

        uncertainty = None
        if any(analysis.method == "uncertainty" for analysis in spec.analyses):
            from drw.uncertainty import compute_uncertainty

            uncertainty = compute_uncertainty(schema, spec, runs[1:])

        result = ExperimentResult(
            experiment_id=resolved_id,
            spec=spec,
            schema=schema,
            model_ref=spec.model_ref,
            estimate=estimate,
            spec_hash=spec_hash,
            model_hash=model_hash,
            isolation=isolation,
            environment=environment,
            runs=runs,
            comparisons=comparisons,
            warnings=warnings,
            started_at=started_at,
            finished_at=_utcnow(),
            uncertainty=uncertainty,
        )
        return result

    def retry(
        self,
        original: RunRecord,
        spec: ExperimentSpec,
        *,
        cancel_event: threading.Event | None = None,
    ) -> RunRecord:
        """Re-execute ``original`` as a new attempt linked to the original record.

        The original record is never mutated (RUN-001).
        """
        adapter = self._resolve_adapter(spec)
        schema = adapter.describe()
        isolation, _ = self._resolve_isolation(spec, schema)
        environment = environment_fingerprint()
        retried = self._run_one(
            adapter,
            dict(original.inputs),
            spec,
            schema,
            run_id=f"{original.run_id}-a{original.attempt + 1}",
            experiment_id=original.experiment_id,
            label=original.label,
            seed=original.seed or 0,
            environment=environment,
            isolation=isolation,
            cancel_event=cancel_event,
        )
        retried.attempt = original.attempt + 1
        retried.parent_run_id = original.run_id
        return retried

    # -- internals ----------------------------------------------------------

    @staticmethod
    def _complete_inputs(spec: ExperimentSpec, schema) -> dict[str, object]:
        inputs: dict[str, object] = {}
        for param in schema.parameters:
            if param.name in spec.baseline:
                inputs[param.name] = spec.baseline[param.name]
            elif param.nominal is not None:
                inputs[param.name] = param.nominal
        return inputs

    @staticmethod
    def _advance(record: RunRecord, target: RunStatus) -> None:
        """Apply a lifecycle transition, enforcing the state machine."""
        if not allowed_run_transition(record.status, target):
            raise RuntimeError(f"illegal run transition {record.status} -> {target}")
        record.status = target

    def _run_one(
        self,
        adapter: ModelAdapter,
        inputs: dict[str, object],
        spec: ExperimentSpec,
        schema,
        *,
        run_id: str,
        experiment_id: str,
        label: str,
        seed: int,
        environment: dict[str, object],
        isolation: str,
        cancel_event: threading.Event | None,
    ) -> RunRecord:
        if cancel_event is not None and cancel_event.is_set():
            return self._cancelled_record(
                inputs,
                spec,
                run_id=run_id,
                experiment_id=experiment_id,
                label=label,
                seed=seed,
                environment=environment,
                isolation=isolation,
            )

        context = RunContext(
            run_id=run_id,
            experiment_id=experiment_id,
            seed=seed,
            timeout_s=spec.execution.timeout_s,
            solver=spec.execution.solver,
            rtol=spec.verification.rtol,
            atol=spec.verification.atol,
            environment_fingerprint=environment,
        )
        record = RunRecord(
            run_id=run_id,
            experiment_id=experiment_id,
            label=label,
            status=RunStatus.QUEUED,
            model_ref=spec.model_ref,
            inputs=dict(inputs),
            seed=seed,
            environment=environment,
            isolation=isolation,
            started_at=_utcnow(),
        )
        self._advance(record, RunStatus.RUNNING)

        if isolation == "subprocess":
            outcome = self._executor.execute(
                spec.model_ref.model_id, inputs, context, cancel_event=cancel_event
            )
            record.duration_s = outcome.duration_s
            record.timed_out = outcome.timed_out
            record.result = outcome.result
            record.diagnostics = outcome.diagnostics
            if outcome.ok:
                record.metrics = _scalar_metrics(outcome.result)
                self._advance(record, RunStatus.SUCCEEDED)
            else:
                record.error = _first_error(outcome.diagnostics) or "isolated run failed"
                self._advance(record, RunStatus.FAILED)
        else:
            start = time.perf_counter()
            try:
                result = adapter.run(inputs, context)
            except Exception as exc:
                record.diagnostics = (
                    Diagnostic(
                        level="error",
                        code="adapter_exception",
                        message=f"{type(exc).__name__}: {exc}",
                    ),
                )
                record.error = record.diagnostics[0].message
            else:
                record.result = result
                record.diagnostics = result.diagnostics
                if result.ok:
                    record.metrics = _scalar_metrics(result)
                    self._advance(record, RunStatus.SUCCEEDED)
                else:
                    record.error = _first_error(result.diagnostics) or "model reported failure"
            if record.status == RunStatus.RUNNING:
                self._advance(record, RunStatus.FAILED)
            record.duration_s = time.perf_counter() - start

        record.finished_at = _utcnow()
        return record

    def _cancelled_record(
        self,
        inputs: dict[str, object],
        spec: ExperimentSpec,
        *,
        run_id: str,
        experiment_id: str,
        label: str,
        seed: int,
        environment: dict[str, object],
        isolation: str,
    ) -> RunRecord:
        record = RunRecord(
            run_id=run_id,
            experiment_id=experiment_id,
            label=label,
            status=RunStatus.QUEUED,
            model_ref=spec.model_ref,
            inputs=dict(inputs),
            seed=seed,
            environment=environment,
            isolation=isolation,
            error="run cancelled",
            diagnostics=(
                Diagnostic(
                    level="warning",
                    code="cancelled",
                    message="run was not started because the experiment was cancelled",
                ),
            ),
        )
        self._advance(record, RunStatus.FAILED)
        record.started_at = _utcnow()
        record.finished_at = record.started_at
        return record

    @staticmethod
    def _analyse(
        spec: ExperimentSpec, runs: list[RunRecord]
    ) -> tuple[list[Comparison], tuple[Diagnostic, ...]]:
        baseline = runs[0]
        if not baseline.succeeded or baseline.result is None:
            return [], ()
        # A single comparison already carries both the absolute delta and the
        # relative change, so declaring both methods yields one artifact per
        # (variant, output) rather than duplicate rows.
        requested = [a.method for a in spec.analyses if a.method in ("delta", "relative_delta")]
        method_label = "+".join(dict.fromkeys(requested)) or "delta"
        outputs = spec.outputs or None
        baseline_outputs = set(baseline.result.output_names())

        comparisons: list[Comparison] = []
        diagnostics: list[Diagnostic] = []
        for run in runs[1:]:
            if not run.succeeded or run.result is None:
                # Failed runs remain visible in history but cannot be compared.
                continue
            run_outputs = set(run.result.output_names())
            if outputs:
                for name in outputs:
                    if name not in baseline_outputs or name not in run_outputs:
                        diagnostics.append(
                            Diagnostic(
                                level="warning",
                                code="output_missing_for_comparison",
                                message=(
                                    f"output {name!r} is missing from {run.run_id}; it was "
                                    "skipped in the comparison"
                                ),
                            )
                        )
            try:
                comparisons.extend(
                    compare_run(
                        baseline,
                        run,
                        outputs=outputs,
                        method=method_label,
                        strategy="exact",
                        relative_epsilon=spec.verification.relative_epsilon,
                    )
                )
            except AlignmentError as exc:
                diagnostics.append(
                    Diagnostic(
                        level="error",
                        code="comparison_failed",
                        message=f"could not compare {run.run_id}: {exc}",
                    )
                )
        return comparisons, tuple(diagnostics)
