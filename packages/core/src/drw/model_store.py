"""Content-addressed persistence for compiled models (the model-generation path).

A compiled model is an inspectable artifact: the source specification, the projected
:class:`~drw.schema.model.ModelSchema` and a serializable execution descriptor (rate
expressions, state order, window). It is stored append-only, content-addressed and
verifiable, mirroring the other DRW stores. Updating the specification produces a
different identity, so a model can never be ambiguously overwritten.

Layout under the workspace root::

    <root>/models/<model_id>/
        spec.json         # the source ModelSpecification
        schema.json       # the projected ModelSchema
        artifact.json     # the execution descriptor (rate expressions, window, ...)
        provenance.json   # compiler + spec identity
        manifest.json     # sha256 of each file + identity

``model_id = "mdl-" + compile_hash[:12]``. Nothing here executes arbitrary code: the
descriptor holds validated expression **strings** and is re-compiled deterministically
by :mod:`drw.model_compiler` when the model is built.
"""

from __future__ import annotations

import json
import os
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict

from drw.model_compiler import CompiledModel, compute_compile_hash
from drw.schema.model import ModelSchema
from drw.schema.model_spec import ModelSpecification
from drw.schema.serialization import dumps_pretty, sha256_hex, to_plain

__all__ = [
    "CompiledModelRef",
    "InvalidModelId",
    "ModelCorruptedError",
    "ModelNotFoundError",
    "ModelStore",
    "ModelStoreError",
    "ModelVerification",
    "default_model_store",
]

MODEL_ID_PATTERN = re.compile(r"^mdl-[0-9a-f]{12}$")

_SPEC = "spec.json"
_SCHEMA = "schema.json"
_ARTIFACT = "artifact.json"
_PROVENANCE = "provenance.json"
_MANIFEST = "manifest.json"


class ModelStoreError(RuntimeError):
    """Base class for model-store failures."""


class InvalidModelId(ModelStoreError, ValueError):
    """Raised for a malformed model id or a path that escapes the store."""


class ModelNotFoundError(ModelStoreError, KeyError):
    """Raised when a model id does not exist in the store."""


class ModelCorruptedError(ModelStoreError):
    """Raised when a stored model cannot be reconstructed faithfully."""


