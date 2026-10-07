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
``verify_evidence``, ``reproduce_experiment``, ``sensitivity``, ``uncertainty``,
``global_sensitivity``, ``identifiability``, ``list_dataset_sources``,
``inspect_dataset``, ``import_dataset``, ``list_datasets``, ``describe_dataset``
(alias ``get_dataset``), ``verify_dataset``, ``evaluate``, ``calibrate``,
``list_calibrations``, ``get_calibration``, ``verify_calibration``,
``run_validation``, ``list_validations``, ``get_validation``,
``verify_validation``, ``check_validation_staleness``, ``list_projects``,
``create_project``, ``plan_experiment``, ``planner_status``, ``si_state``,
``si_ask``, ``si_preview``, ``si_execute``, ``si_reject``, ``si_actions``,
``si_provider``, ``environment``.

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
from drw.schema.experiment import (
    ExperimentSpec,
    estimate_run_count,
    validate_experiment,
)
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


def _param_number(params: Params, key: str) -> float:
    value = _require(params, key)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ApiError("bad_request", f"parameter {key!r} must be a number")
    return float(value)


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
    return {
        "experiments": store.list(project_id=str(project_id) if project_id else None)
    }


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
        raise ApiError(
            "not_found", f"experiment {experiment_id!r} has no evidence package"
        )
    try:
        report = verify_evidence(manifest)
    except EvidenceVerificationError as exc:
        raise ApiError("bad_request", str(exc)) from exc
    return {"experiment_id": experiment_id, "verification": to_plain(report)}


def op_reproduce_experiment(params: Params, store: ExperimentStore) -> dict[str, Any]:
    from drw.reproduce import ReproduceError, reproduce_experiment

    experiment_id = _param_str(params, "experiment_id")
    rtol = _param_number(params, "rtol")
    atol = _param_number(params, "atol")
    try:
        report = reproduce_experiment(experiment_id, rtol=rtol, atol=atol, store=store)
    except ReproduceError as exc:
        raise ApiError("bad_request", str(exc)) from exc
    return {"report": to_plain(report)}


def op_uncertainty(params: Params, store: ExperimentStore) -> dict[str, Any]:
    from drw.uncertainty import UncertaintyError, uncertainty_for_experiment

    experiment_id = _param_str(params, "experiment_id")
    try:
        summary = uncertainty_for_experiment(experiment_id, store)
    except UncertaintyError as exc:
        raise ApiError("bad_request", str(exc)) from exc
    return {"uncertainty": to_plain(summary)}


def op_global_sensitivity(params: Params, store: ExperimentStore) -> dict[str, Any]:
    from drw.global_sensitivity import (
        DEFAULT_BOOTSTRAP,
        DEFAULT_SAMPLE_COUNT,
        GlobalSensitivityError,
        default_factors,
        sobol_indices_for_experiment,
    )
    from drw.models.registry import build_model
    from drw.schema.experiment import ExperimentSpec as _Spec

    experiment_id = _param_str(params, "experiment_id")
    output = params.get("output") or None
    factors = params.get("factors") or None
    if factors is not None and (
        not isinstance(factors, list)
        or not all(isinstance(item, str) for item in factors)
    ):
        raise ApiError("bad_request", "'factors' must be a list of parameter names")
    try:
        sample_count = int(params.get("sample_count", DEFAULT_SAMPLE_COUNT))
        seed = int(params.get("seed", 0))
        bootstrap = int(params.get("bootstrap_resamples", DEFAULT_BOOTSTRAP))
    except (TypeError, ValueError) as exc:
        raise ApiError(
            "bad_request", f"invalid numeric study parameter: {exc}"
        ) from exc

    # Resolve the study size for the job journal (reuses the core's canonical
    # factor-selection rule so the reported total matches what will run).
    loaded = store.load(experiment_id)  # KeyError -> not found
    spec = _Spec.model_validate(loaded["spec"])
    schema = build_model(spec.model_ref.model_id).describe()
    chosen_factors = list(factors) if factors else default_factors(schema)

    journal: JobJournal | None = None
    if params.get("job_id") is not None:
        try:
            journal = JobJournal(store.root, str(params["job_id"]))
        except InvalidJobId as exc:
            raise ApiError("bad_request", str(exc)) from exc
        journal.prune()
        journal.append("started", total_runs=sample_count * (len(chosen_factors) + 2))

    try:
        report = sobol_indices_for_experiment(
            experiment_id,
            store,
            output=output,
            factors=factors,
            sample_count=sample_count,
            seed=seed,
            journal=journal,
            bootstrap_resamples=bootstrap,
        )
    except GlobalSensitivityError as exc:
        if journal is not None:
            journal.append("finished", status="failed", error="bad_request")
        raise ApiError("bad_request", str(exc)) from exc

    if journal is not None:
        journal.append(
            "finished",
            status="inconclusive" if report.inconclusive else "succeeded",
            evaluations=report.evaluations_completed,
        )
    return {"report": to_plain(report)}


