"""``python -m drw`` command line interface.

Subcommands map directly onto the documented MVP workflow:

    list-models, describe, validate, run, demo, export-schemas
"""

from __future__ import annotations

import argparse
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


_COMMANDS = {
    "list-models": _cmd_list_models,
    "describe": _cmd_describe,
    "validate": _cmd_validate,
    "run": _cmd_run,
    "demo": _cmd_demo,
    "export-schemas": _cmd_export_schemas,
    "verify": _cmd_verify,
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
