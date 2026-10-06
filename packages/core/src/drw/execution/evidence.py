"""SCI-005 (evidence): portable, hashed reproducibility packages.

A package is a directory (optionally zipped) containing the exact spec, the model
contract, every run, every comparison and a human-readable report, tied together
by a manifest of SHA-256 hashes. It exists to answer "where did this number come
from?" (specification sections 4.1 and 6.4).
"""

from __future__ import annotations

import json
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from drw.execution.environment import fingerprint_hash
from drw.execution.result import ExperimentResult
from drw.schema.serialization import dumps_pretty, sha256_hex, to_plain

__all__ = [
    "ArtifactEntry",
    "ArtifactVerification",
    "EvidenceManifest",
    "EvidenceVerification",
    "EvidenceVerificationError",
    "build_evidence_package",
    "render_report",
    "verify_evidence",
]

EVIDENCE_SCHEMA_VERSION = "1.0.0"


class ArtifactEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str
    kind: str
    sha256: str
    size_bytes: int


class EvidenceManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = EVIDENCE_SCHEMA_VERSION
    generated_at: str
    experiment_id: str
    name: str
    hypothesis: str
    model_ref: dict
    spec_hash: str
    model_hash: str
    environment_hash: str
    environment: dict
    estimate: dict
    n_runs: int
    n_succeeded: int
    n_failed: int
    counts_by_status: dict[str, int]
    run_ids: list[str]
    analyses: list[str]
    warnings: list[dict]
    files: list[ArtifactEntry]


def _file_entry(path: Path, root: Path, kind: str) -> ArtifactEntry:
    data = path.read_bytes()
    return ArtifactEntry(
        path=path.relative_to(root).as_posix(),
        kind=kind,
        sha256=sha256_hex(data),
        size_bytes=len(data),
    )


