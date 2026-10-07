"""The controlled SI action registry.

SI does **not** call arbitrary internal functions. Every capability that SI can
invoke is a registered :class:`SIAction` with a stable id, a human name, a
description, an input contract, an approval requirement and a deterministic
executor that delegates to an existing DRW capability. Actions that the engine
cannot actually perform are registered as ``supported=False`` and fail closed with
an explanation rather than pretending.

Read-only actions may run without approval; everything that creates or modifies an
artifact requires explicit approval (see :mod:`drw.si.executor`).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from drw.schema.result import Diagnostic
from drw.schema.serialization import to_plain
from drw.schema.si import (
    ActionCategory,
    SIActionPreview,
    SIActionRef,
    SIEffect,
    SIInvestigationState,
)

__all__ = [
    "SIAction",
    "SIActionContext",
    "SIActionError",
    "SIActionOutcome",
    "SIActionRegistry",
    "default_registry",
    "preview_action",
    "registry_metadata",
]

_READ_ONLY_CATEGORY: ActionCategory = "read"


class SIActionError(Exception):
    """A controlled action failure with a stable machine-readable code."""

    def __init__(self, code: str, message: str, *, diagnostics: Any = ()) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.diagnostics = list(diagnostics)


@dataclass(slots=True)
class SIActionOutcome:
    """The structured outcome of executing an action."""

    summary: str
    result: dict[str, Any] = field(default_factory=dict)
    artifacts: dict[str, str] = field(default_factory=dict)
    diagnostics: tuple[Diagnostic, ...] = ()


@dataclass(slots=True)
class SIActionContext:
    """Everything an action executor may read or write.

    The stores are the same durable artifacts the rest of DRW uses; there is no
    SI-only representation of a model, dataset or result.
    """

    store: Any  # drw.store.ExperimentStore
    project_id: str
    investigation_id: str
    model_id: str | None = None
    state: SIInvestigationState | None = None
    datasets: Any = None  # drw.dataset_store.DatasetStore
    calibrations: Any = None  # drw.calibration_store.CalibrationStore
    validations: Any = None  # drw.validation_store.ValidationStore
    model_specs: Any = None  # drw.model_spec_store.ModelSpecStore
    models: Any = None  # drw.model_store.ModelStore
    simulations: Any = None  # drw.simulation_store.SimulationStore


Validator = Callable[
    [dict[str, Any], SIActionContext], tuple[dict[str, Any], tuple[Diagnostic, ...]]
]
Executor = Callable[[dict[str, Any], SIActionContext], SIActionOutcome]


@dataclass(slots=True)
class SIAction:
    """One registered capability."""

    action_id: str
    name: str
    description: str
    category: ActionCategory
    read_only: bool
    effects: SIEffect = "none"
    supported: bool = True
    limitations: tuple[str, ...] = ()
    validate: Validator | None = None
    execute: Executor | None = None

    @property
    def requires_approval(self) -> bool:
        return not self.read_only

    def ref(self) -> SIActionRef:
        return SIActionRef(
            action_id=self.action_id,
            name=self.name,
            description=self.description,
            category=self.category,
            read_only=self.read_only,
            requires_approval=self.requires_approval,
            supported=self.supported,
            effects=self.effects,
            limitations=self.limitations,
        )

    def preview(self, inputs: dict[str, Any], ctx: SIActionContext) -> SIActionPreview:
        normalized: dict[str, Any] = dict(inputs)
        diagnostics: tuple[Diagnostic, ...] = ()
        warnings: list[str] = []
        if self.validate is not None:
            try:
                normalized, diagnostics = self.validate(inputs, ctx)
            except SIActionError as exc:
                diagnostics = (
                    Diagnostic(level="error", code=exc.code, message=exc.message),
                )
        if not self.supported:
            warnings.append(
                self.limitations[0] if self.limitations else "Not supported yet."
            )
        summary = _preview_summary(self, normalized)
        return SIActionPreview(
            action_id=self.action_id,
            name=self.name,
            description=self.description,
            read_only=self.read_only,
            requires_approval=self.requires_approval,
            supported=self.supported,
            effects=self.effects,
            inputs=normalized,
            input_diagnostics=diagnostics,
            summary=summary,
            warnings=tuple(warnings),
        )


class SIActionRegistry:
    """A registry of the capabilities SI may orchestrate."""

    def __init__(self, actions: list[SIAction] | None = None) -> None:
        self._actions: dict[str, SIAction] = {}
        for action in actions or []:
            self.register(action)

    def register(self, action: SIAction) -> None:
        if action.action_id in self._actions:
            raise ValueError(f"duplicate SI action id {action.action_id!r}")
        self._actions[action.action_id] = action

    def get(self, action_id: str) -> SIAction:
        try:
            return self._actions[action_id]
        except KeyError as exc:
            raise SIActionError(
                "unknown_action",
                f"no SI action {action_id!r} is registered; available: {sorted(self._actions)}",
            ) from exc

    def has(self, action_id: str) -> bool:
        return action_id in self._actions

    def list(self) -> list[SIAction]:
        return [self._actions[key] for key in sorted(self._actions)]

    def refs(self) -> list[SIActionRef]:
        return [action.ref() for action in self.list()]

    def preview(
        self, action_id: str, inputs: dict[str, Any], ctx: SIActionContext
    ) -> SIActionPreview:
        return self.get(action_id).preview(inputs, ctx)


def preview_action(
    registry: SIActionRegistry,
    action_id: str,
    inputs: dict[str, Any],
    ctx: SIActionContext,
) -> SIActionPreview:
    return registry.preview(action_id, inputs, ctx)


# ---------------------------------------------------------------------------
# Input helpers
# ---------------------------------------------------------------------------


def _required_str(params: dict[str, Any], key: str) -> str:
    value = params.get(key)
    if not isinstance(value, str) or not value:
        raise SIActionError("bad_request", f"input {key!r} must be a non-empty string")
    return value


def _optional_str(params: dict[str, Any], key: str) -> str | None:
    value = params.get(key)
    if value is None:
        return None
    if not isinstance(value, str) or not value:
        raise SIActionError(
            "bad_request", f"input {key!r} must be a non-empty string when supplied"
        )
    return value


def _optional_str_list(params: dict[str, Any], key: str) -> list[str] | None:
    value = params.get(key)
    if value is None:
        return None
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise SIActionError("bad_request", f"input {key!r} must be a list of strings")
    return list(value)


def _resolve_experiment_id(params: dict[str, Any], ctx: SIActionContext) -> str:
    explicit = _optional_str(params, "experiment_id")
    if explicit is not None:
        return explicit
    if ctx.state is not None and ctx.state.experiments:
        return ctx.state.experiments[-1]
    raise SIActionError(
        "bad_request",
        "no experiment is selected; provide 'experiment_id' or run an experiment first",
    )


def _preview_summary(action: SIAction, inputs: dict[str, Any]) -> str:
    if action.read_only:
        target = (
            inputs.get("experiment_id")
            or inputs.get("model_id")
            or inputs.get("dataset_id")
        )
        suffix = f" ({target})" if target else ""
        return f"Read-only: {action.name}{suffix}. No side effects."
    return f"{action.name}: will {action.effects.replace('_', ' ')}. Requires your approval."


def registry_metadata(action: SIAction) -> dict[str, Any]:
    """Return the JSON-safe metadata for one action (used by capabilities)."""
    return to_plain(action.ref())


# ---------------------------------------------------------------------------
# Read-only executors
# ---------------------------------------------------------------------------


def _exec_inspect_project(
    params: dict[str, Any], ctx: SIActionContext
) -> SIActionOutcome:
    project = ctx.store.get_project(ctx.project_id)
    experiments = ctx.store.list(project_id=ctx.project_id)
    datasets = ctx.datasets.list() if ctx.datasets is not None else []
    return SIActionOutcome(
        summary=f"Project {project.get('name')!r}: {len(experiments)} experiment(s), "
        f"{len(datasets)} dataset(s).",
        result={
            "project": to_plain(project),
            "n_experiments": len(experiments),
            "n_datasets": len(datasets),
            "models": sorted(_model_ids()),
        },
    )


def _exec_inspect_investigation(
    params: dict[str, Any], ctx: SIActionContext
) -> SIActionOutcome:
    state = ctx.state
    if state is None:
        raise SIActionError("not_found", "no SI investigation state is available")
    plan = state.current_plan()
    next_step = plan.current_next_step() if plan is not None else None
    return SIActionOutcome(
        summary=f"Investigation {state.investigation_id}: {len(state.experiments)} experiment(s), "
        f"{len(state.datasets)} dataset(s), {len(state.decisions)} decision(s).",
        result={
            "objective": state.objective,
            "hypotheses": list(state.hypotheses),
            "assumptions": list(state.assumptions),
            "models": list(state.models),
            "datasets": list(state.datasets),
            "experiments": list(state.experiments),
            "calibrations": list(state.calibrations),
            "validations": list(state.validations),
            "unresolved_questions": list(state.unresolved_questions),
            "decisions": list(state.decisions),
            "current_plan_id": state.current_plan_id,
            "next_step": to_plain(next_step) if next_step is not None else None,
        },
    )


def _model_ids() -> list[str]:
    from drw.models.registry import list_models

    return list_models()


def _exec_list_models(params: dict[str, Any], ctx: SIActionContext) -> SIActionOutcome:
    from drw.models.registry import model_schemas

    models = [
        {
            "model_id": model_id,
            "version": schema.version,
            "description": schema.description,
            "n_parameters": len(schema.parameters),
            "n_outputs": len(schema.outputs),
        }
        for model_id, schema in sorted(model_schemas().items())
    ]
    return SIActionOutcome(
        summary=f"{len(models)} registered model(s).", result={"models": models}
    )


def _exec_inspect_model(
    params: dict[str, Any], ctx: SIActionContext
) -> SIActionOutcome:
    from drw.capabilities import model_capabilities
    from drw.models.registry import build_model

    model_id = _required_str(params, "model_id")
    schema = build_model(model_id).describe()
    return SIActionOutcome(
        summary=f"Model {model_id} v{schema.version}: {len(schema.parameters)} parameters, "
        f"{len(schema.outputs)} outputs.",
        result={
            "schema": to_plain(schema),
            "model_hash": schema.content_hash(),
            "capabilities": model_capabilities(schema),
        },
    )


def _exec_inspect_capabilities(
    params: dict[str, Any], ctx: SIActionContext
) -> SIActionOutcome:
    from drw.capabilities import model_capabilities
    from drw.models.registry import build_model

    model_id = _required_str(params, "model_id")
    schema = build_model(model_id).describe()
    return SIActionOutcome(
        summary=f"Capabilities for {model_id}.",
        result={"model_id": model_id, "capabilities": model_capabilities(schema)},
    )


def _dataset_summary(ctx: SIActionContext, ref: Any) -> dict[str, Any]:
    from drw.schema.simulation import is_synthetic

    item = to_plain(ref)
    source_kind = None
    synthetic = False
    try:
        provenance = ctx.datasets.provenance(ref.dataset_id)
        source_kind = provenance.source_kind
        synthetic = is_synthetic(provenance)
    except Exception:  # pragma: no cover - provenance is best-effort metadata
        pass
    item["source_kind"] = source_kind
    item["synthetic"] = synthetic
    return item


def _exec_list_datasets(
    params: dict[str, Any], ctx: SIActionContext
) -> SIActionOutcome:
    datasets = [_dataset_summary(ctx, ref) for ref in ctx.datasets.list()]
    n_synthetic = sum(1 for item in datasets if item.get("synthetic"))
    return SIActionOutcome(
        summary=f"{len(datasets)} dataset(s), {n_synthetic} synthetic.",
        result={"datasets": datasets},
    )


def _exec_inspect_dataset(
    params: dict[str, Any], ctx: SIActionContext
) -> SIActionOutcome:
    from drw.schema.simulation import is_synthetic

    dataset_id = _required_str(params, "dataset_id")
    dataset = ctx.datasets.load(dataset_id)
    synthetic = is_synthetic(dataset.provenance)
    return SIActionOutcome(
        summary=f"Dataset {dataset_id} ({dataset.provenance.source_kind}).",
        result={
            "ref": to_plain(ctx.datasets.ref(dataset_id)),
            "dataset": to_plain(dataset),
            "verification": to_plain(ctx.datasets.verify(dataset_id)),
            "synthetic": synthetic,
        },
    )


def _exec_list_experiments(
    params: dict[str, Any], ctx: SIActionContext
) -> SIActionOutcome:
    experiments = ctx.store.list(project_id=ctx.project_id)
    return SIActionOutcome(
        summary=f"{len(experiments)} experiment(s) in this project.",
        result={"experiments": to_plain(experiments)},
    )


def _exec_inspect_experiment(
    params: dict[str, Any], ctx: SIActionContext
) -> SIActionOutcome:
    experiment_id = _required_str(params, "experiment_id")
    loaded = ctx.store.load(experiment_id)
    results = loaded.get("results") or {}
    runs = results.get("runs") or []
    summary = {
        "experiment_id": experiment_id,
        "meta": to_plain(loaded.get("meta") or {}),
        "spec": to_plain(loaded.get("spec") or {}),
        "n_runs": len(runs),
        "n_succeeded": sum(1 for run in runs if run.get("status") == "succeeded"),
        "n_comparisons": len(results.get("comparisons") or []),
        "uncertainty": to_plain(results.get("uncertainty")),
    }
    return SIActionOutcome(
        summary=f"Experiment {experiment_id}: {summary['n_succeeded']}/{summary['n_runs']} runs "
        "succeeded.",
        result=summary,
    )


def _exec_inspect_evidence(
    params: dict[str, Any], ctx: SIActionContext
) -> SIActionOutcome:
    experiment_id = _required_str(params, "experiment_id")
    evidence = ctx.store.evidence(experiment_id)
    files = evidence.get("files") or []
    return SIActionOutcome(
        summary=f"Evidence package for {experiment_id}: {len(files)} artifact(s).",
        result={
            "manifest": to_plain(evidence.get("manifest") or {}),
            "files": to_plain(files),
        },
    )


def _exec_list_calibrations(
    params: dict[str, Any], ctx: SIActionContext
) -> SIActionOutcome:
    items = to_plain(ctx.calibrations.list())
    return SIActionOutcome(
        summary=f"{len(items)} stored calibration(s).", result={"calibrations": items}
    )


def _exec_inspect_calibration(
    params: dict[str, Any], ctx: SIActionContext
) -> SIActionOutcome:
    calibration_id = _required_str(params, "calibration_id")
    result = ctx.calibrations.load(calibration_id)
    return SIActionOutcome(
        summary=f"Calibration {calibration_id}: status {result.status}.",
        result={
            "calibration": to_plain(result),
            "ref": to_plain(ctx.calibrations.ref(calibration_id)),
        },
    )


def _exec_list_validations(
    params: dict[str, Any], ctx: SIActionContext
) -> SIActionOutcome:
    items = to_plain(ctx.validations.list())
    return SIActionOutcome(
        summary=f"{len(items)} stored validation(s).", result={"validations": items}
    )


def _exec_inspect_validation(
    params: dict[str, Any], ctx: SIActionContext
) -> SIActionOutcome:
    validation_id = _required_str(params, "validation_id")
    result = ctx.validations.load(validation_id)
    return SIActionOutcome(
        summary=f"Validation {validation_id}: agreement {result.agreement_status}.",
        result={
            "validation": to_plain(result),
            "ref": to_plain(ctx.validations.ref(validation_id)),
        },
    )


# ---------------------------------------------------------------------------
# Scientific executors (create artifacts; require approval)
# ---------------------------------------------------------------------------


def _load_experiment_spec(params: dict[str, Any], ctx: SIActionContext) -> Any:
    from pydantic import ValidationError as PydanticValidationError

    from drw.models.registry import build_model
    from drw.schema.experiment import ExperimentSpec, validate_experiment

    raw = params.get("spec")
    if not isinstance(raw, dict):
        raise SIActionError(
            "bad_request", "input 'spec' must be an experiment specification object"
        )
    try:
        spec = ExperimentSpec.model_validate(raw)
    except PydanticValidationError as exc:
        raise SIActionError(
            "invalid_spec",
            "the experiment specification is not well formed",
            diagnostics=exc.errors(),
        ) from exc
    schema = build_model(spec.model_ref.model_id).describe()
    problems = validate_experiment(spec, schema)
    if any(d.level == "error" for d in problems):
        raise SIActionError(
            "validation_error",
            "the experiment failed validation and was not executed",
            diagnostics=to_plain(problems),
        )
    return spec, problems


def _validate_experiment_inputs(
    params: dict[str, Any], ctx: SIActionContext
) -> tuple[dict[str, Any], tuple[Diagnostic, ...]]:
    try:
        spec, problems = _load_experiment_spec(params, ctx)
    except SIActionError as exc:
        return dict(params), (
            Diagnostic(level="error", code=exc.code, message=exc.message),
        )
    return {"spec": to_plain(spec)}, tuple(problems)


def _exec_create_experiment(
    params: dict[str, Any], ctx: SIActionContext
) -> SIActionOutcome:
    from drw.execution.runner import Runner

    spec, problems = _load_experiment_spec(params, ctx)
    result = Runner().run(spec)
    ctx.store.save(result, project_id=ctx.project_id)
    n_runs = len(result.runs)
    n_ok = len(result.succeeded_runs)
    return SIActionOutcome(
        summary=f"Ran experiment {result.experiment_id}: {n_ok}/{n_runs} runs succeeded, "
        f"{len(result.comparisons)} comparison(s).",
        result={
            "experiment_id": result.experiment_id,
            "n_runs": n_runs,
            "n_succeeded": n_ok,
            "n_failed": len(result.failed_runs),
            "n_comparisons": len(result.comparisons),
            "spec_hash": result.spec_hash,
            "model_hash": result.model_hash,
        },
        artifacts={"experiment_id": result.experiment_id},
        diagnostics=problems,
    )


def _exec_evaluate(params: dict[str, Any], ctx: SIActionContext) -> SIActionOutcome:
    from pydantic import ValidationError as PydanticValidationError

    from drw.evaluation import evaluate_run
    from drw.execution.environment import fingerprint_hash
    from drw.models.registry import build_model
    from drw.schema.evaluation import EvaluationConfig
    from drw.schema.experiment import ExperimentSpec
    from drw.schema.observation import ObservationMapping
    from drw.schema.result import RunRecord
    from drw.schema.simulation import SyntheticObservationError, assert_empirical

    experiment_id = _resolve_experiment_id(params, ctx)
    try:
        mapping = ObservationMapping.model_validate(params.get("mapping"))
    except (PydanticValidationError, TypeError) as exc:
        raise SIActionError(
            "bad_request", "the observation mapping is not well formed"
        ) from exc
    config = EvaluationConfig.model_validate(params.get("config") or {})

    loaded = ctx.store.load(experiment_id)
    spec = ExperimentSpec.model_validate(loaded["spec"])
    results = loaded.get("results") or {}
    schema = build_model(spec.model_ref.model_id).describe()
    runs = [RunRecord.model_validate(record) for record in results.get("runs") or []]
    if not runs:
        raise SIActionError(
            "bad_request", f"experiment {experiment_id!r} has no runs to evaluate"
        )
    run_id = _optional_str(params, "run_id") or "baseline"
    if run_id == "baseline":
        run = runs[0]
    else:
        run = next(
            (candidate for candidate in runs if candidate.run_id == run_id), None
        )
        if run is None:
            raise SIActionError(
                "bad_request", f"experiment {experiment_id!r} has no run {run_id!r}"
            )

    dataset = ctx.datasets.load(mapping.dataset.dataset_id)
    try:
        assert_empirical(dataset.provenance, what="Evaluation")
    except SyntheticObservationError as exc:
        raise SIActionError("synthetic_not_empirical", str(exc)) from exc

    evaluation = evaluate_run(
        run,
        schema=schema,
        dataset=dataset,
        mapping=mapping,
        config=config,
        spec_hash=results.get("spec_hash", ""),
        environment_hash=fingerprint_hash(results.get("environment") or {}),
        model_hash=results.get("model_hash", ""),
    )
    metrics = {pair.output: pair.metrics for pair in evaluation.pairs}
    return SIActionOutcome(
        summary=(
            f"Evaluated {experiment_id} against {mapping.dataset.dataset_id}: "
            f"ok={evaluation.ok}, {evaluation.total_usable} usable observation(s)."
        ),
        result={
            "evaluation_hash": evaluation.evaluation_hash,
            "ok": evaluation.ok,
            "total_usable": evaluation.total_usable,
            "total_excluded": evaluation.total_excluded,
            "metrics_by_output": metrics,
        },
        artifacts={"evaluation_hash": evaluation.evaluation_hash},
    )


def _exec_calibrate(params: dict[str, Any], ctx: SIActionContext) -> SIActionOutcome:
    from pydantic import ValidationError as PydanticValidationError

    from drw.calibration import calibrate_for_experiment
    from drw.schema.calibration import CalibrationConfig
    from drw.schema.simulation import SyntheticObservationError, assert_empirical

    experiment_id = _resolve_experiment_id(params, ctx)
    try:
        config = CalibrationConfig.model_validate(params.get("config"))
    except (PydanticValidationError, TypeError) as exc:
        raise SIActionError(
            "bad_request", "the calibration config is not well formed"
        ) from exc
    config = config.model_copy(update={"experiment_id": experiment_id})

    dataset = ctx.datasets.load(config.dataset.dataset_id)
    try:
        assert_empirical(dataset.provenance, what="Calibration")
    except SyntheticObservationError as exc:
        raise SIActionError("synthetic_not_empirical", str(exc)) from exc

    result = calibrate_for_experiment(experiment_id, ctx.store, config)
    artifacts: dict[str, str] = {}
    if bool(params.get("persist", False)):
        ref = ctx.calibrations.save(result)
        artifacts["calibration_id"] = ref.calibration_id
    best = result.best.parameters if result.best is not None else None
    return SIActionOutcome(
        summary=f"Calibration {result.status} ({result.evaluations_completed} evaluations); "
        f"converged={result.converged}.",
        result={
            "status": result.status,
            "converged": result.converged,
            "stop_reason": result.stop_reason,
            "best_parameters": best,
            "objective_value": result.objective.value,
            "evaluations_completed": result.evaluations_completed,
            "note": result.note,
        },
        artifacts=artifacts,
    )


def _exec_validate(params: dict[str, Any], ctx: SIActionContext) -> SIActionOutcome:
    from pydantic import ValidationError as PydanticValidationError

    from drw.schema.simulation import SyntheticObservationError, assert_empirical
    from drw.schema.validation import ValidationConfig
    from drw.validation import validate_for_experiment

    experiment_id = _resolve_experiment_id(params, ctx)
    try:
        config = ValidationConfig.model_validate(params.get("config"))
    except (PydanticValidationError, TypeError) as exc:
        raise SIActionError(
            "bad_request", "the validation config is not well formed"
        ) from exc
    config = config.model_copy(update={"experiment_id": experiment_id})

    for item in config.datasets:
        dataset = ctx.datasets.load(item.dataset.dataset_id)
        try:
            assert_empirical(dataset.provenance, what="Validation")
        except SyntheticObservationError as exc:
            raise SIActionError("synthetic_not_empirical", str(exc)) from exc

    result = validate_for_experiment(experiment_id, ctx.store, config)
    artifacts: dict[str, str] = {}
    if bool(params.get("persist", False)):
        ref = ctx.validations.save(result)
        artifacts["validation_id"] = ref.validation_id
    return SIActionOutcome(
        summary=f"Validation agreement={result.agreement_status}, "
        f"independence={result.independence_status}, acceptance={result.acceptance_status}.",
        result={
            "agreement_status": result.agreement_status,
            "independence_status": result.independence_status,
            "acceptance_status": result.acceptance_status,
            "evaluations_completed": result.evaluations_completed,
            "note": result.note,
        },
        artifacts=artifacts,
    )


def _exec_sensitivity(params: dict[str, Any], ctx: SIActionContext) -> SIActionOutcome:
    from drw.global_sensitivity import sobol_indices_for_experiment

    experiment_id = _resolve_experiment_id(params, ctx)
    report = sobol_indices_for_experiment(
        experiment_id,
        ctx.store,
        output=_optional_str(params, "output"),
        factors=_optional_str_list(params, "factors"),
        sample_count=int(params.get("sample_count") or 32),
        seed=int(params.get("seed") or 0),
    )
    return SIActionOutcome(
        summary=f"Sobol study on {report.output}: inconclusive={report.inconclusive}, "
        f"{report.evaluations_completed} evaluation(s).",
        result={
            "output": report.output,
            "inconclusive": report.inconclusive,
            "reasons": list(report.reasons),
            "results": to_plain(report.results),
            "note": report.note,
        },
    )


def _exec_identifiability(
    params: dict[str, Any], ctx: SIActionContext
) -> SIActionOutcome:
    from drw.identifiability import identifiability_for_experiment

    experiment_id = _resolve_experiment_id(params, ctx)
    report = identifiability_for_experiment(
        experiment_id,
        ctx.store,
        factors=_optional_str_list(params, "factors"),
        outputs=_optional_str_list(params, "outputs"),
    )
    return SIActionOutcome(
        summary=f"Identifiability verdict: {report.verdict} (local structural only).",
        result={
            "verdict": report.verdict,
            "inconclusive": report.inconclusive,
            "reasons": list(report.reasons),
            "numerical_rank": report.numerical_rank,
            "condition_number": report.condition_number,
            "note": report.note,
        },
    )


# ---------------------------------------------------------------------------
# Model-specification executors
# ---------------------------------------------------------------------------


def _load_model_spec(params: dict[str, Any], ctx: SIActionContext) -> Any:
    from pydantic import ValidationError as PydanticValidationError

    from drw.model_spec_store import ModelSpecStoreError
    from drw.schema.model_spec import ModelSpecification

    raw = params.get("specification")
    if raw is not None:
        if not isinstance(raw, dict):
            raise SIActionError(
                "bad_request",
                "input 'specification' must be a model specification object",
            )
        try:
            return ModelSpecification.model_validate(raw)
        except PydanticValidationError as exc:
            raise SIActionError(
                "invalid_model_spec",
                "the model specification is not well formed",
                diagnostics=exc.errors(),
            ) from exc
    spec_id = params.get("spec_id")
    if isinstance(spec_id, str) and spec_id:
        if ctx.model_specs is None:
            raise SIActionError(
                "unsupported_action", "no model-specification store is configured"
            )
        try:
            return ctx.model_specs.load(spec_id)
        except ModelSpecStoreError as exc:
            raise SIActionError("not_found", str(exc)) from exc
    raise SIActionError(
        "bad_request",
        "provide 'specification' (an object) or 'spec_id' (a stored specification)",
    )


def _model_spec_diagnostics(spec: Any) -> tuple[Diagnostic, ...]:
    from drw.schema.model_spec import validate_model_specification

    return validate_model_specification(spec)


def _validate_model_spec_inputs(
    params: dict[str, Any], ctx: SIActionContext
) -> tuple[dict[str, Any], tuple[Diagnostic, ...]]:
    try:
        spec = _load_model_spec(params, ctx)
    except SIActionError as exc:
        return dict(params), (
            Diagnostic(level="error", code=exc.code, message=exc.message),
        )
    return {"specification": to_plain(spec)}, _model_spec_diagnostics(spec)


def _exec_validate_model_spec(
    params: dict[str, Any], ctx: SIActionContext
) -> SIActionOutcome:
    from drw.schema.model_spec import compilation_supported, specification_to_schema

    spec = _load_model_spec(params, ctx)
    diagnostics = _model_spec_diagnostics(spec)
    errors = [d for d in diagnostics if d.level == "error"]
    supported, reason = compilation_supported()
    return SIActionOutcome(
        summary=(
            f"Model specification {spec.model_id} v{spec.version}: "
            f"{'valid' if not errors else f'{len(errors)} error(s)'}. "
            f"Compilation supported={supported}."
        ),
        result={
            "model_id": spec.model_id,
            "version": spec.version,
            "spec_hash": spec.content_hash(),
            "errors": to_plain(errors),
            "warnings": to_plain([d for d in diagnostics if d.level == "warning"]),
            "declared_schema": to_plain(specification_to_schema(spec)),
            "compilation_supported": supported,
            "compilation_note": reason,
        },
        diagnostics=diagnostics,
    )


def _exec_propose_model(
    params: dict[str, Any], ctx: SIActionContext
) -> SIActionOutcome:
    spec = _load_model_spec(params, ctx)
    diagnostics = _model_spec_diagnostics(spec)
    return SIActionOutcome(
        summary=f"Proposed model specification {spec.model_id} v{spec.version} "
        f"({len(spec.parameters)} parameters, {len(spec.variables)} variables, "
        f"{len(spec.relationships)} relationships).",
        result={
            "specification": to_plain(spec),
            "spec_hash": spec.content_hash(),
            "diagnostics": to_plain(diagnostics),
        },
        diagnostics=diagnostics,
    )


def _exec_create_model_spec(
    params: dict[str, Any], ctx: SIActionContext
) -> SIActionOutcome:
    spec = _load_model_spec(params, ctx)
    diagnostics = _model_spec_diagnostics(spec)
    errors = [d for d in diagnostics if d.level == "error"]
    if errors:
        raise SIActionError(
            "invalid_model_spec",
            "the model specification has errors and was not stored",
            diagnostics=to_plain(errors),
        )
    if ctx.model_specs is None:
        raise SIActionError(
            "unsupported_action", "no model-specification store is configured"
        )
    ref = ctx.model_specs.save(spec)
    return SIActionOutcome(
        summary=f"Stored model specification {ref.spec_id} (model {spec.model_id} v{spec.version}).",
        result={"ref": to_plain(ref), "spec_hash": spec.content_hash()},
        artifacts={"spec_id": ref.spec_id},
        diagnostics=diagnostics,
    )


def _exec_inspect_model_spec(
    params: dict[str, Any], ctx: SIActionContext
) -> SIActionOutcome:
    from drw.model_spec_store import ModelSpecStoreError

    spec_id = _required_str(params, "spec_id")
    try:
        spec = ctx.model_specs.load(spec_id)
        verification = ctx.model_specs.verify(spec_id)
    except ModelSpecStoreError as exc:
        raise SIActionError("not_found", str(exc)) from exc
    return SIActionOutcome(
        summary=f"Model specification {spec_id}: {spec.model_id} v{spec.version}.",
        result={
            "specification": to_plain(spec),
            "verification": to_plain(verification),
        },
    )


def _validate_create_model_inputs(
    params: dict[str, Any], ctx: SIActionContext
) -> tuple[dict[str, Any], tuple[Diagnostic, ...]]:
    from drw.model_compiler import ModelCompilationError, compile_model_spec

    try:
        spec = _load_model_spec(params, ctx)
    except SIActionError as exc:
        return dict(params), (
            Diagnostic(level="error", code=exc.code, message=exc.message),
        )
    try:
        compile_model_spec(spec)
    except ModelCompilationError as exc:
        return (
            {"specification": to_plain(spec)},
            (Diagnostic(level="error", code=exc.code, message=exc.message),),
        )
    return {"specification": to_plain(spec)}, _model_spec_diagnostics(spec)


def _exec_create_model(params: dict[str, Any], ctx: SIActionContext) -> SIActionOutcome:
    from drw.model_compiler import ModelCompilationError, compile_model_spec

    spec = _load_model_spec(params, ctx)
    try:
        compiled = compile_model_spec(spec)
    except ModelCompilationError as exc:
        raise SIActionError(
            exc.code, exc.message, diagnostics=to_plain(exc.diagnostics)
        ) from exc
    if ctx.models is None:
        raise SIActionError(
            "unsupported_action", "no compiled-model store is configured"
        )
    ref = ctx.models.save(compiled)
    return SIActionOutcome(
        summary=(
            f"Compiled and stored model {ref.model_id} (from specification "
            f"{spec.model_id} v{spec.version}); it is now executable by the Runner."
        ),
        result={
            "model_id": ref.model_id,
            "model_name": ref.model_name,
            "version": ref.version,
            "spec_hash": ref.spec_hash,
            "compile_hash": ref.compile_hash,
            "model_hash": ref.model_hash,
            "compiler": {
                "id": compiled.compiler_id,
                "version": compiled.compiler_version,
            },
            "state_variables": list(compiled.state_names),
            "parameters": list(compiled.parameter_names),
            "t_span": list(compiled.t_span),
            "n_points": compiled.n_points,
            "schema": to_plain(compiled.schema),
            "assumptions": list(spec.assumptions),
        },
        artifacts={"model_id": ref.model_id},
        diagnostics=compiled.diagnostics,
    )


def _simulation_spec_from(params: dict[str, Any], ctx: SIActionContext) -> Any:
    from pydantic import ValidationError as PydanticValidationError

    from drw.schema.simulation import SimulationSpec

    raw = params.get("simulation")
    if not isinstance(raw, dict):
        raise SIActionError(
            "bad_request",
            "input 'simulation' must be a simulation specification object",
        )
    try:
        return SimulationSpec.model_validate(raw)
    except PydanticValidationError as exc:
        raise SIActionError(
            "invalid_simulation",
            "the simulation specification is not well formed",
            diagnostics=exc.errors(),
        ) from exc


def _validate_simulate_inputs(
    params: dict[str, Any], ctx: SIActionContext
) -> tuple[dict[str, Any], tuple[Diagnostic, ...]]:
    from drw.simulation import validate_simulation

    try:
        spec = _simulation_spec_from(params, ctx)
    except SIActionError as exc:
        return dict(params), (
            Diagnostic(level="error", code=exc.code, message=exc.message),
        )
    model_id = _optional_str(params, "model_id") or spec.model_ref.model_id
    return {"simulation": to_plain(spec)}, validate_simulation(spec, model_id=model_id)


def _exec_simulate(params: dict[str, Any], ctx: SIActionContext) -> SIActionOutcome:
    from drw.simulation import SimulationError, simulate
    from drw.simulation_store import simulation_id_for

    spec = _simulation_spec_from(params, ctx)
    model_id = _optional_str(params, "model_id") or spec.model_ref.model_id
    simulation_hash = spec.content_hash()
    simulation_id = simulation_id_for(simulation_hash)

    # Idempotent: an identical specification already simulated is not re-run.
    if ctx.simulations is not None and ctx.simulations.exists(simulation_id):
        ref = ctx.simulations.ref(simulation_id)
        artifacts = {"simulation_id": simulation_id}
        if ref.dataset_id:
            artifacts["dataset_id"] = ref.dataset_id
        return SIActionOutcome(
            summary=(
                f"Simulation {simulation_id} for model {model_id} already exists for this "
                "specification; it was not re-run (identical requests are idempotent)."
            ),
            result={
                "model_id": model_id,
                "simulation_hash": simulation_hash,
                "simulation_id": simulation_id,
                "dataset_id": ref.dataset_id,
                "synthetic": True,
                "idempotent": True,
            },
            artifacts=artifacts,
        )

    try:
        outcome = simulate(spec, model_id=model_id)
    except SimulationError as exc:
        raise SIActionError(
            exc.code, exc.message, diagnostics=to_plain(exc.diagnostics)
        ) from exc

    if ctx.datasets is None:
        raise SIActionError("unsupported_action", "no dataset store is configured")
    ctx.datasets.save(outcome.dataset)
    artifacts: dict[str, str] = {"dataset_id": outcome.dataset_ref.dataset_id}
    if ctx.simulations is not None:
        ref = ctx.simulations.save(outcome.result)
        artifacts["simulation_id"] = ref.simulation_id

    baseline = outcome.run.result
    summary_outputs = (
        {name: output.kind for name, output in baseline.outputs.items()}
        if baseline is not None
        else {}
    )
    return SIActionOutcome(
        summary=(
            f"Simulated {model_id} ({len(outcome.result.observation_set.rows()) if outcome.result.observation_set else 0} "
            f"points) and stored an explicitly synthetic dataset {outcome.dataset_ref.dataset_id}."
        ),
        result={
            "model_id": model_id,
            "simulation_hash": outcome.result.simulation_hash,
            "run_id": outcome.result.run_id,
            "dataset_id": outcome.dataset_ref.dataset_id,
            "dataset_content_hash": outcome.dataset_ref.content_hash,
            "synthetic": True,
            "outputs": summary_outputs,
            "parameters": dict(spec.parameters),
            "initial_conditions": dict(spec.initial_conditions),
            "scenario": spec.scenario,
            "seed": spec.config.seed,
            "provenance": to_plain(outcome.result.provenance),
            "note": outcome.result.note,
        },
        artifacts=artifacts,
        diagnostics=outcome.result.diagnostics,
    )


def _exec_propose_simulation(
    params: dict[str, Any], ctx: SIActionContext
) -> SIActionOutcome:
    from pydantic import ValidationError as PydanticValidationError

    from drw.schema.simulation import SimulationSpec, simulation_supported

    raw = params.get("simulation")
    if not isinstance(raw, dict):
        raise SIActionError(
            "bad_request", "input 'simulation' must be a simulation specification"
        )
    try:
        spec = SimulationSpec.model_validate(raw)
    except PydanticValidationError as exc:
        raise SIActionError(
            "invalid_simulation",
            "the simulation specification is not well formed",
            diagnostics=exc.errors(),
        ) from exc
    supported, reason = simulation_supported()
    return SIActionOutcome(
        summary=f"Proposed simulation of {spec.model_ref.model_id} "
        f"({len(spec.parameters)} parameter(s), scenario {spec.scenario!r}). Executable={supported}.",
        result={
            "simulation": to_plain(spec),
            "simulation_hash": spec.content_hash(),
            "synthetic_by_construction": True,
            "simulation_supported": supported,
            "simulation_note": reason,
        },
    )


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


def _read(
    action_id: str,
    name: str,
    description: str,
    execute: Executor,
    *,
    validate: Validator | None = None,
) -> SIAction:
    return SIAction(
        action_id=action_id,
        name=name,
        description=description,
        category=_READ_ONLY_CATEGORY,
        read_only=True,
        effects="none",
        validate=validate,
        execute=execute,
    )


def _write(
    action_id: str,
    name: str,
    description: str,
    category: ActionCategory,
    effects: SIEffect,
    execute: Executor,
    *,
    validate: Validator | None = None,
    supported: bool = True,
    limitations: tuple[str, ...] = (),
) -> SIAction:
    return SIAction(
        action_id=action_id,
        name=name,
        description=description,
        category=category,
        read_only=False,
        effects=effects,
        supported=supported,
        limitations=limitations,
        validate=validate,
        execute=execute,
    )


def default_registry() -> SIActionRegistry:
    """The built-in action registry. Every entry delegates to a real capability."""
    return SIActionRegistry(
        [
            # -- read ---------------------------------------------------------
            _read(
                "inspect_project",
                "Inspect project",
                "Summarize the current project.",
                _exec_inspect_project,
            ),
            _read(
                "inspect_investigation",
                "Inspect investigation",
                "Summarize the durable SI state of this investigation.",
                _exec_inspect_investigation,
            ),
            _read(
                "list_models",
                "List models",
                "List the registered models.",
                _exec_list_models,
            ),
            _read(
                "inspect_model",
                "Inspect model",
                "Show a model's schema and capabilities.",
                _exec_inspect_model,
            ),
            _read(
                "inspect_capabilities",
                "Inspect capabilities",
                "Show what a model supports.",
                _exec_inspect_capabilities,
            ),
            _read(
                "list_datasets",
                "List datasets",
                "List observation datasets.",
                _exec_list_datasets,
            ),
            _read(
                "inspect_dataset",
                "Inspect dataset",
                "Show one dataset and verify it.",
                _exec_inspect_dataset,
            ),
            _read(
                "list_experiments",
                "List experiments",
                "List this project's experiments.",
                _exec_list_experiments,
            ),
            _read(
                "inspect_experiment",
                "Inspect experiment",
                "Show one experiment's spec and run summary.",
                _exec_inspect_experiment,
            ),
            _read(
                "inspect_evidence",
                "Inspect evidence",
                "Show an experiment's evidence package.",
                _exec_inspect_evidence,
            ),
            _read(
                "list_calibrations",
                "List calibrations",
                "List stored calibrations.",
                _exec_list_calibrations,
            ),
            _read(
                "inspect_calibration",
                "Inspect calibration",
                "Show one stored calibration.",
                _exec_inspect_calibration,
            ),
            _read(
                "list_validations",
                "List validations",
                "List stored validations.",
                _exec_list_validations,
            ),
            _read(
                "inspect_validation",
                "Inspect validation",
                "Show one stored validation.",
                _exec_inspect_validation,
            ),
            _read(
                "inspect_model_spec",
                "Inspect model specification",
                "Show a stored model specification.",
                _exec_inspect_model_spec,
            ),
            # -- model --------------------------------------------------------
            _read(
                "validate_model_spec",
                "Validate model specification",
                "Validate a structured model specification (no execution).",
                _exec_validate_model_spec,
                validate=_validate_model_spec_inputs,
            ),
            _read(
                "propose_model",
                "Propose model",
                "Normalize and inspect a proposed model specification.",
                _exec_propose_model,
            ),
            _read(
                "propose_simulation",
                "Propose simulation",
                "Normalize a simulation request and mark it synthetic by construction.",
                _exec_propose_simulation,
            ),
            _write(
                "create_model_spec",
                "Create model specification",
                "Persist a validated, inspectable model specification artifact.",
                "model",
                "creates_model_spec",
                _exec_create_model_spec,
                validate=_validate_model_spec_inputs,
            ),
            _write(
                "create_model",
                "Create model",
                "Compile a validated model specification into an executable, stored model.",
                "model",
                "modifies_model",
                _exec_create_model,
                validate=_validate_create_model_inputs,
            ),
            # -- simulation ---------------------------------------------------
            _write(
                "simulate",
                "Simulate observations",
                "Run a model through the Runner and store its output as a synthetic dataset.",
                "simulation",
                "creates_dataset",
                _exec_simulate,
                validate=_validate_simulate_inputs,
            ),
            # -- scientific ---------------------------------------------------
            _write(
                "create_experiment",
                "Create experiment",
                "Validate and run an experiment, persisting its results and evidence.",
                "scientific",
                "creates_experiment",
                _exec_create_experiment,
                validate=_validate_experiment_inputs,
            ),
            _write(
                "evaluate",
                "Evaluate model against observations",
                "Compare a stored run with an empirical dataset through a mapping.",
                "scientific",
                "creates_analysis",
                _exec_evaluate,
            ),
            _write(
                "calibrate",
                "Calibrate parameters",
                "Fit bounded parameters to an empirical dataset.",
                "scientific",
                "creates_calibration",
                _exec_calibrate,
            ),
            _write(
                "validate",
                "Validate frozen calibration",
                "Test a frozen calibration against independent empirical datasets.",
                "scientific",
                "creates_validation",
                _exec_validate,
            ),
            _write(
                "sensitivity",
                "Global sensitivity (Sobol)",
                "Estimate variance-based sensitivity indices.",
                "scientific",
                "creates_analysis",
                _exec_sensitivity,
            ),
            _write(
                "identifiability",
                "Local identifiability",
                "Test whether parameters are locally distinguishable.",
                "scientific",
                "creates_analysis",
                _exec_identifiability,
            ),
        ]
    )
