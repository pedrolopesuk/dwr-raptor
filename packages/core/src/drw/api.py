"""JSON bridge between the researcher UI and the scientific core.

The bridge is the **only** boundary between TypeScript and Python. It is a
one-shot process: a JSON request on stdin, a JSON response on stdout. It reuses
the existing contracts and engine - it does not reimplement any science.

Request::

    {"op": "run", "params": {"spec": {...}, "project_id": "default", "job_id": "job-..."}}

Response (always JSON, never a traceback)::

    {"ok": true,  "data": {...}}
    {"ok": false, "error": {"code": "...", "message": "...", "diagnostics": [...]}}

Operations: ``list_models``, ``describe_model``, ``capabilities``,
``sample_experiment``, ``validate``, ``run``, ``job_status``,
``list_experiments``, ``get_experiment``, ``evidence``, ``export_evidence``,
``verify_evidence``, ``sensitivity``, ``list_projects``, ``create_project``,
``plan_experiment``, ``planner_status``, ``environment``.

The workspace root comes from ``DRW_WORKSPACE``. The bridge executes only
registered models; it exposes no network service and runs no arbitrary
caller-supplied code.
"""

from __future__ import annotations

import json
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

from pydantic import ValidationError as PydanticValidationError

from drw.capabilities import model_capabilities
from drw.execution.environment import environment_fingerprint, fingerprint_hash
from drw.execution.runner import ExperimentValidationError, Runner
from drw.jobs import InvalidJobId, JobJournal, derive_phase
from drw.models.registry import build_model, model_schemas
from drw.planner import PlannerError, plan_experiment, provider_status
from drw.schema.experiment import ExperimentSpec, estimate_run_count, validate_experiment
from drw.schema.serialization import dumps_pretty, to_plain
from drw.sensitivity import oat_sensitivity, primary_output
from drw.store import (
    DEFAULT_PROJECT_ID,
    ExperimentStore,
    InvalidExperimentId,
    default_store,
    result_payload,
)

__all__ = ["ApiError", "handle", "main"]

Params = dict[str, Any]


class ApiError(Exception):
    """A request-level failure with a stable machine-readable code."""

    def __init__(self, code: str, message: str, *, diagnostics: Any = ()) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.diagnostics = list(diagnostics)


def _require(params: Params, key: str) -> Any:
    if key not in params:
        raise ApiError("bad_request", f"missing required parameter {key!r}")
    return params[key]


def _param_str(params: Params, key: str) -> str:
    value = _require(params, key)
    if not isinstance(value, str) or not value:
        raise ApiError("bad_request", f"parameter {key!r} must be a non-empty string")
    return value


def _load_spec(params: Params) -> ExperimentSpec:
    spec_json = _require(params, "spec")
    try:
        return ExperimentSpec.model_validate(spec_json)
    except PydanticValidationError as exc:
        raise ApiError(
            "invalid_spec",
            "the experiment spec is not well formed",
            diagnostics=exc.errors(),
        ) from exc


# ---------------------------------------------------------------------------
# Operations. Each takes (params, store).
# ---------------------------------------------------------------------------


def op_list_models(_params: Params, _store: ExperimentStore) -> dict[str, Any]:
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
    return {"models": models}


def op_describe_model(params: Params, _store: ExperimentStore) -> dict[str, Any]:
    schema = build_model(_param_str(params, "model_id")).describe()
    return {
        "schema": to_plain(schema),
        "model_hash": schema.content_hash(),
        "capabilities": model_capabilities(schema),
    }


def op_capabilities(params: Params, _store: ExperimentStore) -> dict[str, Any]:
    schema = build_model(_param_str(params, "model_id")).describe()
    return {"model_id": schema.model_id, "capabilities": model_capabilities(schema)}


def op_sample_experiment(params: Params, _store: ExperimentStore) -> dict[str, Any]:
    from drw.demo import DEMO_MODEL, build_demo_experiment

    spec = build_demo_experiment(params.get("model_id", DEMO_MODEL))
    return {"spec": to_plain(spec)}


def op_validate(params: Params, _store: ExperimentStore) -> dict[str, Any]:
    spec = _load_spec(params)
    schema = build_model(spec.model_ref.model_id).describe()
    diagnostics = validate_experiment(spec, schema)
    return {
        "ok": not any(d.level == "error" for d in diagnostics),
        "diagnostics": to_plain(diagnostics),
        "estimate": to_plain(estimate_run_count(spec)),
    }