def render_report(result: ExperimentResult) -> str:
    """Render a one-page, provenance-first Markdown report."""
    lines: list[str] = []
    title = result.spec.reporting.title or result.spec.name or result.experiment_id
    lines.append(f"# {title}")
    lines.append("")
    lines.append(f"**Experiment id:** `{result.experiment_id}`  ")
    lines.append(f"**Model:** `{result.model_ref.model_id}`  ")
    lines.append(f"**Hypothesis:** {result.spec.hypothesis}")
    lines.append("")

    estimate = result.estimate
    lines.append("## Execution plan")
    lines.append("")
    lines.append(
        f"- Sampling method: `{estimate.method}`\n"
        f"- Baseline runs: {estimate.baseline_runs}\n"
        f"- Variant runs: {estimate.variant_runs}\n"
        f"- Total runs: {estimate.total_runs}"
    )
    lines.append("")

    lines.append("## Runs")
    lines.append("")
    lines.append("| run id | label | status | duration (s) | metrics |")
    lines.append("| --- | --- | --- | --- | --- |")
    for run in result.runs:
        metrics = ", ".join(f"{k}={v:.6g}" for k, v in sorted(run.metrics.items())) or "-"
        duration = f"{run.duration_s:.4f}" if run.duration_s is not None else "-"
        lines.append(f"| `{run.run_id}` | {run.label} | {run.status.value} | {duration} | {metrics} |")
    lines.append("")

    lines.append("## Differential analysis")
    lines.append("")
    if result.comparisons:
        lines.append(
            "| variant | output | method | MAE | RMSE | max abs delta | "
            "max abs rel delta | peak shift | alignment |"
        )
        lines.append("| --- | --- | --- | --- | --- | --- | --- | --- | --- |")
        for comparison in result.comparisons:
            m = comparison.metrics
            lines.append(
                f"| `{comparison.variant_run_id}` | {comparison.output} | {comparison.method} | "
                f"{m.get('mae', float('nan')):.6g} | {m.get('rmse', float('nan')):.6g} | "
                f"{m.get('max_abs_delta', float('nan')):.6g} | "
                f"{m.get('max_abs_relative_delta', float('nan')):.6g} | "
                f"{m.get('peak_shift', float('nan')):.6g} | {comparison.alignment} |"
            )
    else:
        lines.append("_No comparisons were produced._")
    lines.append("")

    lines.append("## Reproducibility")
    lines.append("")
    lines.append(f"- Spec hash: `{result.spec_hash}`")
    lines.append(f"- Model hash: `{result.model_hash}`")
    lines.append(f"- Environment hash: `{fingerprint_hash(result.environment)}`")
    lines.append(f"- Python: {result.environment.get('python_version')}")
    lines.append(f"- numpy/scipy: {result.environment.get('numpy')} / {result.environment.get('scipy')}")
    lines.append("")

    if result.uncertainty is not None:
        uncertainty = result.uncertainty
        lines.append("## Uncertainty (descriptive)")
        lines.append("")
        lines.append(
            f"- Sampling: `{uncertainty.sampling_method}` · seed {uncertainty.seed} · "
            f"variants {uncertainty.requested_variants} · "
            f"valid output-samples {uncertainty.valid_output_samples} · "
            f"excluded output-samples {uncertainty.excluded_output_samples}"
        )
        lines.append(
            f"- Quantiles {uncertainty.quantiles} (method `{uncertainty.quantile_method}`)"
        )
        lines.append("")
        lines.append("| output | unit | valid | mean | std | min | max | p05 | p50 | p95 |")
        lines.append("| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |")

        def _fmt(value: float | None) -> str:
            return "n/a" if value is None else f"{value:.6g}"

        for output in uncertainty.outputs:
            lines.append(
                f"| {output.output} | {output.unit} | {output.valid_samples} | {_fmt(output.mean)} | "
                f"{_fmt(output.std)} | {_fmt(output.minimum)} | {_fmt(output.maximum)} | "
                f"{_fmt(output.p05)} | {_fmt(output.p50)} | {_fmt(output.p95)} |"
            )
        lines.append("")
        lines.append(
            "_Descriptive summary of the sampled design; not a probabilistic guarantee "
            "or scientific validation._"
        )
        lines.append("")

    warnings = list(result.warnings) + [
        warning for comparison in result.comparisons for warning in comparison.warnings
    ]
    if warnings:
        lines.append("## Warnings")
        lines.append("")
        for warning in warnings:
            lines.append(f"- `{warning.code}`: {warning.message}")
        lines.append("")

    return "\n".join(lines) + "\n"


