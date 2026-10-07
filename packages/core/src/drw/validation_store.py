"""Content-addressed persistence for validation results (M12C-D).

Mirrors the calibration store's principles (ADR-0017): append-only,
content-addressed, idempotent for an identical payload, and never silently
overwriting a different payload under an existing id. Layout under the workspace
root::

    <root>/validations/<validation_id>/
        config.json
        result.json
        provenance.json
        manifest.json      # sha256 of each file + result_hash

``validation_id = "val-" + result_hash[:12]``. Persistence is deliberately
separate from the pure validation core; nothing here executes a model.

Staleness is computed **on read** from the recorded hashes and the current
artifacts (never stored as a mutable flag): a stored validation is stale when any
scientific dependency it recorded no longer matches.
"""

from __future__ import annotations

import json
import os
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from drw.schema.serialization import content_hash, dumps_pretty, sha256_hex, to_plain
from drw.schema.validation import (
    VALIDATION_ID_PATTERN,
    ValidationRef,
    ValidationResult,
    compute_validation_result_hash,
    short_validation_id,
)

__all__ = [
    "VALIDATION_ID_PATTERN",
    "InvalidValidationId",
    "ValidationCheck",
    "ValidationCorruptedError",
    "ValidationExistsError",
    "ValidationNotFoundError",
    "ValidationStaleness",
    "ValidationStore",
    "ValidationStoreError",
    "ValidationVerification",
    "check_validation_staleness",
    "default_validation_store",
]

_HEX64 = re.compile(r"^[0-9a-f]{64}$")

_CONFIG = "config.json"
_RESULT = "result.json"
_PROVENANCE = "provenance.json"
_MANIFEST = "manifest.json"


class ValidationStoreError(RuntimeError):
    """Base class for validation-store failures."""


class InvalidValidationId(ValidationStoreError, ValueError):
    """Raised for a malformed validation id or a path that escapes the store."""


class ValidationNotFoundError(ValidationStoreError, KeyError):
    """Raised when a validation id does not exist in the store."""


class ValidationExistsError(ValidationStoreError):
    """Raised when a different payload already occupies an existing id."""


class ValidationCorruptedError(ValidationStoreError):
    """Raised when a stored validation cannot be reconstructed."""


class ValidationCheck(BaseModel):
    """One verification check."""

    model_config = ConfigDict(extra="forbid")

    name: str
    status: Literal["ok", "failed"]
    message: str = ""


class ValidationVerification(BaseModel):
    """The outcome of verifying a stored validation against its manifest."""

    model_config = ConfigDict(extra="forbid")

    validation_id: str
    result_hash: str
    ok: bool
    checks: list[ValidationCheck]
    errors: int


class ValidationStaleness(BaseModel):
    """Whether a stored validation is still current, with the reasons why not."""

    model_config = ConfigDict(extra="forbid")

    validation_id: str
    result_hash: str
    fresh: bool
    reasons: list[str] = Field(default_factory=list)
    checks: list[ValidationCheck] = Field(default_factory=list)


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _default_root() -> Path:
    return Path(os.environ.get("DRW_WORKSPACE", ".drw/workspace"))


def default_validation_store() -> ValidationStore:
    """Build a store from ``DRW_WORKSPACE`` (read at call time)."""
    return ValidationStore(_default_root())