def op_run(params: Params, store: ExperimentStore) -> dict[str, Any]:
    spec = _load_spec(params)
    persist = bool(params.get("persist", True))
    project_id = str(params.get("project_id") or DEFAULT_PROJECT_ID)
    journal: JobJournal | None = None
    requested_job_id = params.get("job_id")
    if requested_job_id is not None:
        try:
            journal = JobJournal(store.root, str(requested_job_id))
        except InvalidJobId as exc:
            raise ApiError("bad_request", str(exc)) from exc

    # Validate before recording anything so a rejected spec produces no job events.
    schema = build_model(spec.model_ref.model_id).describe()
    problems = validate_experiment(spec, schema)
    if any(d.level == "error" for d in problems):
        raise ApiError(
            "validation_error",
            "the experiment failed validation and was not executed",
            diagnostics=to_plain(problems),
        )

    if journal is not None:
        journal.prune()
        journal.append(
            "started",
            total_runs=estimate_run_count(spec).total_runs,
            project_id=project_id,
        )

    def _on_run(index: int, total: int, record: Any) -> None:
        if journal is None:
            return
        journal.append(
            "run_completed",
            index=index,
            total_runs=total,
            run_id=record.run_id,
            label=record.label,
            status=record.status.value,
            timed_out=record.timed_out,
            duration_s=record.duration_s,
        )

    try:
        result = Runner().run(spec, on_run=_on_run if journal is not None else None)
    except ExperimentValidationError as exc:  # pragma: no cover - pre-validated above
        if journal is not None:
            journal.append("finished", status="failed", error="validation_error")
        raise ApiError(
            "validation_error",
            "the experiment failed validation and was not executed",
            diagnostics=to_plain(exc.diagnostics),
        ) from exc

    if journal is not None:
        counts: dict[str, int] = {}
        for record in result.runs:
            counts[record.status.value] = counts.get(record.status.value, 0) + 1
        if all(record.succeeded for record in result.runs):
            status = "succeeded"
        elif any(record.timed_out for record in result.runs):
            status = "timed_out"
        else:
            status = "failed"
        journal.append(
            "finished",
            status=status,
            counts=counts,
            comparisons=len(result.comparisons),
            experiment_id=result.experiment_id,
        )

    data = result_payload(result)
    data["job_id"] = journal.job_id if journal is not None else None
    data["project_id"] = project_id
    if persist:
        store.save(result, project_id=project_id)
        data["evidence"] = store.evidence(result.experiment_id)
    return data


def op_job_status(params: Params, store: ExperimentStore) -> dict[str, Any]:
    job_id = _param_str(params, "job_id")
    try:
        journal = JobJournal(store.root, job_id)
    except InvalidJobId as exc:
        raise ApiError("bad_request", str(exc)) from exc
    return {"job_id": job_id, **derive_phase(journal.read())}


def op_list_experiments(params: Params, store: ExperimentStore) -> dict[str, Any]:
    project_id = params.get("project_id")
    return {"experiments": store.list(project_id=str(project_id) if project_id else None)}


def op_get_experiment(params: Params, store: ExperimentStore) -> dict[str, Any]:
    return {"experiment": store.load(_param_str(params, "experiment_id"))}


def op_evidence(params: Params, store: ExperimentStore) -> dict[str, Any]:
    return {"evidence": store.evidence(_param_str(params, "experiment_id"))}


def op_export_evidence(params: Params, store: ExperimentStore) -> dict[str, Any]:
    archive = store.export_zip(_param_str(params, "experiment_id"))
    try:
        relative = archive.relative_to(store.root).as_posix()
    except ValueError:  # pragma: no cover - defensive
        relative = str(archive)
    return {"zip": relative, "path": str(archive)}


def op_verify_evidence(params: Params, store: ExperimentStore) -> dict[str, Any]:
    from drw.execution.evidence import EvidenceVerificationError, verify_evidence

    experiment_id = _param_str(params, "experiment_id")
    manifest = store.experiment_dir(experiment_id) / "evidence" / "manifest.json"
    if not manifest.is_file():
        raise ApiError("not_found", f"experiment {experiment_id!r} has no evidence package")
    try:
        report = verify_evidence(manifest)
    except EvidenceVerificationError as exc:
        raise ApiError("bad_request", str(exc)) from exc
    return {"experiment_id": experiment_id, "verification": to_plain(report)}


def op_sensitivity(params: Params, store: ExperimentStore) -> dict[str, Any]:
    loaded = store.load(_param_str(params, "experiment_id"))
    spec = ExperimentSpec.model_validate(loaded["spec"])
    runs = loaded["results"].get("runs") or []
    if not runs:
        raise ApiError("bad_request", "experiment has no runs to analyze")
    baseline_run = runs[0]
    schema = build_model(spec.model_ref.model_id).describe()
    metric = primary_output(schema)
    reference_peak = (baseline_run.get("metrics") or {}).get(metric)
    ranking = oat_sensitivity(
        schema, dict(baseline_run.get("inputs") or {}), reference_peak, metric
    )
    return {"metric": metric, "perturbation": "+10%", "ranking": ranking}