def op_identifiability(params: Params, store: ExperimentStore) -> dict[str, Any]:
    from drw.identifiability import (
        CONDITION_THRESHOLD,
        DEFAULT_RANK_TOLERANCE,
        DEFAULT_STEP_SCALE,
        IdentifiabilityError,
        default_factors,
        identifiability_for_experiment,
    )
    from drw.models.registry import build_model
    from drw.schema.experiment import ExperimentSpec as _Spec

    experiment_id = _param_str(params, "experiment_id")
    factors = params.get("factors") or None
    outputs = params.get("outputs") or None
    for key, value in (("factors", factors), ("outputs", outputs)):
        if value is not None and (
            not isinstance(value, list)
            or not all(isinstance(item, str) for item in value)
        ):
            raise ApiError("bad_request", f"{key!r} must be a list of names")
    try:
        step_scale = float(params.get("step_scale", DEFAULT_STEP_SCALE))
        seed = int(params.get("seed", 0))
        rank_tolerance = float(params.get("rank_tolerance", DEFAULT_RANK_TOLERANCE))
        condition_threshold = float(
            params.get("condition_threshold", CONDITION_THRESHOLD)
        )
    except (TypeError, ValueError) as exc:
        raise ApiError(
            "bad_request", f"invalid numeric study parameter: {exc}"
        ) from exc

    # Resolve the study size for the job journal (reuses the core's canonical
    # factor-selection rule so the reported total matches what will run).
    loaded = store.load(experiment_id)  # KeyError -> not found
    spec = _Spec.model_validate(loaded["spec"])
    schema = build_model(spec.model_ref.model_id).describe()
    chosen_factors = list(factors) if factors else default_factors(schema)
    total = 2 * len(chosen_factors) + 1

    journal: JobJournal | None = None
    if params.get("job_id") is not None:
        try:
            journal = JobJournal(store.root, str(params["job_id"]))
        except InvalidJobId as exc:
            raise ApiError("bad_request", str(exc)) from exc
        journal.prune()
        journal.append("started", total_runs=total)

    try:
        report = identifiability_for_experiment(
            experiment_id,
            store,
            factors=factors,
            outputs=outputs,
            step_scale=step_scale,
            seed=seed,
            journal=journal,
            rank_tolerance=rank_tolerance,
            condition_threshold=condition_threshold,
        )
    except IdentifiabilityError as exc:
        if journal is not None:
            journal.append("finished", status="failed", error="bad_request")
        raise ApiError("bad_request", str(exc)) from exc

    if journal is not None:
        journal.append(
            "finished",
            status="inconclusive" if report.inconclusive else "succeeded",
            evaluations=report.evaluations_completed,
        )
    return {"report": to_plain(report)}


def _dataset_source_path(store: ExperimentStore, filename: str) -> Path:
    """Resolve a CSV file inside ``<workspace>/dataset-sources`` (contained)."""
    if not filename:
        raise ApiError("bad_request", "filename must be a non-empty string")
    relative = Path(filename)
    if relative.is_absolute() or ".." in relative.parts:
        raise ApiError(
            "bad_request",
            "filename must be a relative path inside the dataset-sources directory",
        )
    sources = (Path(store.root) / "dataset-sources").resolve()
    candidate = (sources / relative).resolve()
    if candidate != sources and sources not in candidate.parents:
        raise ApiError("bad_request", "filename escapes the dataset-sources directory")
    if not candidate.is_file():
        raise ApiError("not_found", f"source file {filename!r} not found")
    return candidate


def op_list_dataset_sources(_params: Params, store: ExperimentStore) -> dict[str, Any]:
    sources = Path(store.root) / "dataset-sources"
    if not sources.is_dir():
        return {"sources": []}
    items = [
        {"filename": path.name, "size_bytes": path.stat().st_size}
        for path in sorted(sources.glob("*.csv"))
        if path.is_file()
    ]
    return {"sources": items}