def build_evidence_package(
    result: ExperimentResult,
    out_dir: str | Path,
    *,
    zip_bundle: bool = False,
    generated_at: str | None = None,
) -> Path:
    """Write an evidence package and return the path to ``manifest.json``."""
    root = Path(out_dir)
    root.mkdir(parents=True, exist_ok=True)

    spec_path = root / "experiment-spec.json"
    schema_path = root / "model-schema.json"
    results_path = root / "results.json"
    report_path = root / "report.md"

    spec_path.write_text(dumps_pretty(result.spec) + "\n", encoding="utf-8")
    schema_path.write_text(dumps_pretty(result.schema) + "\n", encoding="utf-8")
    results_path.write_text(
        dumps_pretty(
            {
                "experiment_id": result.experiment_id,
                "runs": result.runs,
                "comparisons": result.comparisons,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    report_path.write_text(render_report(result), encoding="utf-8")

    counts: dict[str, int] = {}
    for run in result.runs:
        counts[run.status.value] = counts.get(run.status.value, 0) + 1

    files = [
        _file_entry(spec_path, root, "experiment_spec"),
        _file_entry(schema_path, root, "model_schema"),
        _file_entry(results_path, root, "results"),
        _file_entry(report_path, root, "report"),
    ]

    # Additive artifact: present only when the experiment declared the
    # ``uncertainty`` analysis. Experiments without it are unchanged.
    bundle_paths = [spec_path, schema_path, results_path, report_path]
    if result.uncertainty is not None:
        uncertainty_path = root / "uncertainty.json"
        uncertainty_path.write_text(
            dumps_pretty(result.uncertainty) + "\n", encoding="utf-8"
        )
        files.append(_file_entry(uncertainty_path, root, "uncertainty"))
        bundle_paths.append(uncertainty_path)

    manifest = EvidenceManifest(
        generated_at=generated_at or datetime.now(UTC).isoformat(),
        experiment_id=result.experiment_id,
        name=result.spec.name,
        hypothesis=result.spec.hypothesis,
        model_ref=to_plain(result.model_ref),
        spec_hash=result.spec_hash,
        model_hash=result.model_hash,
        environment_hash=fingerprint_hash(result.environment),
        environment=to_plain(result.environment),
        estimate=to_plain(result.estimate),
        n_runs=len(result.runs),
        n_succeeded=len(result.succeeded_runs),
        n_failed=len(result.failed_runs),
        counts_by_status=counts,
        run_ids=[run.run_id for run in result.runs],
        analyses=[a.method for a in result.spec.analyses],
        warnings=[to_plain(w) for w in result.warnings],
        files=files,
    )
    manifest_path = root / "manifest.json"
    manifest_path.write_text(dumps_pretty(manifest) + "\n", encoding="utf-8")

    if zip_bundle:
        archive = root.parent / f"{root.name}.zip"
        with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as bundle:
            for path in (*bundle_paths, manifest_path):
                bundle.write(path, arcname=path.relative_to(root).as_posix())

    return manifest_path


# ---------------------------------------------------------------------------
# Verification (read-only).
#
# A package is verified against the manifest that was written alongside it. This
# is a *consistency* check - the manifest is not self-hashed or signed, so a
# successful result does not prove protection against a party who can rewrite
# both the artifacts and the manifest.
# ---------------------------------------------------------------------------

VERIFICATION_SCHEMA_VERSION = "1.0.0"

#: Per-artifact verification outcome.
ArtifactStatus = Literal[
    "ok",
    "missing",
    "size_mismatch",
    "hash_mismatch",
    "invalid_path",
    "invalid_entry",
    "unreadable",
]


class EvidenceVerificationError(ValueError):
    """Raised when a manifest cannot be used for verification at all."""


class ArtifactVerification(BaseModel):
    """The verification outcome for one artifact declared by the manifest."""

    model_config = ConfigDict(extra="forbid")

    path: str
    kind: str = ""
    status: ArtifactStatus
    expected_sha256: str = ""
    expected_size_bytes: int = 0
    actual_sha256: str | None = None
    actual_size_bytes: int | None = None


class EvidenceVerification(BaseModel):
    """The outcome of verifying an evidence package against its manifest.

    ``ok`` is ``True`` only when **every declared artifact** exists, stays inside
    the manifest's directory, and matches its recorded size and SHA-256. Files
    present in the directory but **not declared** by the manifest are listed in
    ``extra_files`` and are explicitly **not** verified; on their own they do not
    fail verification (an exported package legitimately contains ``evidence.zip``,
    and the manifest itself is not listed among the artifacts).
    """

    model_config = ConfigDict(extra="forbid")

    schema_version: str = VERIFICATION_SCHEMA_VERSION
    manifest: str
    experiment_id: str | None = None
    ok: bool
    verified: int
    failed: int
    artifacts: list[ArtifactVerification]
    extra_files: list[str] = Field(default_factory=list)


def _resolve_within(root: Path, relative: str) -> Path | None:
    """Resolve ``relative`` under ``root``; return ``None`` if it escapes."""
    candidate = Path(relative)
    if candidate.is_absolute():
        return None
    resolved = (root / candidate).resolve()
    base = root.resolve()
    if resolved != base and base not in resolved.parents:
        return None
    return resolved


def _verify_artifact(root: Path, entry: Any) -> ArtifactVerification:
    if not isinstance(entry, dict):
        return ArtifactVerification(path="<malformed entry>", status="invalid_entry")
    relative = entry.get("path")
    expected_sha = entry.get("sha256")
    expected_size = entry.get("size_bytes")
    if not isinstance(relative, str) or not relative:
        return ArtifactVerification(path="<missing path>", status="invalid_entry")
    if (
        not isinstance(expected_sha, str)
        or not expected_sha
        or not isinstance(expected_size, int)
        or isinstance(expected_size, bool)
    ):
        return ArtifactVerification(path=relative, status="invalid_entry")

    record = ArtifactVerification(
        path=relative,
        kind=str(entry.get("kind") or ""),
        status="missing",
        expected_sha256=expected_sha,
        expected_size_bytes=expected_size,
    )
    target = _resolve_within(root, relative)
    if target is None:
        record.status = "invalid_path"
        return record
    if not target.is_file():
        record.status = "missing"
        return record
    try:
        data = target.read_bytes()
    except OSError:  # pragma: no cover - unreadable file
        record.status = "unreadable"
        return record

    record.actual_size_bytes = len(data)
    record.actual_sha256 = sha256_hex(data)
    if len(data) != expected_size:
        record.status = "size_mismatch"
    elif record.actual_sha256 != expected_sha:
        record.status = "hash_mismatch"
    else:
        record.status = "ok"
    return record


def verify_evidence(manifest_path: str | Path) -> EvidenceVerification:
    """Verify an evidence package against its manifest (read-only).

    Every artifact the manifest declares must exist, stay inside the manifest's
    directory, and match the recorded size and SHA-256. Missing files, modified
    files, size mismatches, escaping paths and malformed entries are reported per
    artifact; the package is ``ok`` only when no declared artifact failed.
    Undeclared files present in the directory are listed in ``extra_files`` and
    are **not** treated as verified evidence.

    Structural problems raise :class:`EvidenceVerificationError`: a missing,
    unreadable or malformed manifest, a manifest that declares **no** artifacts
    (an empty package must never verify), or an evidence directory that cannot be
    listed. Nothing is written: manifests, artifacts, experiment records and
    stored results are only read.
    """
    path = Path(manifest_path)
    if not path.is_file():
        raise EvidenceVerificationError(f"manifest not found: {path}")
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:  # pragma: no cover - unreadable manifest
        raise EvidenceVerificationError(f"could not read manifest {path}: {exc}") from exc
    try:
        manifest = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise EvidenceVerificationError(f"manifest is not valid JSON: {exc}") from exc
    if not isinstance(manifest, dict):
        raise EvidenceVerificationError("manifest must be a JSON object")
    entries = manifest.get("files")
    if not isinstance(entries, list):
        raise EvidenceVerificationError("manifest is missing a 'files' list")
    if not entries:
        raise EvidenceVerificationError(
            "manifest declares no artifacts; an empty package cannot be verified"
        )

    root = path.parent
    artifacts = [_verify_artifact(root, entry) for entry in entries]

    declared = {artifact.path for artifact in artifacts}
    extra_files: list[str] = []
    manifest_name = path.name
    try:
        siblings = sorted(root.iterdir())
    except OSError as exc:
        raise EvidenceVerificationError(
            f"could not list the evidence directory {root}: {exc}"
        ) from exc
    for sibling in siblings:
        name = sibling.relative_to(root).as_posix()
        if sibling.is_file() and name != manifest_name and name not in declared:
            extra_files.append(name)

    failed = sum(1 for artifact in artifacts if artifact.status != "ok")
    experiment_id = manifest.get("experiment_id")
    return EvidenceVerification(
        manifest=str(path),
        experiment_id=experiment_id if isinstance(experiment_id, str) else None,
        ok=failed == 0,
        verified=len(artifacts) - failed,
        failed=failed,
        artifacts=artifacts,
        extra_files=extra_files,
    )
