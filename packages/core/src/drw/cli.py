"""``python -m drw`` command line interface.

Subcommands map directly onto the documented MVP workflow:

    list-models, describe, validate, run, demo, export-schemas
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from drw.execution.evidence import build_evidence_package
from drw.execution.runner import ExperimentValidationError, Runner
from drw.models.registry import build_model, model_schemas
from drw.schema.experiment import estimate_run_count, validate_experiment
from drw.schema.files import load_experiment_spec
from drw.schema.serialization import dumps_pretty

__all__ = ["build_parser", "main"]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="drw",
        description="Differential Research Workbench - local scientific core.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("list-models", help="list registered reference models")

    describe = sub.add_parser("describe", help="print a model's typed contract")
    describe.add_argument("model")

    validate = sub.add_parser("validate", help="validate an experiment spec (no execution)")
    validate.add_argument("spec")

    run = sub.add_parser("run", help="run an experiment and export an evidence package")
    run.add_argument("spec")
    run.add_argument("--out", default=".drw/run", help="output directory for the evidence package")
    run.add_argument("--zip", action="store_true", dest="zip_bundle", help="also write a zip bundle")
    run.add_argument(
        "--isolation",
        choices=["in_process", "subprocess"],
        default=None,
        help="override execution.isolation (subprocess enforces the wall-clock timeout)",
    )

    demo = sub.add_parser("demo", help="run the killer demo (baseline vs +10 percent)")
    demo.add_argument("--model", default="predator-prey")
    demo.add_argument("--out", default=".drw/demo")
    demo.add_argument("--zip", action="store_true", dest="zip_bundle")

    export = sub.add_parser("export-schemas", help="export JSON Schemas for the typed contracts")
    export.add_argument("--out", default="packages/experiment-spec/schema")

    verify = sub.add_parser(
        "verify", help="verify an evidence package against its manifest (read-only)"
    )
    verify.add_argument("manifest", help="path to an evidence package manifest.json")

    reproduce = sub.add_parser(
        "reproduce",
        help="re-run a stored experiment and compare it to the stored reference (read-only)",
    )
    reproduce.add_argument("experiment_id")
    reproduce.add_argument(
        "--rtol",
        type=float,
        required=True,
        help="relative tolerance: pass criterion is |fresh-ref| <= atol + rtol*|ref|",
    )
    reproduce.add_argument(
        "--atol", type=float, required=True, help="absolute tolerance for the same criterion"
    )
    reproduce.add_argument(
        "--workspace",
        default=None,
        help="workspace root holding stored experiments (default: DRW_WORKSPACE)",
    )

    uncertainty = sub.add_parser(
        "uncertainty",
        help="descriptive uncertainty summary over a stored experiment's sampled design (read-only)",
    )
    uncertainty.add_argument("experiment_id")
    uncertainty.add_argument(
        "--workspace",
        default=None,
        help="workspace root holding stored experiments (default: DRW_WORKSPACE)",
    )

    from drw.global_sensitivity import DEFAULT_BOOTSTRAP, DEFAULT_SAMPLE_COUNT

    sobol = sub.add_parser(
        "sobol",
        help="global variance-based (Sobol) sensitivity study for a stored experiment (read-only)",
    )
    sobol.add_argument("experiment_id")
    sobol.add_argument(
        "--output", default=None, help="scalar output to analyse (default: primary scalar output)"
    )
    sobol.add_argument(
        "--factors",
        default=None,
        help="comma-separated factor names (default: all bounded numeric parameters)",
    )
    sobol.add_argument(
        "--n",
        type=int,
        default=DEFAULT_SAMPLE_COUNT,
        help=f"base sample size N; evaluations = N*(d+2) (default {DEFAULT_SAMPLE_COUNT})",
    )
    sobol.add_argument("--seed", type=int, default=0, help="quasi-Monte Carlo seed")
    sobol.add_argument(
        "--bootstrap",
        type=int,
        default=DEFAULT_BOOTSTRAP,
        help=f"bootstrap resamples for the diagnostic interval (default {DEFAULT_BOOTSTRAP})",
    )
    sobol.add_argument(
        "--workspace",
        default=None,
        help="workspace root holding stored experiments (default: DRW_WORKSPACE)",
    )

    from drw.identifiability import (
        CONDITION_THRESHOLD,
        DEFAULT_RANK_TOLERANCE,
        DEFAULT_STEP_SCALE,
    )

    identifiability = sub.add_parser(
        "identifiability",
        help="local parameter identifiability study for a stored experiment (read-only)",
    )
    identifiability.add_argument("experiment_id")
    identifiability.add_argument(
        "--factors",
        default=None,
        help="comma-separated parameter names (default: all bounded continuous parameters)",
    )
    identifiability.add_argument(
        "--outputs",
        default=None,
        help="comma-separated output names (default: every scalar/time-series output)",
    )
    identifiability.add_argument(
        "--step-scale",
        type=float,
        default=DEFAULT_STEP_SCALE,
        help=f"relative finite-difference step h = max(step-scale*|theta|, absolute) (default {DEFAULT_STEP_SCALE:g})",
    )
    identifiability.add_argument("--seed", type=int, default=0, help="accepted for interface parity")
    identifiability.add_argument(
        "--rank-tolerance",
        type=float,
        default=DEFAULT_RANK_TOLERANCE,
        help=f"relative singular-value tolerance for the numerical rank (default {DEFAULT_RANK_TOLERANCE:g})",
    )
    identifiability.add_argument(
        "--condition-threshold",
        type=float,
        default=CONDITION_THRESHOLD,
        help=f"condition number above which the result is 'ill-conditioned' (default {CONDITION_THRESHOLD:g})",
    )
    identifiability.add_argument(
        "--workspace",
        default=None,
        help="workspace root holding stored experiments (default: DRW_WORKSPACE)",
    )

    dataset = sub.add_parser(
        "dataset", help="inspect and import scientific datasets (CSV), and manage stored datasets"
    )
    dataset_sub = dataset.add_subparsers(dest="dataset_command", required=True)

    ds_inspect = dataset_sub.add_parser(
        "inspect", help="inspect a CSV file (advisory; does not persist anything)"
    )
    ds_inspect.add_argument("file")
    ds_inspect.add_argument("--delimiter", default=None, help="field delimiter (default: sniff)")
    ds_inspect.add_argument(
        "--no-header", action="store_true", dest="no_header", help="the file has no header row"
    )
    ds_inspect.add_argument(
        "--missing-code",
        action="append",
        default=[],
        dest="missing_codes",
        help="treat this cell value as missing (repeatable)",
    )
    ds_inspect.add_argument("--json", action="store_true", dest="as_json", help="emit JSON")

    ds_import = dataset_sub.add_parser("import", help="import a CSV file as an immutable dataset")
    ds_import.add_argument("file")
    ds_import.add_argument("--config", required=True, help="path to a JSON import configuration")
    ds_import.add_argument(
        "--dry-run", action="store_true", dest="dry_run", help="validate only; write nothing"
    )
    ds_import.add_argument("--workspace", default=None)

    ds_list = dataset_sub.add_parser("list", help="list stored datasets")
    ds_list.add_argument("--workspace", default=None)
    ds_list.add_argument("--json", action="store_true", dest="as_json")

    ds_describe = dataset_sub.add_parser("describe", help="describe a stored dataset")
    ds_describe.add_argument("dataset_id")
    ds_describe.add_argument("--workspace", default=None)
    ds_describe.add_argument("--json", action="store_true", dest="as_json")

    ds_verify = dataset_sub.add_parser("verify", help="verify a stored dataset (read-only)")
    ds_verify.add_argument("dataset_id")
    ds_verify.add_argument("--workspace", default=None)

    evaluate = sub.add_parser(
        "evaluate",
        help="evaluate a stored experiment run against a dataset (read-only; execution-free)",
    )
    evaluate.add_argument("experiment_id")
    evaluate.add_argument("--run", default="baseline", help="run id, or 'baseline'")
    evaluate.add_argument("--mapping", required=True, help="path to an ObservationMapping JSON file")
    evaluate.add_argument("--metric", action="append", default=None, dest="metrics", help="metric (repeatable)")
    evaluate.add_argument("--relative", action="store_true", dest="relative", help="include relative residuals/metrics")
    evaluate.add_argument("--weighted", action="store_true", dest="weighted", help="include normalized (weighted) residuals/metrics")
    evaluate.add_argument("--interpolate", action="store_true", dest="interpolate", help="allow opt-in linear interpolation")
    evaluate.add_argument("--tolerance", type=float, default=0.0, dest="tolerance")
    evaluate.add_argument("--time-origin", default=None, dest="time_origin")
    evaluate.add_argument("--dof", type=int, default=None, dest="dof")
    evaluate.add_argument("--dry-run", action="store_true", dest="dry_run", help="validate and report diagnostics only")
    evaluate.add_argument("--json", action="store_true", dest="as_json")
    evaluate.add_argument("--workspace", default=None)

    calibrate = sub.add_parser(
        "calibrate",
        help="calibrate model parameters against a dataset (serial, bounded; read-only w.r.t. the experiment)",
    )
    calibrate.add_argument("experiment_id")
    calibrate.add_argument("--config", required=True, help="path to a CalibrationConfig JSON file")
    calibrate.add_argument(
        "--dry-run",
        action="store_true",
        dest="dry_run",
        help="validate configuration, dataset, mapping and objective; execute no model runs",
    )
    calibrate.add_argument("--persist", action="store_true", help="store the calibration result")
    calibrate.add_argument("--json", action="store_true", dest="as_json")
    calibrate.add_argument("--workspace", default=None)

    validation = sub.add_parser(
        "validation",
        help="validate a frozen calibration against independent datasets (read-only; no refit)",
    )
    vsub = validation.add_subparsers(dest="validation_command", required=True)

    vrun = vsub.add_parser(
        "run",
        help="run a validation: frozen parameters, independent datasets, M12A evaluation",
    )
    vrun.add_argument("experiment_id")
    vrun.add_argument("--config", required=True, help="path to a ValidationConfig JSON file")
    vrun.add_argument(
        "--dry-run",
        action="store_true",
        dest="dry_run",
        help="validate config, calibration, datasets, mappings and independence; execute nothing",
    )
    vrun.add_argument("--persist", action="store_true", help="store the validation result")
    vrun.add_argument("--json", action="store_true", dest="as_json")
    vrun.add_argument("--workspace", default=None)

    vlist = vsub.add_parser("list", help="list stored validations")
    vlist.add_argument("--json", action="store_true", dest="as_json")
    vlist.add_argument("--workspace", default=None)

    vget = vsub.add_parser("get", help="print a stored validation")
    vget.add_argument("validation_id")
    vget.add_argument("--json", action="store_true", dest="as_json")
    vget.add_argument("--workspace", default=None)

    vverify = vsub.add_parser("verify", help="verify a stored validation against its manifest")
    vverify.add_argument("validation_id")
    vverify.add_argument("--json", action="store_true", dest="as_json")
    vverify.add_argument("--workspace", default=None)

    vstale = vsub.add_parser("staleness", help="report whether a stored validation is still current")
    vstale.add_argument("validation_id")
    vstale.add_argument("--json", action="store_true", dest="as_json")
    vstale.add_argument("--workspace", default=None)

    return parser


def _cmd_list_models(_args: argparse.Namespace) -> int:
    for model_id, schema in sorted(model_schemas().items()):
        print(f"{model_id:<16} v{schema.version:<8} {schema.description}")
    return 0


def _cmd_describe(args: argparse.Namespace) -> int:
    schema = build_model(args.model).describe()
    print(f"# {schema.model_id} v{schema.version}")
    print(schema.description)
    print(f"runtime: {schema.runtime}")
    print("\nParameters:")
    print(f"  {'name':<14} {'type':<12} {'role':<8} {'unit':<16} {'nominal':>10} "
          f"{'lower':>10} {'upper':>10}")
    for param in schema.parameters:
        bounds = (
            f"{param.lower:>10g} {param.upper:>10g}"
            if param.lower is not None and param.upper is not None
            else f"{'-':>10} {'-':>10}"
        )
        print(
            f"  {param.name:<14} {param.type:<12} {param.role:<8} {param.unit:<16} "
            f"{param.nominal!s:>10} {bounds}"
        )
    print("\nOutputs:")
    for output in schema.outputs:
        print(f"  {output.name:<18} {output.kind:<12} {output.unit}")
    return 0


def _cmd_validate(args: argparse.Namespace) -> int:
    spec = load_experiment_spec(args.spec)
    adapter = build_model(spec.model_ref.model_id)
    diagnostics = validate_experiment(spec, adapter.describe())
    estimate = estimate_run_count(spec)
    print(f"estimated runs: {estimate.total_runs} (method={estimate.method})")
    if not diagnostics:
        print("no diagnostics: spec is valid")
    for diagnostic in diagnostics:
        marker = {"info": "INFO", "warning": "WARN", "error": "ERROR"}[diagnostic.level]
        print(f"[{marker}] {diagnostic.code}: {diagnostic.message}")
    return 1 if any(d.level == "error" for d in diagnostics) else 0


def _cmd_run(args: argparse.Namespace) -> int:
    spec = load_experiment_spec(args.spec)
    if args.isolation is not None:
        spec = spec.model_copy(
            update={"execution": spec.execution.model_copy(update={"isolation": args.isolation})}
        )
    runner = Runner()
    try:
        result = runner.run(spec)
    except ExperimentValidationError as exc:
        for diagnostic in exc.diagnostics:
            print(f"[ERROR] {diagnostic.code}: {diagnostic.message}", file=sys.stderr)
        return 1

    manifest = build_evidence_package(result, args.out, zip_bundle=args.zip_bundle)
    print(f"experiment: {result.experiment_id}")
    print(f"isolation: {result.isolation}")
    print(f"runs: {len(result.runs)} ({len(result.succeeded_runs)} succeeded, "
          f"{len(result.failed_runs)} failed)")
    print(f"comparisons: {len(result.comparisons)}")
    for comparison in result.comparisons:
        print(
            f"  {comparison.variant_run_id} {comparison.output}: "
            f"max_abs_delta={comparison.metrics['max_abs_delta']:.6g} "
            f"mae={comparison.metrics['mae']:.6g}"
        )
    print(f"evidence manifest: {manifest}")
    return 0 if result.baseline.succeeded else 1


def _cmd_demo(args: argparse.Namespace) -> int:
    from drw.demo import run_demo

    summary = run_demo(args.model, args.out, zip_bundle=args.zip_bundle)
    result = summary["result"]
    print(f"experiment: {summary['experiment_id']} (model={args.model})")
    print(f"isolation: {result.isolation}")
    print(f"runs: {len(result.runs)}; comparisons: {len(result.comparisons)}")
    print(f"evidence manifest: {summary['manifest']}")
    print(f"sensitivity metric: {summary['primary_output']} (perturbation +10%)")
    print("parameter sensitivity ranking (|delta|, most influential first):")
    for row in summary["ranking"]:
        elasticity = row.get("elasticity")
        elasticity_text = "n/a" if elasticity is None else f"{elasticity:+.4g}"
        clamped = " [clamped to bounds]" if row.get("clamped") else ""
        print(
            f"  {row['parameter']:<12} abs_delta={row['abs_delta']:.6g} "
            f"elasticity={elasticity_text}{clamped}"
        )
    print(f"sensitivity artifact: {Path(args.out) / 'sensitivity.json'}")
    return 0


def _cmd_export_schemas(args: argparse.Namespace) -> int:
    from drw.schema.experiment import ExperimentSpec
    from drw.schema.model import ModelSchema

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    targets = {"model-schema.schema.json": ModelSchema, "experiment-spec.schema.json": ExperimentSpec}
    for filename, model in targets.items():
        path = out / filename
        path.write_text(dumps_pretty(model.model_json_schema()) + "\n", encoding="utf-8")
        print(f"wrote {path}")
    return 0


def _cmd_verify(args: argparse.Namespace) -> int:
    from drw.execution.evidence import verify_evidence

    report = verify_evidence(args.manifest)
    print(f"manifest: {report.manifest}")
    if report.experiment_id:
        print(f"experiment: {report.experiment_id}")
    detail_by_status = {
        "size_mismatch": lambda a: (
            f" (expected {a.expected_size_bytes} bytes, got {a.actual_size_bytes})"
        ),
        "hash_mismatch": lambda a: " (sha256 does not match)",
        "invalid_path": lambda a: " (path escapes the manifest directory)",
        "invalid_entry": lambda a: " (malformed manifest entry)",
    }
    for artifact in report.artifacts:
        describe = detail_by_status.get(artifact.status)
        detail = describe(artifact) if describe is not None else ""
        print(f"[{artifact.status.upper()}] {artifact.path}{detail}")
    if report.extra_files:
        print("undeclared files (present but not verified):")
        for name in report.extra_files:
            print(f"  {name}")
    verdict = "OK" if report.ok else "FAILED"
    print(f"result: {verdict} ({report.verified} verified, {report.failed} failed)")
    return 0 if report.ok else 1


def _g(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.6g}"


def _cmd_reproduce(args: argparse.Namespace) -> int:
    from drw.reproduce import reproduce_experiment
    from drw.store import ExperimentStore, default_store

    store = ExperimentStore(args.workspace) if args.workspace else default_store()
    report = reproduce_experiment(
        args.experiment_id, rtol=args.rtol, atol=args.atol, store=store
    )

    print(f"experiment: {report.experiment_id}")
    print(f"tolerances: rtol={report.tolerances.rtol:g} atol={report.tolerances.atol:g}")
    print(f"verdict: {report.verdict}")
    print(f"reference runs (stored): {', '.join(report.reference_run_ids) or '-'}")
    print(f"fresh runs (in-memory, not persisted): {', '.join(report.fresh_run_ids) or '-'}")
    if report.reference_run_ids and report.reference_run_ids == report.fresh_run_ids:
        print(
            "note: the fresh run ids equal the stored ids because the deterministic "
            "experiment id is derived from the specification; only the stored runs exist "
            "on disk - the fresh result is not a separately stored run."
        )
    for run in report.runs:
        if run.identical:
            state = "identical"
        elif run.passes_tolerance:
            state = "within tolerance"
        elif run.comparable:
            state = "different"
        else:
            state = "incomparable"
        print(f"  run {run.index} [{run.label}] {run.reference_run_id} -> {run.fresh_run_id or '-'}: {state}")
        for output in run.outputs:
            print(
                f"    {output.output} ({output.unit}): {output.status} "
                f"max_abs_delta={_g(output.max_abs_delta)} mae={_g(output.mae)} "
                f"rmse={_g(output.rmse)} passes={output.passes_tolerance}"
            )
    provenance = report.provenance
    print("provenance:")
    print(f"  spec hash match: {provenance.spec_hash_match}")
    print(f"  model hash match: {provenance.model_hash_match}")
    print(f"  environment hash match: {provenance.environment_hash_match}")
    for difference in provenance.differences:
        print(f"  - {difference}")
    for warning in report.warnings:
        print(f"warning: {warning}")
    print(
        "note: numerical agreement is not scientific validity, and the original stored "
        "result was not modified."
    )

    if report.verdict in ("identical", "equivalent_within_tolerance"):
        return 0
    if report.verdict == "different":
        return 1
    return 2


def _cmd_uncertainty(args: argparse.Namespace) -> int:
    from drw.store import ExperimentStore, default_store
    from drw.uncertainty import uncertainty_for_experiment

    store = ExperimentStore(args.workspace) if args.workspace else default_store()
    summary = uncertainty_for_experiment(args.experiment_id, store)

    print(
        f"sampling: {summary.sampling_method} seed={summary.seed} "
        f"variants={summary.requested_variants} "
        f"valid_output_samples={summary.valid_output_samples} "
        f"excluded_output_samples={summary.excluded_output_samples}"
    )
    print(
        "note: requested_variants is a per-run count; valid/excluded output-samples "
        "are totals across the declared scalar outputs"
    )
    print(f"quantiles: {summary.quantiles} (method {summary.quantile_method})")
    header = f"  {'output':<16} {'unit':<12} {'valid':>5} {'mean':>12} {'std':>12} {'min':>12} {'max':>12} {'p05':>12} {'p50':>12} {'p95':>12}"
    print(header)
    for output in summary.outputs:
        values = " ".join(
            f"{_g(value):>12}"
            for value in (output.mean, output.std, output.minimum, output.maximum, output.p05, output.p50, output.p95)
        )
        print(f"  {output.output:<16} {output.unit:<12} {output.valid_samples:>5} {values}")
        if output.exclusions:
            print(f"      exclusions: {output.exclusions}")
        if output.note:
            print(f"      note: {output.note}")
    if summary.note:
        print(f"note: {summary.note}")
    print(
        "descriptive summary of the sampled design; not a probabilistic guarantee or "
        "scientific validation."
    )
    return 0


def _ci(interval: tuple[float, float] | None) -> str:
    if interval is None:
        return "n/a"
    return f"[{interval[0]:.4f}, {interval[1]:.4f}]"


def _cmd_sobol(args: argparse.Namespace) -> int:
    from drw.global_sensitivity import sobol_indices_for_experiment
    from drw.store import ExperimentStore, default_store

    store = ExperimentStore(args.workspace) if args.workspace else default_store()
    factors = [item.strip() for item in args.factors.split(",")] if args.factors else None
    report = sobol_indices_for_experiment(
        args.experiment_id,
        store,
        output=args.output,
        factors=factors,
        sample_count=args.n,
        seed=args.seed,
        bootstrap_resamples=args.bootstrap,
    )

    print(f"output: {report.output}  estimator: {report.estimator}")
    print(
        f"design: N={report.sample_count} d={report.dimensions} seed={report.seed} "
        f"evaluations={report.evaluations_requested} completed={report.evaluations_completed}"
    )
    print(f"variance: {_g(report.variance)}")
    if report.inconclusive:
        print("result: INCONCLUSIVE (indices not estimated)")
        for reason in report.reasons:
            print(f"  - {reason}")
        return 2
    print(f"  {'factor':<16} {'S1':>10} {'S1 95% CI':>22} {'ST':>10} {'ST 95% CI':>22}")
    for row in report.results:
        s1 = "n/a" if row.s1 is None else f"{row.s1:.4f}"
        st = "n/a" if row.st is None else f"{row.st:.4f}"
        print(f"  {row.name:<16} {s1:>10} {_ci(row.s1_ci):>22} {st:>10} {_ci(row.st_ci):>22}")
    if report.note:
        print(f"note: {report.note}")
    print(
        "finite-sample variance-based estimates (independent inputs assumed); "
        "not causal and not proof of convergence."
    )
    return 0


def _cmd_identifiability(args: argparse.Namespace) -> int:
    from drw.identifiability import identifiability_for_experiment
    from drw.store import ExperimentStore, default_store

    store = ExperimentStore(args.workspace) if args.workspace else default_store()
    factors = [item.strip() for item in args.factors.split(",")] if args.factors else None
    outputs = [item.strip() for item in args.outputs.split(",")] if args.outputs else None
    report = identifiability_for_experiment(
        args.experiment_id,
        store,
        factors=factors,
        outputs=outputs,
        step_scale=args.step_scale,
        seed=args.seed,
        rank_tolerance=args.rank_tolerance,
        condition_threshold=args.condition_threshold,
    )

    print(f"experiment: {report.experiment_id}  method: {report.method}")
    print(f"verdict: {report.verdict.upper()}")
    print(
        f"factors: {', '.join(report.factors)}  "
        f"evaluations: {report.evaluations_completed}/{report.evaluations_requested}"
    )
    print(
        f"thresholds: rank_tolerance={report.rank_tolerance:g} "
        f"condition_threshold={report.condition_threshold:g}"
    )
    if report.inconclusive:
        print("result: INCONCLUSIVE (identifiability not established)")
        for reason in report.reasons:
            print(f"  - {reason}")
        return 2

    print(f"targets: {report.n_targets} informative of {len(report.targets)}")
    print(
        f"numerical rank: {report.numerical_rank}/{report.dimensions}  "
        f"condition number: {_g(report.condition_number)}"
    )
    print("singular values: " + ", ".join(f"{value:.6g}" for value in report.singular_values))
    problematic = [direction for direction in report.directions if direction.problematic]
    if problematic:
        print("poorly distinguishable directions (local):")
        for direction in problematic:
            weights = ", ".join(
                f"{name}={weight:.3f}" for name, weight in direction.weights.items()
            )
            print(
                f"  direction {direction.index}: sigma={_g(direction.singular_value)} "
                f"condition_index={_g(direction.condition_index)} weights: {weights}"
            )
    else:
        print("no poorly distinguishable direction was detected")
    for pair in report.factor_correlations:
        print(f"collinear pair {pair.first}/{pair.second}: correlation={pair.correlation:+.4f}")
    if report.note:
        print(f"note: {report.note}")
    print(
        "local (linearised) structural identifiability only; not global identifiability, "
        "not practical identifiability from noisy data, and not a statement that the model "
        "is scientifically valid."
    )
    return 0


def _cmd_dataset(args: argparse.Namespace) -> int:
    from drw.adapters.csv_adapter import CSV_ADAPTER, CsvImportConfig, import_csv
    from drw.dataset_store import DatasetStore, default_dataset_store

    command = getattr(args, "dataset_command", None)
    if command == "inspect":
        inspection = CSV_ADAPTER.inspect(
            args.file,
            delimiter=args.delimiter,
            has_header=False if args.no_header else None,
            missing_codes=tuple(args.missing_codes),
        )
        if args.as_json:
            print(dumps_pretty(inspection.model_dump(mode="json")))
            return 0
        print(
            f"{inspection.filename}: delimiter={inspection.delimiter!r} "
            f"header={inspection.has_header} rows={inspection.row_count} "
            f"columns={len(inspection.columns)}"
        )
        print(f"  {'column':<20} {'kind':<11} {'missing':>7} {'nonfinite':>9}  suggested")
        for column in inspection.columns:
            suggestion = column.suggested_role or ""
            if column.suggested_uncertainty_for:
                suggestion += f" (of {column.suggested_uncertainty_for})"
            print(
                f"  {column.column:<20} {column.kind:<11} {column.missing_count:>7} "
                f"{column.non_finite_count:>9}  {suggestion}"
            )
        for diagnostic in inspection.diagnostics:
            print(f"[{diagnostic.level.upper()}] {diagnostic.code}: {diagnostic.message}")
        print("note: detections are advisory; supply an explicit configuration to import.")
        return 0

    store = DatasetStore(args.workspace) if args.workspace else default_dataset_store()

    if command == "import":
        try:
            raw = json.loads(Path(args.config).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(f"could not read config {args.config!r}: {exc}") from exc
        config = CsvImportConfig.model_validate(raw)
        ref = import_csv(args.file, config, store, dry_run=args.dry_run)
        if args.dry_run:
            print(f"validated (dry run): {ref.dataset_id} content_hash={ref.content_hash}")
            print("no dataset was written")
        else:
            print(f"imported dataset: {ref.dataset_id}")
            print(f"  name: {ref.name}")
            print(f"  content_hash: {ref.content_hash}")
            print(f"  created_at: {ref.created_at}")
        return 0

    if command == "list":
        refs = store.list()
        if args.as_json:
            print(dumps_pretty([ref.model_dump(mode="json") for ref in refs]))
            return 0
        if not refs:
            print("no datasets")
            return 0
        for ref in refs:
            print(f"{ref.dataset_id}  {ref.name}  {ref.created_at}  {ref.content_hash[:12]}")
        return 0

    if command == "describe":
        dataset = store.load(args.dataset_id)
        ref = store.ref(args.dataset_id)
        if args.as_json:
            print(dumps_pretty({"ref": ref.model_dump(mode="json"), "dataset": dataset.model_dump(mode="json")}))
            return 0
        print(f"dataset: {ref.dataset_id}  name={ref.name!r}")
        print(f"content_hash: {ref.content_hash}")
        print(f"created_at: {ref.created_at}  schema_version: {dataset.schema_version}")
        provenance = dataset.provenance
        print(
            f"provenance: source_kind={provenance.source_kind} "
            f"adapter={provenance.adapter} imported_at={provenance.imported_at}"
        )
        print("variables:")
        for variable in dataset.observation_set.variables:
            unit = variable.unit if variable.unit is not None else "(unspecified)"
            extra = ""
            if variable.uncertainty is not None:
                extra += f" uncertainty={variable.uncertainty.type}"
            if variable.quality is not None:
                extra += f" quality={variable.quality.flag_column}"
            print(
                f"  {variable.name:<20} {variable.kind:<11} {variable.role:<12} "
                f"unit={unit:<12} depends_on=[{','.join(variable.depends_on)}]{extra}"
            )
        print(f"rows: {dataset.observation_set.row_count}  files: {len(dataset.files)}")
        return 0

    if command == "verify":
        report = store.verify(args.dataset_id)
        for check in report.checks:
            suffix = f" - {check.message}" if check.message else ""
            print(f"[{check.status.upper()}] {check.name}{suffix}")
        if report.extra_files:
            print(f"extra files (not verified): {', '.join(report.extra_files)}")
        print(f"result: {'OK' if report.ok else 'FAILED'} ({report.errors} error(s))")
        return 0 if report.ok else 1

    print(f"error: unknown dataset command {command!r}", file=sys.stderr)
    return 2


def _cmd_evaluate(args: argparse.Namespace) -> int:
    from drw.dataset_store import DatasetStore, default_dataset_store
    from drw.evaluation import evaluate_run
    from drw.execution.environment import fingerprint_hash
    from drw.schema.evaluation import CORE_METRICS, EvaluationConfig
    from drw.schema.experiment import ExperimentSpec
    from drw.schema.observation import ObservationMapping
    from drw.schema.result import RunRecord
    from drw.store import ExperimentStore, default_store

    store = ExperimentStore(args.workspace) if args.workspace else default_store()
    datasets = DatasetStore(args.workspace) if args.workspace else default_dataset_store()

    loaded = store.load(args.experiment_id)
    spec = ExperimentSpec.model_validate(loaded["spec"])
    results = loaded["results"]
    schema = build_model(spec.model_ref.model_id).describe()
    runs = [RunRecord.model_validate(record) for record in results.get("runs", [])]
    if not runs:
        raise ValueError("the experiment has no runs to evaluate")
    if args.run == "baseline":
        run = runs[0]
    else:
        run = next((candidate for candidate in runs if candidate.run_id == args.run), None)
        if run is None:
            raise ValueError(f"experiment {args.experiment_id!r} has no run {args.run!r}")

    try:
        raw_mapping = json.loads(Path(args.mapping).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"could not read mapping {args.mapping!r}: {exc}") from exc
    mapping = ObservationMapping.model_validate(raw_mapping)
    dataset = datasets.load(mapping.dataset.dataset_id)

    residual_modes = ["raw"]
    if args.relative:
        residual_modes.append("relative")
    if args.weighted:
        residual_modes.append("normalized")
    metrics = tuple(args.metrics) if args.metrics else CORE_METRICS
    config = EvaluationConfig(
        metrics=metrics,
        residual_modes=tuple(residual_modes),
        alignment="interpolate" if args.interpolate else "exact",
        alignment_tolerance=args.tolerance,
        time_origin=args.time_origin,
        degrees_of_freedom=args.dof,
    )
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

    if args.as_json:
        print(dumps_pretty(result.model_dump(mode="json")))
        return 0 if result.ok else 1

    print(f"experiment: {result.experiment_id}  run: {result.run_id}  ok: {result.ok}")
    print(f"dataset: {result.dataset.dataset_id}  mapping_hash: {result.mapping_hash[:12]}…")
    if args.dry_run:
        for diagnostic in result.diagnostics:
            print(f"[{diagnostic.level.upper()}] {diagnostic.code}: {diagnostic.message}")
        return 0 if result.ok else 1

    for pair in result.pairs:
        print(
            f"  {pair.observation} -> {pair.output} ({pair.kind}, {pair.unit}, {pair.alignment}): "
            f"usable={pair.usable_count} excluded={pair.excluded_count}"
            + (" [interpolated]" if pair.interpolated else "")
        )
        for name, value in pair.metrics.items():
            print(f"      {name}: {'null' if value is None else f'{value:.6g}'}")
        if pair.exclusion_counts:
            print(f"      exclusions: {pair.exclusion_counts}")
    for diagnostic in result.diagnostics:
        print(f"[{diagnostic.level.upper()}] {diagnostic.code}: {diagnostic.message}")
    if not result.ok:
        print("result: NOT VALID (no metrics were produced)")
    return 0 if result.ok else 1


def _cmd_calibrate(args: argparse.Namespace) -> int:
    from drw.calibration import calibrate_for_experiment, resolve_objective_pair
    from drw.calibration_store import CalibrationStore
    from drw.dataset_store import DatasetStore, default_dataset_store
    from drw.schema.calibration import CalibrationConfig, validate_calibration_config
    from drw.schema.experiment import ExperimentSpec
    from drw.store import ExperimentStore, default_store

    store = ExperimentStore(args.workspace) if args.workspace else default_store()
    datasets = DatasetStore(args.workspace) if args.workspace else default_dataset_store()

    try:
        raw_config = json.loads(Path(args.config).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"could not read calibration config {args.config!r}: {exc}") from exc
    config = CalibrationConfig.model_validate(raw_config)
    # The command-line experiment id is authoritative.
    config = config.model_copy(update={"experiment_id": args.experiment_id})

    loaded = store.load(args.experiment_id)
    spec = ExperimentSpec.model_validate(loaded["spec"])
    schema = build_model(spec.model_ref.model_id).describe()

    if args.dry_run:
        diagnostics = validate_calibration_config(config, schema, dict(spec.baseline))
        datasets.load(config.dataset.dataset_id)  # KeyError -> not found
        pair = resolve_objective_pair(config.objective, config.mapping)
        if not diagnostics:
            print("no diagnostics: calibration is ready to run")
        for diagnostic in diagnostics:
            print(f"[{diagnostic.level.upper()}] {diagnostic.code}: {diagnostic.message}")
        print(
            f"dry run: free={[item.name for item in config.free]} "
            f"optimizer={config.optimizer.name} metric={pair.observation}->{pair.output} "
            f"({config.objective.metric}) budget={config.budget.max_evaluations}"
        )
        print("dry run: no model runs were executed")
        return 2 if any(d.level == "error" for d in diagnostics) else 0

    result = calibrate_for_experiment(args.experiment_id, store, config)
    ref = CalibrationStore(store.root).save(result) if args.persist else None

    if args.as_json:
        payload = result.model_dump(mode="json")
        if ref is not None:
            payload["calibration_id"] = ref.calibration_id
        print(dumps_pretty(payload))
        return 0 if result.best is not None else 1

    print(f"experiment: {result.experiment_id}  status: {result.status}  "
          f"stop_reason: {result.stop_reason}  converged: {result.converged}")
    print(
        f"evaluations: {result.evaluations_completed} completed, "
        f"{result.evaluations_invalid} invalid (cap {result.evaluations_requested})  "
        f"iterations: {result.iterations}  wall: {result.wall_seconds:.3f}s"
    )
    if result.best is not None:
        params = ", ".join(f"{name}={value:.6g}" for name, value in result.best.parameters.items())
        print(f"best objective ({result.objective.metric}): {result.objective.value:.6g}")
        print(f"best parameters: {params}")
    else:
        print("no usable best candidate was found")
    if result.identifiability is not None:
        print(f"identifiability: {result.identifiability['verdict']} (advisory)")
    for diagnostic in result.diagnostics:
        print(f"[{diagnostic.level.upper()}] {diagnostic.code}: {diagnostic.message}")
    if ref is not None:
        print(f"stored calibration: {ref.calibration_id}")
    print(f"note: {result.note}")
    return 0 if result.best is not None else 1


def _cmd_validation(args: argparse.Namespace) -> int:
    from drw.calibration_store import CalibrationStore
    from drw.dataset_store import DatasetStore, default_dataset_store
    from drw.observations import validate_mapping
    from drw.schema.experiment import ExperimentSpec
    from drw.schema.validation import ValidationConfig, validate_validation_config
    from drw.store import ExperimentStore, default_store
    from drw.validation import validate_for_experiment
    from drw.validation.independence import evaluate_independence
    from drw.validation_store import (
        ValidationStore,
        check_validation_staleness,
        default_validation_store,
    )

    command = getattr(args, "validation_command", None)
    workspace = args.workspace

    if command in ("list", "get", "verify", "staleness"):
        vstore = ValidationStore(workspace) if workspace else default_validation_store()
        if command == "list":
            refs = vstore.list()
            if args.as_json:
                print(dumps_pretty([ref.model_dump(mode="json") for ref in refs]))
            else:
                for ref in refs:
                    print(
                        f"{ref.validation_id}  {ref.agreement_status:<12} "
                        f"exp={ref.experiment_id}"
                    )
            return 0
        if command == "get":
            ref = vstore.ref(args.validation_id)
            result = vstore.load(args.validation_id)
            if args.as_json:
                payload = result.model_dump(mode="json")
                payload["validation_id"] = ref.validation_id
                print(dumps_pretty(payload))
            else:
                print(
                    f"{ref.validation_id}  agreement={result.agreement_status}  "
                    f"acceptance={result.acceptance_status}  "
                    f"independence={result.independence_status}"
                )
                for item in result.datasets:
                    print(f"  {item.label or item.dataset.dataset_id}: {item.metrics}")
            return 0
        if command == "verify":
            report = vstore.verify(args.validation_id)
            if args.as_json:
                print(dumps_pretty(report.model_dump(mode="json")))
            else:
                for check in report.checks:
                    print(f"[{check.status.upper()}] {check.name}: {check.message}")
            return 0 if report.ok else 1
        result = vstore.load(args.validation_id)
        staleness = check_validation_staleness(
            result,
            calibration_store=CalibrationStore(vstore.root),
            dataset_store=DatasetStore(vstore.root),
        )
        if args.as_json:
            print(dumps_pretty(staleness.model_dump(mode="json")))
        else:
            print(f"{staleness.validation_id}: {'fresh' if staleness.fresh else 'stale'}")
            for reason in staleness.reasons:
                print(f"  - {reason}")
        return 0 if staleness.fresh else 1

    store = ExperimentStore(workspace) if workspace else default_store()
    datasets = DatasetStore(workspace) if workspace else default_dataset_store()

    try:
        raw_config = json.loads(Path(args.config).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"could not read validation config {args.config!r}: {exc}") from exc
    config = ValidationConfig.model_validate(raw_config)
    # The command-line experiment id is authoritative.
    config = config.model_copy(update={"experiment_id": args.experiment_id})

    loaded = store.load(args.experiment_id)
    spec = ExperimentSpec.model_validate(loaded["spec"])
    schema = build_model(spec.model_ref.model_id).describe()
    calibration = CalibrationStore(store.root).load(config.calibration.calibration_id)

    if args.dry_run:
        diagnostics = list(
            validate_validation_config(config, schema, calibration, dict(spec.baseline))
        )
        calibration_dataset = datasets.load(calibration.config.dataset.dataset_id)
        reports = []
        for item in config.datasets:
            dataset = datasets.load(item.dataset.dataset_id)
            diagnostics.extend(validate_mapping(item.mapping, dataset=dataset, schema=schema))
            reports.append(
                (
                    item,
                    evaluate_independence(
                        item.independence, calibration_dataset, dataset, item.mapping
                    ),
                )
            )
        if not diagnostics:
            print("no diagnostics: validation is ready to run")
        for diagnostic in diagnostics:
            print(f"[{diagnostic.level.upper()}] {diagnostic.code}: {diagnostic.message}")
        for item, report in reports:
            label = item.label or item.dataset.dataset_id
            print(f"dataset {label}: independence={report.status} ({report.note})")
        print(
            f"dry run: datasets={len(config.datasets)} "
            f"budget={config.budget.max_evaluations} metrics={list(config.evaluation.metrics)}"
        )
        print("dry run: no model runs were executed")
        return 2 if any(d.level == "error" for d in diagnostics) else 0

    result = validate_for_experiment(args.experiment_id, store, config)
    ref = ValidationStore(store.root).save(result) if args.persist else None

    if args.as_json:
        payload = result.model_dump(mode="json")
        if ref is not None:
            payload["validation_id"] = ref.validation_id
        print(dumps_pretty(payload))
    else:
        print(
            f"experiment: {result.experiment_id}  agreement: {result.agreement_status}  "
            f"acceptance: {result.acceptance_status}  independence: {result.independence_status}"
        )
        print(
            f"datasets: {len(result.datasets)}  evaluations: {result.evaluations_completed} "
            f"(cap {result.evaluations_requested})  wall: {result.wall_seconds:.3f}s"
        )
        for item in result.datasets:
            label = item.label or item.dataset.dataset_id
            metrics = ", ".join(
                f"{key}={value:.6g}" if value is not None else f"{key}=n/a"
                for key, value in item.metrics.items()
            )
            print(
                f"  [{item.failure or item.agreement}] {label}: {metrics or 'no metrics'}  "
                f"independence={item.independence.status}"
            )
        for diagnostic in result.diagnostics:
            print(f"[{diagnostic.level.upper()}] {diagnostic.code}: {diagnostic.message}")
        if ref is not None:
            print(f"stored validation: {ref.validation_id}")
        print(f"note: {result.note}")
    return 0 if any(item.agreement == "evaluated" for item in result.datasets) else 1


_COMMANDS = {
    "list-models": _cmd_list_models,
    "describe": _cmd_describe,
    "validate": _cmd_validate,
    "run": _cmd_run,
    "demo": _cmd_demo,
    "export-schemas": _cmd_export_schemas,
    "verify": _cmd_verify,
    "reproduce": _cmd_reproduce,
    "uncertainty": _cmd_uncertainty,
    "sobol": _cmd_sobol,
    "identifiability": _cmd_identifiability,
    "dataset": _cmd_dataset,
    "evaluate": _cmd_evaluate,
    "calibrate": _cmd_calibrate,
    "validation": _cmd_validation,
}


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    handler = _COMMANDS[args.command]
    try:
        return handler(args)
    except (KeyError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