class CompiledModelRef(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model_id: str
    version: str
    model_name: str
    spec_hash: str
    compile_hash: str
    model_hash: str
    created_at: str | None = None


class ModelVerification(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model_id: str
    compile_hash: str
    ok: bool
    checks: list[dict[str, str]]
    errors: int


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _default_root() -> Path:
    return Path(os.environ.get("DRW_WORKSPACE", ".drw/workspace"))


def default_model_store() -> ModelStore:
    """Build a model store from ``DRW_WORKSPACE`` (read at call time)."""
    return ModelStore(_default_root())


class ModelStore:
    """Filesystem-backed, content-addressed store for compiled models."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)

    @property
    def models_dir(self) -> Path:
        return self.root / "models"

    def directory(self, model_id: str) -> Path:
        if not isinstance(model_id, str) or not MODEL_ID_PATTERN.match(model_id):
            raise InvalidModelId(f"invalid model id {model_id!r}")
        base = self.models_dir.resolve()
        candidate = (base / model_id).resolve()
        if candidate.parent != base:
            raise InvalidModelId(f"model path escapes the store: {model_id!r}")
        return candidate

    def exists(self, model_id: str) -> bool:
        try:
            return (self.directory(model_id) / _MANIFEST).is_file()
        except InvalidModelId:
            return False

    # -- read ---------------------------------------------------------------

    def _read(self, model_id: str, filename: str) -> dict[str, Any]:
        path = self.directory(model_id) / filename
        if not path.is_file():
            raise ModelNotFoundError(f"model {model_id!r} not found")
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ModelCorruptedError(
                f"model {model_id!r} has unreadable {filename}: {exc}"
            ) from exc

    def ref(self, model_id: str) -> CompiledModelRef:
        manifest = self._read(model_id, _MANIFEST)
        return CompiledModelRef(
            model_id=model_id,
            version=manifest.get("version", ""),
            model_name=manifest.get("model_name", ""),
            spec_hash=manifest.get("spec_hash", ""),
            compile_hash=manifest.get("compile_hash", ""),
            model_hash=manifest.get("model_hash", ""),
            created_at=manifest.get("created_at"),
        )

    def list(self) -> list[CompiledModelRef]:
        if not self.models_dir.is_dir():
            return []
        references: list[CompiledModelRef] = []
        for directory in sorted(self.models_dir.iterdir()):
            if (
                not directory.is_dir()
                or not MODEL_ID_PATTERN.match(directory.name)
                or not (directory / _MANIFEST).is_file()
            ):
                continue
            try:
                references.append(self.ref(directory.name))
            except (ModelStoreError, ValueError):  # pragma: no cover - corrupt entry
                continue
        return references

    def schema(self, model_id: str) -> ModelSchema:
        return self.load(model_id).schema

    def load(self, model_id: str) -> CompiledModel:
        """Reconstruct and integrity-check a compiled model."""
        spec_raw = self._read(model_id, _SPEC)
        schema_raw = self._read(model_id, _SCHEMA)
        descriptor = self._read(model_id, _ARTIFACT)
        try:
            spec = ModelSpecification.model_validate(spec_raw)
            schema = ModelSchema.model_validate(schema_raw)
        except Exception as exc:
            raise ModelCorruptedError(
                f"model {model_id!r} does not reconstruct: {exc}"
            ) from exc

        compile_hash = descriptor.get("compile_hash")
        try:
            recomputed = compute_compile_hash(
                spec_hash=descriptor["spec_hash"],
                declared_model_id=descriptor["declared_model_id"],
                version=descriptor["version"],
                state_names=descriptor["state_names"],
                parameter_names=descriptor["parameter_names"],
                rate_expressions=descriptor["rate_expressions"],
                t_span=descriptor["t_span"],
                n_points=descriptor["n_points"],
                solver=descriptor["solver"],
                time_unit=descriptor["time_unit"],
            )
        except (KeyError, TypeError) as exc:
            raise ModelCorruptedError(
                f"model {model_id!r} artifact is incomplete: {exc}"
            ) from exc
        if recomputed != compile_hash:
            raise ModelCorruptedError(
                f"model {model_id!r} compile_hash does not match its artifact"
            )
        if model_id != "mdl-" + str(compile_hash)[:12]:
            raise ModelCorruptedError(
                f"model {model_id!r} does not match its compile_hash"
            )
        if spec.content_hash() != descriptor.get("spec_hash"):
            raise ModelCorruptedError(
                f"model {model_id!r} spec_hash does not match its source specification"
            )
        if schema.model_id != model_id:
            raise ModelCorruptedError(
                f"model {model_id!r} schema model_id does not match the artifact"
            )

        return CompiledModel(
            model_id=model_id,
            version=str(descriptor["version"]),
            spec=spec,
            spec_hash=str(descriptor["spec_hash"]),
            compile_hash=str(compile_hash),
            schema=schema,
            state_names=tuple(descriptor["state_names"]),
            parameter_names=tuple(descriptor["parameter_names"]),
            rate_expressions=dict(descriptor["rate_expressions"]),
            t_span=(float(descriptor["t_span"][0]), float(descriptor["t_span"][1])),
            n_points=int(descriptor["n_points"]),
            solver=str(descriptor["solver"]),
            time_unit=str(descriptor["time_unit"]),
            compiler_id=str(descriptor.get("compiler_id", "drw.model-compiler")),
            compiler_version=str(descriptor.get("compiler_version", "1.0.0")),
        )

    def build(self, model_id: str, **_kwargs: Any) -> Any:
        """Build the engine adapter for a stored model (used by the registry)."""
        return self.load(model_id).build_adapter()

    # -- write --------------------------------------------------------------

    def save(
        self, compiled: CompiledModel, *, created_at: str | None = None
    ) -> CompiledModelRef:
        model_id = compiled.model_id
        directory = self.directory(model_id)
        if directory.is_dir():
            return self.ref(model_id)  # idempotent: content-addressed

        descriptor = compiled.descriptor()
        # The descriptor carries the declared id so identity can be recomputed.
        descriptor["declared_model_id"] = compiled.spec.model_id
        documents = {
            _SPEC: to_plain(compiled.spec),
            _SCHEMA: to_plain(compiled.schema),
            _ARTIFACT: descriptor,
            _PROVENANCE: {
                "compiler_id": compiled.compiler_id,
                "compiler_version": compiled.compiler_version,
                "spec_hash": compiled.spec_hash,
                "compile_hash": compiled.compile_hash,
                "declared_model_id": compiled.spec.model_id,
                "assumptions": list(compiled.spec.assumptions),
                "source_reference": compiled.spec.provenance.source_reference,
                "author": compiled.spec.provenance.author,
                "generated_by": compiled.spec.provenance.generated_by,
            },
        }
        directory.mkdir(parents=True, exist_ok=True)
        files: list[dict[str, Any]] = []
        for name, document in documents.items():
            data = (dumps_pretty(document) + "\n").encode("utf-8")
            (directory / name).write_bytes(data)
            files.append(
                {"path": name, "sha256": sha256_hex(data), "size_bytes": len(data)}
            )
        manifest = {
            "schema_version": "1.0.0",
            "model_id": model_id,
            "version": compiled.version,
            "model_name": compiled.spec.model_id,
            "spec_hash": compiled.spec_hash,
            "compile_hash": compiled.compile_hash,
            "model_hash": compiled.schema.content_hash(),
            "created_at": created_at or _now(),
            "files": files,
        }
        (directory / _MANIFEST).write_bytes(
            (dumps_pretty(manifest) + "\n").encode("utf-8")
        )
        return self.ref(model_id)

    def verify(self, model_id: str) -> ModelVerification:
        directory = self.directory(model_id)
        manifest = self._read(model_id, _MANIFEST)
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
            compiled = self.load(model_id)
            matches = compiled.compile_hash == manifest.get("compile_hash")
        except (ModelStoreError, ValueError) as exc:
            matches = False
            checks.append({"name": "identity", "status": "failed", "message": str(exc)})
        else:
            checks.append(
                {
                    "name": "identity",
                    "status": "ok" if matches else "failed",
                    "message": "" if matches else "compile hash mismatch",
                }
            )
        errors = sum(1 for check in checks if check["status"] == "failed")
        return ModelVerification(
            model_id=model_id,
            compile_hash=manifest.get("compile_hash", ""),
            ok=errors == 0,
            checks=checks,
            errors=errors,
        )