def op_list_projects(_params: Params, store: ExperimentStore) -> dict[str, Any]:
    return {"projects": store.list_projects()}


def op_create_project(params: Params, store: ExperimentStore) -> dict[str, Any]:
    name = _param_str(params, "name")
    description = params.get("description") or ""
    model_id = params.get("model_id")
    project = store.create_project(
        name, description=str(description), model_id=str(model_id) if model_id else None
    )
    return {"project": project}


def op_plan_experiment(params: Params, _store: ExperimentStore) -> dict[str, Any]:
    model_id = _param_str(params, "model_id")
    question = _param_str(params, "question")
    context = params.get("context") or ""
    schema = build_model(model_id).describe()
    try:
        plan = plan_experiment(
            model_id=model_id, question=question, schema=schema, context=str(context)
        )
    except PlannerError as exc:
        raise ApiError(
            exc.code, exc.message, diagnostics=[{"code": exc.code, "questions": exc.questions}]
        ) from exc
    return {
        "spec": to_plain(plan.spec) if plan.spec is not None else None,
        "assumptions": plan.assumptions,
        "questions": plan.questions,
        "diagnostics": to_plain(plan.diagnostics),
        "validation_ok": not any(d.level == "error" for d in plan.diagnostics),
        "provider": plan.provider,
        "used_ai": plan.used_ai,
        "rationale": plan.rationale,
    }


def op_planner_status(_params: Params, _store: ExperimentStore) -> dict[str, Any]:
    return provider_status()


def op_environment(_params: Params, _store: ExperimentStore) -> dict[str, Any]:
    fingerprint = environment_fingerprint()
    return {"environment": fingerprint, "environment_hash": fingerprint_hash(fingerprint)}


_OPS: dict[str, Callable[[Params, ExperimentStore], dict[str, Any]]] = {
    "list_models": op_list_models,
    "describe_model": op_describe_model,
    "capabilities": op_capabilities,
    "sample_experiment": op_sample_experiment,
    "validate": op_validate,
    "run": op_run,
    "job_status": op_job_status,
    "list_experiments": op_list_experiments,
    "get_experiment": op_get_experiment,
    "evidence": op_evidence,
    "export_evidence": op_export_evidence,
    "verify_evidence": op_verify_evidence,
    "sensitivity": op_sensitivity,
    "list_projects": op_list_projects,
    "create_project": op_create_project,
    "plan_experiment": op_plan_experiment,
    "planner_status": op_planner_status,
    "environment": op_environment,
}


def _error(code: str, message: str, diagnostics: Any = ()) -> dict[str, Any]:
    return {"ok": False, "error": {"code": code, "message": message, "diagnostics": list(diagnostics)}}


def handle(request: Any, *, store: ExperimentStore | None = None) -> dict[str, Any]:
    """Dispatch a request dict and always return a response dict (never raises)."""
    if not isinstance(request, dict):
        return _error("bad_request", "request must be a JSON object")
    op = request.get("op")
    params = request.get("params") or {}
    if not isinstance(op, str):
        return _error("bad_request", "request.op must be a string")
    if not isinstance(params, dict):
        return _error("bad_request", "request.params must be an object")
    handler = _OPS.get(op)
    if handler is None:
        return _error("unknown_op", f"unknown operation {op!r}")

    active_store = store if store is not None else default_store()
    try:
        data = handler(params, active_store)
    except ApiError as exc:
        return _error(exc.code, exc.message, exc.diagnostics)
    except KeyError as exc:
        return _error("not_found", str(exc).strip("'"))
    except InvalidExperimentId as exc:
        return _error("bad_request", str(exc))
    except ValueError as exc:
        return _error("bad_request", str(exc))
    except Exception as exc:  # the bridge must never leak a traceback
        return _error("internal_error", f"{type(exc).__name__}: {exc}")
    return {"ok": True, "data": data}


def main(argv: list[str] | None = None) -> int:
    """Read one JSON request and write one JSON response."""
    args = sys.argv[1:] if argv is None else argv
    raw = Path(args[0]).read_text(encoding="utf-8") if args else sys.stdin.read()
    try:
        request = json.loads(raw)
    except json.JSONDecodeError as exc:
        print(dumps_pretty(_error("bad_request", f"invalid JSON request: {exc}")))
        return 2
    print(dumps_pretty(handle(request)))
    return 0


if __name__ == "__main__":  # pragma: no cover - exercised via subprocess
    raise SystemExit(main())