def op_inspect_dataset(params: Params, store: ExperimentStore) -> dict[str, Any]:
    from drw.adapters.csv_adapter import CSV_ADAPTER, InspectionError

    path = _dataset_source_path(store, _param_str(params, "filename"))
    delimiter = params.get("delimiter") or None
    has_header = params.get("has_header")
    if has_header is not None and not isinstance(has_header, bool):
        raise ApiError("bad_request", "'has_header' must be a boolean when supplied")
    missing = params.get("missing_codes") or []
    if not isinstance(missing, list) or not all(
        isinstance(item, str) for item in missing
    ):
        raise ApiError("bad_request", "'missing_codes' must be a list of strings")
    try:
        inspection = CSV_ADAPTER.inspect(
            path,
            delimiter=delimiter,
            has_header=has_header,
            missing_codes=tuple(missing),
        )
    except InspectionError as exc:
        raise ApiError("bad_request", str(exc)) from exc
    return {"inspection": to_plain(inspection)}


def op_import_dataset(params: Params, store: ExperimentStore) -> dict[str, Any]:
    from drw.adapters.csv_adapter import (
        CsvImportConfig,
        DatasetImportError,
        import_csv,
    )
    from drw.dataset_store import DatasetStore

    path = _dataset_source_path(store, _param_str(params, "filename"))
    config_raw = _require(params, "config")
    try:
        config = CsvImportConfig.model_validate(config_raw)
    except PydanticValidationError as exc:
        raise ApiError(
            "bad_request",
            "the import configuration is not well formed",
            diagnostics=exc.errors(),
        ) from exc
    dry_run = bool(params.get("dry_run", False))
    datasets = DatasetStore(store.root)
    try:
        ref = import_csv(path, config, datasets, dry_run=dry_run)
    except DatasetImportError as exc:
        raise ApiError(
            "bad_request", str(exc), diagnostics=to_plain(exc.diagnostics)
        ) from exc
    data: dict[str, Any] = {
        "ref": to_plain(ref),
        "dry_run": dry_run,
        "stored": not dry_run,
    }
    if not dry_run:
        data["verification"] = to_plain(datasets.verify(ref.dataset_id))
    return data


def op_list_datasets(_params: Params, store: ExperimentStore) -> dict[str, Any]:
    from drw.dataset_store import DatasetStore

    datasets = DatasetStore(store.root)
    summaries: list[dict[str, Any]] = []
    for ref in datasets.list():
        item = to_plain(ref)
        try:
            item["source_kind"] = datasets.provenance(ref.dataset_id).source_kind
        except (ValueError, KeyError):
            item["source_kind"] = None
        summaries.append(item)
    return {"datasets": summaries}


def op_describe_dataset(params: Params, store: ExperimentStore) -> dict[str, Any]:
    from drw.dataset_store import DatasetStore

    dataset_id = _param_str(params, "dataset_id")
    datasets = DatasetStore(store.root)
    dataset = datasets.load(
        dataset_id
    )  # KeyError -> not_found; ValueError -> bad_request
    return {
        "ref": to_plain(datasets.ref(dataset_id)),
        "dataset": to_plain(dataset),
        "verification": to_plain(datasets.verify(dataset_id)),
    }


def op_verify_dataset(params: Params, store: ExperimentStore) -> dict[str, Any]:
    from drw.dataset_store import DatasetStore

    report = DatasetStore(store.root).verify(_param_str(params, "dataset_id"))
    return {"dataset_id": report.dataset_id, "verification": to_plain(report)}