class ValidationStore:
    """Filesystem-backed, content-addressed store for validation results."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)

    # -- paths --------------------------------------------------------------

    @property
    def validations_dir(self) -> Path:
        return self.root / "validations"

    def directory(self, validation_id: str) -> Path:
        if not VALIDATION_ID_PATTERN.match(validation_id):
            raise InvalidValidationId(f"invalid validation id {validation_id!r}")
        base = self.validations_dir.resolve()
        candidate = (base / validation_id).resolve()
        if candidate.parent != base:
            raise InvalidValidationId(f"validation path escapes the store: {validation_id!r}")
        return candidate

    # -- queries ------------------------------------------------------------

    def exists(self, validation_id: str) -> bool:
        try:
            return (self.directory(validation_id) / _MANIFEST).is_file()
        except InvalidValidationId:
            return False

    def _read_manifest(self, validation_id: str) -> dict[str, Any]:
        path = self.directory(validation_id) / _MANIFEST
        if not path.is_file():
            raise ValidationNotFoundError(f"validation {validation_id!r} not found")
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValidationCorruptedError(
                f"manifest for {validation_id!r} is unreadable: {exc}"
            ) from exc

    def ref(self, validation_id: str) -> ValidationRef:
        manifest = self._read_manifest(validation_id)
        return ValidationRef(
            validation_id=validation_id,
            result_hash=manifest["result_hash"],
            experiment_id=manifest["experiment_id"],
            model_id=manifest["model_id"],
            agreement_status=manifest["agreement_status"],
            created_at=manifest.get("created_at"),
        )

    def list(self) -> list[ValidationRef]:
        if not self.validations_dir.is_dir():
            return []
        return [
            self.ref(directory.name)
            for directory in sorted(self.validations_dir.iterdir())
            if directory.is_dir() and (directory / _MANIFEST).is_file()
        ]

    # -- load / save --------------------------------------------------------

    def load(self, validation_id: str) -> ValidationResult:
        directory = self.directory(validation_id)
        manifest = self._read_manifest(validation_id)
        try:
            result_doc = json.loads((directory / _RESULT).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValidationCorruptedError(
                f"validation {validation_id!r} is unreadable: {exc}"
            ) from exc
        try:
            result = ValidationResult.model_validate(result_doc)
        except Exception as exc:  # pragma: no cover - defensive
            raise ValidationCorruptedError(
                f"validation {validation_id!r} does not reconstruct: {exc}"
            ) from exc
        if result.result_hash != manifest.get("result_hash"):
            raise ValidationCorruptedError(
                f"validation {validation_id!r} result_hash does not match its manifest"
            )
        return result

    def save(self, result: ValidationResult, *, created_at: str | None = None) -> ValidationRef:
        """Persist a result (idempotent for an identical payload)."""
        validation_id = short_validation_id(result.result_hash)
        directory = self.directory(validation_id)
        if directory.is_dir():
            existing = self._read_manifest(validation_id)
            if existing.get("result_hash") != result.result_hash:
                raise ValidationExistsError(
                    f"validation {validation_id!r} already exists with a different payload"
                )
            return self.ref(validation_id)

        directory.mkdir(parents=True, exist_ok=True)
        documents = {
            _CONFIG: to_plain(result.config),
            _RESULT: to_plain(result),
            _PROVENANCE: to_plain(result.provenance),
        }
        files: list[dict[str, Any]] = []
        for name, document in documents.items():
            data = (dumps_pretty(document) + "\n").encode("utf-8")
            (directory / name).write_bytes(data)
            files.append({"path": name, "sha256": sha256_hex(data), "size_bytes": len(data)})

        manifest = {
            "schema_version": "1.0.0",
            "validation_id": validation_id,
            "result_hash": result.result_hash,
            "validation_hash": result.validation_hash,
            "experiment_id": result.experiment_id,
            "model_id": result.model_ref.model_id,
            "agreement_status": result.agreement_status,
            "created_at": created_at or _now(),
            "files": files,
        }
        (directory / _MANIFEST).write_bytes((dumps_pretty(manifest) + "\n").encode("utf-8"))
        return self.ref(validation_id)

    # -- verification -------------------------------------------------------

    def verify(self, validation_id: str) -> ValidationVerification:
        """Recompute file hashes and the result hash (independent of save)."""
        directory = self.directory(validation_id)
        manifest = self._read_manifest(validation_id)
        checks: list[ValidationCheck] = []

        for entry in manifest.get("files", []):
            name = entry.get("path", "")
            path = directory / name
            if not path.is_file():
                checks.append(ValidationCheck(name=name, status="failed", message="missing"))
                continue
            data = path.read_bytes()
            if len(data) != entry.get("size_bytes") or sha256_hex(data) != entry.get("sha256"):
                checks.append(
                    ValidationCheck(name=name, status="failed", message="hash/size mismatch")
                )
            else:
                checks.append(ValidationCheck(name=name, status="ok"))

        try:
            result = self.load(validation_id)
            recomputed = compute_validation_result_hash(result)
            match = recomputed == result.result_hash
            checks.append(
                ValidationCheck(
                    name="result_hash",
                    status="ok" if match else "failed",
                    message="" if match else "recomputed result hash does not match",
                )
            )
        except (ValidationStoreError, ValueError) as exc:
            checks.append(ValidationCheck(name="result_hash", status="failed", message=str(exc)))

        errors = sum(1 for check in checks if check.status == "failed")
        return ValidationVerification(
            validation_id=validation_id,
            result_hash=manifest.get("result_hash", ""),
            ok=errors == 0,
            checks=checks,
            errors=errors,
        )


def _dataset_available(dataset_store: Any, content_hash: str) -> bool:
    """Whether a dataset with this content hash is resolvable (missing ⇒ not available)."""
    try:
        return dataset_store.resolve(content_hash) is not None
    except Exception:
        return False


def check_validation_staleness(
    result: ValidationResult,
    *,
    calibration_store: Any | None = None,
    dataset_store: Any | None = None,
    current_model_hash: str | None = None,
    current_environment_hash: str | None = None,
) -> ValidationStaleness:
    """Compare a stored validation's recorded hashes to the current artifacts.

    A stale result is never silently authoritative: the reasons are returned and
    recomputation is an explicit user action producing a new result.
    """
    checks: list[ValidationCheck] = []
    reasons: list[str] = []

    def record(name: str, ok: bool, reason: str | None, message: str) -> None:
        if ok:
            checks.append(ValidationCheck(name=name, status="ok", message=message))
            return
        checks.append(ValidationCheck(name=name, status="failed", message=message))
        if reason is not None:
            reasons.append(reason)

    if calibration_store is not None:
        try:
            calibration = calibration_store.load(result.calibration.calibration_id)
            matches = calibration.result_hash == result.calibration.result_hash
            record(
                "calibration_result",
                matches,
                None if matches else "calibration_result_changed",
                "the referenced calibration result still matches"
                if matches
                else "the referenced calibration result changed",
            )
        except Exception:
            record(
                "calibration_result",
                False,
                "calibration_result_missing",
                "the referenced calibration result is no longer available",
            )

    if dataset_store is not None:
        calibration_available = _dataset_available(
            dataset_store, result.calibration.dataset_content_hash
        )
        record(
            "calibration_dataset",
            calibration_available,
            None if calibration_available else "calibration_dataset_missing",
            "the calibration dataset is available"
            if calibration_available
            else "the calibration dataset is no longer available",
        )
        missing = [
            content
            for content in result.provenance.validation_dataset_content_hashes
            if not _dataset_available(dataset_store, content)
        ]
        record(
            "validation_datasets",
            not missing,
            None if not missing else "validation_dataset_missing",
            "every validation dataset is available"
            if not missing
            else f"validation dataset(s) no longer available: {', '.join(missing)}",
        )

    if current_model_hash is not None:
        matches = current_model_hash == result.provenance.model_hash
        record(
            "model",
            matches,
            None if matches else "model_changed",
            "the model is unchanged" if matches else "the model definition changed",
        )

    recorded_mapping_hashes = tuple(result.provenance.mapping_hashes)
    current_mapping_hashes = tuple(content_hash(item.mapping) for item in result.config.datasets)
    mappings_match = recorded_mapping_hashes == current_mapping_hashes
    record(
        "mapping",
        mappings_match,
        None if mappings_match else "mapping_changed",
        "the observation mappings are unchanged"
        if mappings_match
        else "an observation mapping changed",
    )

    current_eval_hash = content_hash(result.config.evaluation)
    eval_match = current_eval_hash == result.provenance.evaluation_config_hash
    record(
        "evaluation_config",
        eval_match,
        None if eval_match else "evaluation_config_changed",
        "the evaluation configuration is unchanged"
        if eval_match
        else "the evaluation configuration changed",
    )

    if current_environment_hash is not None:
        env_match = current_environment_hash == result.provenance.environment_hash
        record(
            "environment",
            env_match,
            None if env_match else "environment_changed",
            "the environment is unchanged"
            if env_match
            else "the execution environment changed (disclosure)",
        )

    return ValidationStaleness(
        validation_id=short_validation_id(result.result_hash),
        result_hash=result.result_hash,
        fresh=not reasons,
        reasons=reasons,
        checks=checks,
    )
