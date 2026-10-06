"""Local-first persistence for projects and experiments.

Layout under the workspace root (``DRW_WORKSPACE``)::

    <root>/
        projects/<project_id>.json          # {project_id, name, description, model_id, created_at}
        experiments/<experiment_id>/        # meta.json, spec.json, results.json, evidence/
        jobs/<job_id>.jsonl                 # execution progress journals (ADR-0009)

An experiment stores the project it belongs to in ``meta.json``. **Compatibility:**
experiments written before projects existed have no ``project_id``; they are read
as belonging to the ``default`` project and are never rewritten, so existing data
and stable experiment identifiers are preserved.

Every id is validated against a strict pattern and every resolved path is
confirmed to stay inside the root, so a request can never read or write outside
the workspace.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from drw.execution.evidence import build_evidence_package
from drw.execution.result import ExperimentResult
from drw.schema.serialization import dumps_pretty, to_plain

__all__ = [
    "DEFAULT_PROJECT_ID",
    "ExperimentStore",
    "InvalidExperimentId",
    "InvalidProjectId",
    "default_store",
    "result_payload",
]

EXPERIMENT_ID_PATTERN = re.compile(r"^exp-[0-9a-f]{12}$")
PROJECT_ID_PATTERN = re.compile(r"^(default|proj-[0-9a-f]{12})$")

DEFAULT_PROJECT_ID = "default"
_DEFAULT_PROJECT_NAME = "Sample: predator-prey"

_RESULT_FILENAME = "results.json"
_META_FILENAME = "meta.json"
_SPEC_FILENAME = "spec.json"
_EVIDENCE_DIRNAME = "evidence"


class InvalidExperimentId(ValueError):
    """Raised when an experiment id is malformed or would escape the workspace."""


class InvalidProjectId(ValueError):
    """Raised when a project id is malformed or would escape the workspace."""


def _default_root() -> Path:
    return Path(os.environ.get("DRW_WORKSPACE", ".drw/workspace"))


def default_store() -> ExperimentStore:
    """Build a store from ``DRW_WORKSPACE`` (read at call time)."""
    return ExperimentStore(_default_root())


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(dumps_pretty(payload) + "\n", encoding="utf-8")


class ExperimentStore:
    """Filesystem-backed store for projects and experiments."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)

    # -- paths --------------------------------------------------------------

    def _contained(self, *parts: str) -> Path:
        candidate = (self.root.joinpath(*parts)).resolve()
        root = self.root.resolve()
        if root != candidate and root not in candidate.parents:
            raise InvalidExperimentId(f"path escapes the workspace: {'/'.join(parts)}")
        return candidate

    def experiment_dir(self, experiment_id: str) -> Path:
        if not EXPERIMENT_ID_PATTERN.match(experiment_id):
            raise InvalidExperimentId(f"invalid experiment id {experiment_id!r}")
        candidate = self._contained("experiments", experiment_id)
        expected = (self.root / "experiments").resolve()
        if candidate.parent != expected:
            raise InvalidExperimentId(f"experiment path escapes the workspace: {experiment_id!r}")
        return candidate

    def project_path(self, project_id: str) -> Path:
        if not PROJECT_ID_PATTERN.match(project_id):
            raise InvalidProjectId(f"invalid project id {project_id!r}")
        candidate = self._contained("projects", f"{project_id}.json")
        expected = (self.root / "projects").resolve()
        if candidate.parent != expected:
            raise InvalidProjectId(f"project path escapes the workspace: {project_id!r}")
        return candidate

    # -- projects -----------------------------------------------------------

    def ensure_default_project(self) -> dict[str, Any]:
        """Create the built-in sample project on first use and return it."""
        path = self.project_path(DEFAULT_PROJECT_ID)
        if not path.is_file():
            _write_json(
                path,
                {
                    "project_id": DEFAULT_PROJECT_ID,
                    "name": _DEFAULT_PROJECT_NAME,
                    "description": "Built-in sample project for the predator-prey model.",
                    "model_id": "predator-prey",
                    "created_at": _now(),
                },
            )
        return _read_json(path)

    def create_project(
        self, name: str, *, description: str = "", model_id: str | None = None
    ) -> dict[str, Any]:
        clean = " ".join(name.split())
        if not clean:
            raise ValueError("project name must not be empty")
        digest = hashlib.sha256(f"{clean}|{_now()}".encode()).hexdigest()[:12]
        project_id = f"proj-{digest}"
        payload = {
            "project_id": project_id,
            "name": clean,
            "description": description,
            "model_id": model_id,
            "created_at": _now(),
        }
        _write_json(self.project_path(project_id), payload)
        return payload

    def list_projects(self) -> list[dict[str, Any]]:
        self.ensure_default_project()
        projects = [
            _read_json(path)
            for path in sorted((self.root / "projects").glob("*.json"))
            if path.is_file()
        ]
        projects.sort(key=lambda item: (item.get("project_id") != DEFAULT_PROJECT_ID, item.get("created_at") or ""))
        return projects

    def get_project(self, project_id: str) -> dict[str, Any]:
        if project_id == DEFAULT_PROJECT_ID:
            return self.ensure_default_project()
        path = self.project_path(project_id)
        if not path.is_file():
            raise KeyError(f"project {project_id!r} not found")
        return _read_json(path)

    # -- experiments --------------------------------------------------------

    def save(self, result: ExperimentResult, *, project_id: str = DEFAULT_PROJECT_ID) -> Path:
        """Persist an experiment result (spec, results, metadata and evidence)."""
        project = self.get_project(project_id)  # validates the project exists
        directory = self.experiment_dir(result.experiment_id)
        directory.mkdir(parents=True, exist_ok=True)

        (directory / _SPEC_FILENAME).write_text(dumps_pretty(result.spec) + "\n", encoding="utf-8")
        (directory / _RESULT_FILENAME).write_text(
            dumps_pretty(result_payload(result)) + "\n", encoding="utf-8"
        )
        build_evidence_package(result, directory / _EVIDENCE_DIRNAME)

        meta = {
            "experiment_id": result.experiment_id,
            "project_id": project["project_id"],
            "name": result.spec.name,
            "hypothesis": result.spec.hypothesis,
            "model_id": result.model_ref.model_id,
            "isolation": result.isolation,
            "spec_hash": result.spec_hash,
            "model_hash": result.model_hash,
            "n_runs": len(result.runs),
            "n_succeeded": len(result.succeeded_runs),
            "n_failed": len(result.failed_runs),
            "created_at": result.finished_at or result.started_at,
            "warnings": [to_plain(w) for w in result.warnings],
        }
        _write_json(directory / _META_FILENAME, meta)
        return directory

    def exists(self, experiment_id: str) -> bool:
        try:
            return (self.experiment_dir(experiment_id) / _RESULT_FILENAME).is_file()
        except InvalidExperimentId:
            return False

    def list(self, *, project_id: str | None = None) -> list[dict[str, Any]]:
        experiments_root = self.root / "experiments"
        if not experiments_root.is_dir():
            return []
        summaries: list[dict[str, Any]] = []
        for directory in sorted(experiments_root.iterdir()):
            meta_path = directory / _META_FILENAME
            if not meta_path.is_file():
                continue
            try:
                meta = _read_json(meta_path)
            except (OSError, json.JSONDecodeError):  # pragma: no cover - corrupt entry
                continue
            # Compatibility: experiments predating projects belong to `default`.
            meta.setdefault("project_id", DEFAULT_PROJECT_ID)
            if project_id is not None and meta["project_id"] != project_id:
                continue
            summaries.append(meta)
        summaries.sort(key=lambda item: item.get("created_at") or "", reverse=True)
        return summaries

    def load(self, experiment_id: str) -> dict[str, Any]:
        directory = self.experiment_dir(experiment_id)
        spec_path = directory / _SPEC_FILENAME
        results_path = directory / _RESULT_FILENAME
        if not spec_path.is_file() or not results_path.is_file():
            raise KeyError(f"experiment {experiment_id!r} not found")
        meta_path = directory / _META_FILENAME
        meta = _read_json(meta_path) if meta_path.is_file() else {"experiment_id": experiment_id}
        meta.setdefault("project_id", DEFAULT_PROJECT_ID)
        return {
            "meta": meta,
            "spec": _read_json(spec_path),
            "results": _read_json(results_path),
        }

    def evidence(self, experiment_id: str) -> dict[str, Any]:
        directory = self.experiment_dir(experiment_id) / _EVIDENCE_DIRNAME
        manifest_path = directory / "manifest.json"
        if not manifest_path.is_file():
            raise KeyError(f"experiment {experiment_id!r} has no evidence package")
        manifest = _read_json(manifest_path)
        report_path = directory / "report.md"
        return {
            "manifest": manifest,
            "report": report_path.read_text(encoding="utf-8") if report_path.is_file() else "",
            "files": manifest.get("files", []),
        }

    def export_zip(self, experiment_id: str) -> Path:
        directory = self.experiment_dir(experiment_id) / _EVIDENCE_DIRNAME
        if not directory.is_dir():
            raise KeyError(f"experiment {experiment_id!r} has no evidence package")
        archive = directory / "evidence.zip"
        with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as bundle:
            for path in sorted(directory.iterdir()):
                if path.name == archive.name or not path.is_file():
                    continue
                bundle.write(path, arcname=path.name)
        return archive


def result_payload(result: ExperimentResult) -> dict[str, Any]:
    """Canonical, JSON-ready representation of an experiment result.

    ``uncertainty`` is included only when the experiment declared the analysis, so
    results for experiments without it are unchanged.
    """
    payload: dict[str, Any] = {
        "experiment_id": result.experiment_id,
        "name": result.spec.name,
        "hypothesis": result.spec.hypothesis,
        "model_ref": result.model_ref,
        "isolation": result.isolation,
        "spec_hash": result.spec_hash,
        "model_hash": result.model_hash,
        "environment": result.environment,
        "estimate": result.estimate,
        "warnings": result.warnings,
        "runs": result.runs,
        "comparisons": result.comparisons,
        "started_at": result.started_at,
        "finished_at": result.finished_at,
    }
    if result.uncertainty is not None:
        payload["uncertainty"] = result.uncertainty
    return to_plain(payload)