def op_evaluate(params: Params, store: ExperimentStore) -> dict[str, Any]:
    from drw.dataset_store import DatasetStore
    from drw.evaluation import evaluate_run
    from drw.execution.environment import fingerprint_hash
    from drw.schema.evaluation import EvaluationConfig
    from drw.schema.observation import ObservationMapping
    from drw.schema.result import RunRecord

    experiment_id = _param_str(params, "experiment_id")
    run_id = str(params.get("run_id") or "baseline")
    try:
        mapping = ObservationMapping.model_validate(_require(params, "mapping"))
    except PydanticValidationError as exc:
        raise ApiError(
            "bad_request", "the mapping is not well formed", diagnostics=exc.errors()
        ) from exc
    try:
        config = EvaluationConfig.model_validate(params.get("config") or {})
    except PydanticValidationError as exc:
        raise ApiError(
            "bad_request",
            "the evaluation config is not well formed",
            diagnostics=exc.errors(),
        ) from exc

    loaded = store.load(experiment_id)  # KeyError -> not found
    spec = ExperimentSpec.model_validate(loaded["spec"])
    results = loaded["results"]
    schema = build_model(spec.model_ref.model_id).describe()
    runs = [RunRecord.model_validate(record) for record in results.get("runs", [])]
    if not runs:
        raise ApiError("bad_request", "the experiment has no runs to evaluate")
    if run_id == "baseline":
        run = runs[0]
    else:
        run = next(
            (candidate for candidate in runs if candidate.run_id == run_id), None
        )
        if run is None:
            raise ApiError(
                "bad_request", f"experiment {experiment_id!r} has no run {run_id!r}"
            )
    dataset = DatasetStore(store.root).load(mapping.dataset.dataset_id)
    result = evaluate_run(
        run,
        schema=schema,
        dataset=dataset,
        mapping=mapping,
        config=config,
        spec_hash=results.get("spec_hash", ""),
        environment_hash=fingerprint_hash(results.get("environment") or {}),
        model_hash=results.get("model_hash", ""),
    )
    return {"evaluation": to_plain(result)}


def op_calibrate(params: Params, store: ExperimentStore) -> dict[str, Any]:
    from drw.calibration import calibrate_for_experiment
    from drw.calibration_store import CalibrationStore
    from drw.jobs import InvalidJobId, JobJournal
    from drw.schema.calibration import CalibrationConfig

    experiment_id = _param_str(params, "experiment_id")
    try:
        config = CalibrationConfig.model_validate(_require(params, "config"))
    except PydanticValidationError as exc:
        raise ApiError(
            "bad_request",
            "the calibration config is not well formed",
            diagnostics=exc.errors(),
        ) from exc
    # The request experiment id is authoritative.
    config = config.model_copy(update={"experiment_id": experiment_id})
    persist = bool(params.get("persist", False))

    journal: JobJournal | None = None
    if params.get("job_id") is not None:
        try:
            journal = JobJournal(store.root, str(params["job_id"]))
        except InvalidJobId as exc:
            raise ApiError("bad_request", str(exc)) from exc
        journal.prune()
        journal.append(
            "started",
            total_runs=config.budget.max_evaluations,
            experiment_id=experiment_id,
        )

    result = calibrate_for_experiment(experiment_id, store, config, journal=journal)

    data: dict[str, Any] = {"calibration": to_plain(result)}
    if persist:
        data["ref"] = to_plain(CalibrationStore(store.root).save(result))
    if journal is not None:
        journal.append(
            "finished", status=result.status, evaluations=result.evaluations_completed
        )
    return data


def op_list_calibrations(_params: Params, store: ExperimentStore) -> dict[str, Any]:
    from drw.calibration_store import CalibrationStore

    return {"calibrations": to_plain(CalibrationStore(store.root).list())}


def op_get_calibration(params: Params, store: ExperimentStore) -> dict[str, Any]:
    from drw.calibration_store import CalibrationStore

    calibrations = CalibrationStore(store.root)
    calibration_id = _param_str(params, "calibration_id")
    return {
        "calibration": to_plain(calibrations.load(calibration_id)),
        "ref": to_plain(calibrations.ref(calibration_id)),
    }


def op_verify_calibration(params: Params, store: ExperimentStore) -> dict[str, Any]:
    from drw.calibration_store import CalibrationStore

    report = CalibrationStore(store.root).verify(_param_str(params, "calibration_id"))
    return {"verification": to_plain(report)}


