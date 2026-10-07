"""Content-addressed persistence for structured model specifications.

Model specifications are inspectable artifacts, so they are stored durably like
datasets, calibrations and validations - append-only, content-addressed and
verifiable - rather than living only in a conversation. Layout under the
workspace root::

    <root>/model-specs/<spec_id>/{spec,provenance,manifest}.json

``spec_id = "mspec-" + content_hash[:12]``. Nothing here executes a model.
"""

from __future__ import annotations

import json
import os
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict

from drw.schema.model_spec import ModelSpecification
from drw.schema.serialization import dumps_pretty, sha256_hex, to_plain

__all__ = [
    "InvalidModelSpecId",
    "ModelSpecRef",
    "ModelSpecStore",
    "ModelSpecStoreError",
    "ModelSpecVerification",
    "default_model_spec_store",
]

MODEL_SPEC_ID_PATTERN = re.compile(r"^mspec-[0-9a-f]{12}$")

_SPEC = "spec.json"
_PROVENANCE = "provenance.json"
_MANIFEST = "manifest.json"


class ModelSpecStoreError(RuntimeError):
    """Base class for model-spec-store failures."""


class InvalidModelSpecId(ModelSpecStoreError, ValueError):
    """Raised for a malformed spec id or a path that escapes the store."""


class ModelSpecRef(BaseModel):
    model_config = ConfigDict(extra="forbid")

    spec_id: str
    content_hash: str
    model_id: str
    version: str
    created_at: str | None = None


class ModelSpecVerification(BaseModel):
    model_config = ConfigDict(extra="forbid")

    spec_id: str
    content_hash: str
    ok: bool
    checks: list[dict[str, str]]
    errors: int


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _default_root() -> Path:
    return Path(os.environ.get("DRW_WORKSPACE", ".drw/workspace"))


def default_model_spec_store() -> ModelSpecStore:
    return ModelSpecStore(_default_root())


class ModelSpecStore:
    """Filesystem-backed, content-addressed store for model specifications."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)

    @property
    def specs_dir(self) -> Path:
        return self.root / "model-specs"

    def directory(self, spec_id: str) -> Path:
        if not MODEL_SPEC_ID_PATTERN.match(spec_id):
            raise InvalidModelSpecId(f"invalid model spec id {spec_id!r}")
        base = self.specs_dir.resolve()
        candidate = (base / spec_id).resolve()
        if candidate.parent != base:
            raise InvalidModelSpecId(f"model spec path escapes the store: {spec_id!r}")
        return candidate

    def path(self, spec_id: str) -> Path:
        """Validate and return the on-disk directory for ``spec_id``."""
        return self.directory(spec_id)

    def exists(self, spec_id: str) -> bool:
        try:
            return (self.directory(spec_id) / _MANIFEST).is_file()
        except InvalidModelSpecId:
            return False

    def _read_manifest(self, spec_id: str) -> dict[str, Any]:
        path = self.directory(spec_id) / _MANIFEST
        if not path.is_file():
            raise ModelSpecStoreError(f"model spec {spec_id!r} not found")
        return json.loads(path.read_text(encoding="utf-8"))

    def ref(self, spec_id: str) -> ModelSpecRef:
        manifest = self._read_manifest(spec_id)
        return ModelSpecRef(
            spec_id=spec_id,
            content_hash=manifest["content_hash"],
            model_id=manifest["model_id"],
            version=manifest["version"],
            created_at=manifest.get("created_at"),
        )

    def list(self) -> list[ModelSpecRef]:
        if not self.specs_dir.is_dir():
            return []
        return [
            self.ref(directory.name)
            for directory in sorted(self.specs_dir.iterdir())
            if directory.is_dir() and (directory / _MANIFEST).is_file()
        ]

    def load(self, spec_id: str) -> ModelSpecification:
        directory = self.directory(spec_id)
        document = json.loads((directory / _SPEC).read_text(encoding="utf-8"))
        spec = ModelSpecification.model_validate(document)
        if spec.spec_id() != spec_id:
            raise ModelSpecStoreError(
                f"model spec {spec_id!r} does not match its content; the store may be corrupt"
            )
        return spec

    def save(
        self, spec: ModelSpecification, *, created_at: str | None = None
    ) -> ModelSpecRef:
        spec_id = spec.spec_id()
        directory = self.directory(spec_id)
        if directory.is_dir():
            return self.ref(spec_id)
        directory.mkdir(parents=True, exist_ok=True)
        documents = {
            _SPEC: to_plain(spec),
            _PROVENANCE: to_plain(spec.provenance),
        }
        files: list[dict[str, Any]] = []
        for name, document in documents.items():
            data = (dumps_pretty(document) + "\n").encode("utf-8")
            (directory / name).write_bytes(data)
            files.append(
                {"path": name, "sha256": sha256_hex(data), "size_bytes": len(data)}
            )
        manifest = {
            "schema_version": "1.0.0",
            "spec_id": spec_id,
            "content_hash": spec.content_hash(),
            "model_id": spec.model_id,
            "version": spec.version,
            "created_at": created_at or _now(),
            "files": files,
        }
        (directory / _MANIFEST).write_bytes(
            (dumps_pretty(manifest) + "\n").encode("utf-8")
        )
        return self.ref(spec_id)

    def verify(self, spec_id: str) -> ModelSpecVerification:
        directory = self.directory(spec_id)
        manifest = self._read_manifest(spec_id)
        checks: list[dict[str, str]] = []
        for entry in manifest.get("files", []):
            path = directory / entry.get("path", "")
            if not path.is_file():
                checks.append(
                    {
                        "name": entry.get("path", ""),
                        "status": "failed",
                        "message": "missing",
                    }
                )
                continue
            data = path.read_bytes()
            ok = len(data) == entry.get("size_bytes") and sha256_hex(data) == entry.get(
                "sha256"
            )
            checks.append(
                {
                    "name": entry.get("path", ""),
                    "status": "ok" if ok else "failed",
                    "message": "" if ok else "hash/size mismatch",
                }
            )
        try:
            spec = self.load(spec_id)
            matches = spec.content_hash() == manifest.get("content_hash")
        except (ModelSpecStoreError, ValueError) as exc:
            matches = False
            checks.append(
                {"name": "content_hash", "status": "failed", "message": str(exc)}
            )
        else:
            checks.append(
                {
                    "name": "content_hash",
                    "status": "ok" if matches else "failed",
                    "message": "" if matches else "content hash mismatch",
                }
            )
        errors = sum(1 for check in checks if check["status"] == "failed")
        return ModelSpecVerification(
            spec_id=spec_id,
            content_hash=manifest.get("content_hash", ""),
            ok=errors == 0,
            checks=checks,
            errors=errors,
        )