def op_run_validation(params: Params, store: ExperimentStore) -> dict[str, Any]:
    from drw.jobs import InvalidJobId, JobJournal
    from drw.schema.validation import ValidationConfig
    from drw.validation import validate_for_experiment
    from drw.validation_store import ValidationStore

    experiment_id = _param_str(params, "experiment_id")
    try:
        config = ValidationConfig.model_validate(_require(params, "config"))
    except PydanticValidationError as exc:
        raise ApiError(
            "bad_request",
            "the validation config is not well formed",
            diagnostics=exc.errors(),
        ) from exc
    # The request experiment id is authoritative.
    config = config.model_copy(update={"experiment_id": experiment_id})
    persist = bool(params.get("persist", False))

    journal: JobJournal | None = None
    if params.get("job_id") is not None:
        try:
            journal = JobJournal(store.root, str(params["job_id"]))
        except InvalidJobId as exc:
            raise ApiError("bad_request", str(exc)) from exc
        journal.prune()
        journal.append(
            "started",
            total_runs=config.budget.max_evaluations,
            experiment_id=experiment_id,
        )

    result = validate_for_experiment(experiment_id, store, config)

    data: dict[str, Any] = {"validation": to_plain(result)}
    if persist:
        data["ref"] = to_plain(ValidationStore(store.root).save(result))
    if journal is not None:
        journal.append(
            "finished",
            status=result.agreement_status,
            evaluations=result.evaluations_completed,
        )
    return data


def op_list_validations(_params: Params, store: ExperimentStore) -> dict[str, Any]:
    from drw.validation_store import ValidationStore

    return {"validations": to_plain(ValidationStore(store.root).list())}


def op_get_validation(params: Params, store: ExperimentStore) -> dict[str, Any]:
    from drw.validation_store import ValidationStore

    validations = ValidationStore(store.root)
    validation_id = _param_str(params, "validation_id")
    return {
        "validation": to_plain(validations.load(validation_id)),
        "ref": to_plain(validations.ref(validation_id)),
    }


def op_verify_validation(params: Params, store: ExperimentStore) -> dict[str, Any]:
    from drw.validation_store import ValidationStore

    report = ValidationStore(store.root).verify(_param_str(params, "validation_id"))
    return {"verification": to_plain(report)}


def op_check_validation_staleness(
    params: Params, store: ExperimentStore
) -> dict[str, Any]:
    from drw.calibration_store import CalibrationStore
    from drw.dataset_store import DatasetStore
    from drw.validation_store import ValidationStore, check_validation_staleness

    validations = ValidationStore(store.root)
    result = validations.load(_param_str(params, "validation_id"))
    staleness = check_validation_staleness(
        result,
        calibration_store=CalibrationStore(store.root),
        dataset_store=DatasetStore(store.root),
    )
    return {"staleness": to_plain(staleness)}


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
            exc.code,
            exc.message,
            diagnostics=[{"code": exc.code, "questions": exc.questions}],
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


# ---------------------------------------------------------------------------
# Scientific Intelligence (SI) operations
# ---------------------------------------------------------------------------


def _si_guard(exc: Exception) -> ApiError:
    from drw.si.actions import SIActionError

    if isinstance(exc, SIActionError):
        return ApiError(exc.code, exc.message, diagnostics=exc.diagnostics)
    raise exc


def _si_scope(params: Params) -> tuple[str, str | None]:
    project_id = str(params.get("project_id") or DEFAULT_PROJECT_ID)
    model_id = params.get("model_id")
    return project_id, (str(model_id) if model_id else None)


def op_si_state(params: Params, store: ExperimentStore) -> dict[str, Any]:
    from drw.si import get_state

    investigation_id = _param_str(params, "investigation_id")
    project_id, model_id = _si_scope(params)
    try:
        state = get_state(store, investigation_id, project_id=project_id)
    except Exception as exc:
        raise _si_guard(exc) from exc
    data: dict[str, Any] = {"state": to_plain(state)}
    if model_id is not None:
        from drw.si.context import build_action_context

        ctx = build_action_context(
            store,
            investigation_id=investigation_id,
            project_id=project_id,
            model_id=model_id,
            state=state,
        )
        plan = state.current_plan()
        data["next_step_preview"] = (
            to_plain(_preview_for(plan.current_next_step(), ctx))
            if plan and plan.current_next_step()
            else None
        )
    return data


def _preview_for(step: Any, ctx: Any) -> Any:
    from drw.si.planner import preview_of

    return preview_of(step, ctx)


def op_si_ask(params: Params, store: ExperimentStore) -> dict[str, Any]:
    from drw.si import ask

    investigation_id = _param_str(params, "investigation_id")
    question = _param_str(params, "question")
    project_id, model_id = _si_scope(params)
    try:
        analysis, state = ask(
            store, investigation_id, question, project_id=project_id, model_id=model_id
        )
    except Exception as exc:
        raise _si_guard(exc) from exc
    return {"analysis": to_plain(analysis), "state": to_plain(state)}


def op_si_preview(params: Params, store: ExperimentStore) -> dict[str, Any]:
    from drw.si import preview_step

    investigation_id = _param_str(params, "investigation_id")
    step_id = _param_str(params, "step_id")
    project_id, model_id = _si_scope(params)
    plan_id = params.get("plan_id") or None
    try:
        preview = preview_step(
            store,
            investigation_id,
            step_id,
            project_id=project_id,
            model_id=model_id,
            plan_id=str(plan_id) if plan_id else None,
        )
    except Exception as exc:
        raise _si_guard(exc) from exc
    return {"preview": to_plain(preview)}


def op_si_execute(params: Params, store: ExperimentStore) -> dict[str, Any]:
    from drw.si import approve_and_execute

    investigation_id = _param_str(params, "investigation_id")
    step_id = _param_str(params, "step_id")
    project_id, model_id = _si_scope(params)
    plan_id = params.get("plan_id") or None
    approved = bool(params.get("approve", True))
    try:
        execution, interpretation, state = approve_and_execute(
            store,
            investigation_id,
            step_id,
            project_id=project_id,
            model_id=model_id,
            plan_id=str(plan_id) if plan_id else None,
            approved=approved,
        )
    except Exception as exc:
        raise _si_guard(exc) from exc
    return {
        "execution": to_plain(execution),
        "interpretation": to_plain(interpretation),
        "state": to_plain(state),
    }


def op_si_reject(params: Params, store: ExperimentStore) -> dict[str, Any]:
    from drw.si import reject_plan_step

    investigation_id = _param_str(params, "investigation_id")
    step_id = _param_str(params, "step_id")
    project_id, _model_id = _si_scope(params)
    plan_id = params.get("plan_id") or None
    try:
        state = reject_plan_step(
            store,
            investigation_id,
            step_id,
            project_id=project_id,
            plan_id=str(plan_id) if plan_id else None,
        )
    except Exception as exc:
        raise _si_guard(exc) from exc
    return {"state": to_plain(state)}


def op_si_actions(_params: Params, _store: ExperimentStore) -> dict[str, Any]:
    from drw.si import list_actions
    from drw.si.provider import provider_status as si_provider_status

    return {"actions": list_actions(), "provider": si_provider_status()}


def op_si_provider(_params: Params, _store: ExperimentStore) -> dict[str, Any]:
    from drw.si.provider import provider_status as si_provider_status

    return si_provider_status()


def op_environment(_params: Params, _store: ExperimentStore) -> dict[str, Any]:
    fingerprint = environment_fingerprint()
    return {
        "environment": fingerprint,
        "environment_hash": fingerprint_hash(fingerprint),
    }


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
    "reproduce_experiment": op_reproduce_experiment,
    "sensitivity": op_sensitivity,
    "uncertainty": op_uncertainty,
    "global_sensitivity": op_global_sensitivity,
    "identifiability": op_identifiability,
    "list_dataset_sources": op_list_dataset_sources,
    "inspect_dataset": op_inspect_dataset,
    "import_dataset": op_import_dataset,
    "list_datasets": op_list_datasets,
    "describe_dataset": op_describe_dataset,
    "get_dataset": op_describe_dataset,
    "verify_dataset": op_verify_dataset,
    "evaluate": op_evaluate,
    "calibrate": op_calibrate,
    "list_calibrations": op_list_calibrations,
    "get_calibration": op_get_calibration,
    "verify_calibration": op_verify_calibration,
    "run_validation": op_run_validation,
    "list_validations": op_list_validations,
    "get_validation": op_get_validation,
    "verify_validation": op_verify_validation,
    "check_validation_staleness": op_check_validation_staleness,
    "list_projects": op_list_projects,
    "create_project": op_create_project,
    "plan_experiment": op_plan_experiment,
    "planner_status": op_planner_status,
    "si_state": op_si_state,
    "si_ask": op_si_ask,
    "si_preview": op_si_preview,
    "si_execute": op_si_execute,
    "si_reject": op_si_reject,
    "si_actions": op_si_actions,
    "si_provider": op_si_provider,
    "environment": op_environment,
}


def _error(code: str, message: str, diagnostics: Any = ()) -> dict[str, Any]:
    return {
        "ok": False,
        "error": {"code": code, "message": message, "diagnostics": list(diagnostics)},
    }


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
