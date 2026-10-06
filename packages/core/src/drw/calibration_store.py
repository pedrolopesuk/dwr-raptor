"""Content-addressed persistence for calibration results (M12B, Phase D).

Mirrors the dataset store's principles (ADR-0017): append-only, content-addressed,
idempotent for an identical payload, and never silently overwriting a different
payload under an existing id. Layout under the workspace root::

    <root>/calibrations/<calibration_id>/
        config.json
        result.json        # the result without the (separately stored) history
        history.json       # the candidate history
        provenance.json
        manifest.json      # sha256 of each file + result_hash

``calibration_id = "cal-" + result_hash[:12]``. Persistence is deliberately
separate from the pure calibration core; nothing here executes a model.
"""

from __future__ import annotations

import json
import os
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from drw.schema.calibration import (
    CalibrationRef,
    CalibrationResult,
    compute_result_hash,
    short_calibration_id,
)
from drw.schema.serialization import dumps_pretty, sha256_hex, to_plain

__all__ = [
    "CALIBRATION_ID_PATTERN",
    "CalibrationCheck",
    "CalibrationExistsError",
    "CalibrationNotFoundError",
    "CalibrationStore",
    "CalibrationStoreError",
    "CalibrationVerification",
    "InvalidCalibrationId",
    "default_calibration_store",
]

CALIBRATION_ID_PATTERN = re.compile(r"^cal-[0-9a-f]{12}$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")

_CONFIG = "config.json"
_RESULT = "result.json"
_HISTORY = "history.json"
_PROVENANCE = "provenance.json"
_MANIFEST = "manifest.json"


class CalibrationStoreError(RuntimeError):
    """Base class for calibration-store failures."""


class InvalidCalibrationId(CalibrationStoreError, ValueError):
    """Raised for a malformed calibration id or a path that escapes the store."""


class CalibrationNotFoundError(CalibrationStoreError, KeyError):
    """Raised when a calibration id does not exist in the store."""


class CalibrationExistsError(CalibrationStoreError):
    """Raised when a different payload already occupies an existing id."""


class CalibrationCorruptedError(CalibrationStoreError):
    """Raised when a stored calibration cannot be reconstructed."""


class CalibrationCheck(BaseModel):
    """One verification check."""

    model_config = ConfigDict(extra="forbid")

    name: str
    status: Literal["ok", "failed"]
    message: str = ""


class CalibrationVerification(BaseModel):
    """The outcome of verifying a stored calibration against its manifest."""

    model_config = ConfigDict(extra="forbid")

    calibration_id: str
    result_hash: str
    ok: bool
    checks: list[CalibrationCheck]
    errors: int


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _default_root() -> Path:
    return Path(os.environ.get("DRW_WORKSPACE", ".drw/workspace"))


def default_calibration_store() -> CalibrationStore:
    """Build a store from ``DRW_WORKSPACE`` (read at call time)."""
    return CalibrationStore(_default_root())


class CalibrationStore:
    """Filesystem-backed, content-addressed store for calibration results."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)

    # -- paths --------------------------------------------------------------

    @property
    def calibrations_dir(self) -> Path:
        return self.root / "calibrations"

    def directory(self, calibration_id: str) -> Path:
        if not CALIBRATION_ID_PATTERN.match(calibration_id):
            raise InvalidCalibrationId(f"invalid calibration id {calibration_id!r}")
        base = self.calibrations_dir.resolve()
        candidate = (base / calibration_id).resolve()
        if candidate.parent != base:
            raise InvalidCalibrationId(f"calibration path escapes the store: {calibration_id!r}")
        return candidate

    # -- queries ------------------------------------------------------------

    def exists(self, calibration_id: str) -> bool:
        try:
            return (self.directory(calibration_id) / _MANIFEST).is_file()
        except InvalidCalibrationId:
            return False

    def _read_manifest(self, calibration_id: str) -> dict[str, Any]:
        path = self.directory(calibration_id) / _MANIFEST
        if not path.is_file():
            raise CalibrationNotFoundError(f"calibration {calibration_id!r} not found")
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise CalibrationCorruptedError(
                f"manifest for {calibration_id!r} is unreadable: {exc}"
            ) from exc

    def ref(self, calibration_id: str) -> CalibrationRef:
        manifest = self._read_manifest(calibration_id)
        return CalibrationRef(
            calibration_id=calibration_id,
            result_hash=manifest["result_hash"],
            experiment_id=manifest["experiment_id"],
            model_id=manifest["model_id"],
            status=manifest["status"],
            created_at=manifest.get("created_at"),
        )

    def list(self) -> list[CalibrationRef]:
        if not self.calibrations_dir.is_dir():
            return []
        refs = [
            self.ref(directory.name)
            for directory in sorted(self.calibrations_dir.iterdir())
            if directory.is_dir() and (directory / _MANIFEST).is_file()
        ]
        return refs

    # -- load / save --------------------------------------------------------

    def load(self, calibration_id: str) -> CalibrationResult:
        directory = self.directory(calibration_id)
        manifest = self._read_manifest(calibration_id)
        try:
            result_doc = json.loads((directory / _RESULT).read_text(encoding="utf-8"))
            history = json.loads((directory / _HISTORY).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise CalibrationCorruptedError(
                f"calibration {calibration_id!r} is unreadable: {exc}"
            ) from exc
        result_doc["history"] = history
        try:
            result = CalibrationResult.model_validate(result_doc)
        except Exception as exc:  # pragma: no cover - defensive
            raise CalibrationCorruptedError(
                f"calibration {calibration_id!r} does not reconstruct: {exc}"
            ) from exc
        if result.result_hash != manifest.get("result_hash"):
            raise CalibrationCorruptedError(
                f"calibration {calibration_id!r} result_hash does not match its manifest"
            )
        return result

    def save(self, result: CalibrationResult, *, created_at: str | None = None) -> CalibrationRef:
        """Persist a result (idempotent for an identical payload)."""
        calibration_id = short_calibration_id(result.result_hash)
        directory = self.directory(calibration_id)
        if directory.is_dir():
            existing = self._read_manifest(calibration_id)
            if existing.get("result_hash") != result.result_hash:
                raise CalibrationExistsError(
                    f"calibration {calibration_id!r} already exists with a different payload"
                )
            return self.ref(calibration_id)

        directory.mkdir(parents=True, exist_ok=True)
        plain = to_plain(result)
        history = plain.pop("history", [])
        documents = {
            _CONFIG: to_plain(result.config),
            _RESULT: plain,
            _HISTORY: history,
            _PROVENANCE: to_plain(result.provenance),
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
            "calibration_id": calibration_id,
            "result_hash": result.result_hash,
            "calibration_hash": result.calibration_hash,
            "experiment_id": result.experiment_id,
            "model_id": result.model_ref.model_id,
            "status": result.status,
            "created_at": created_at or _now(),
            "files": files,
        }
        (directory / _MANIFEST).write_bytes((dumps_pretty(manifest) + "\n").encode("utf-8"))
        return self.ref(calibration_id)

    # -- verification -------------------------------------------------------

    def verify(self, calibration_id: str) -> CalibrationVerification:
        """Recompute file hashes and the result hash (independent of save)."""
        directory = self.directory(calibration_id)
        manifest = self._read_manifest(calibration_id)
        checks: list[CalibrationCheck] = []

        for entry in manifest.get("files", []):
            name = entry.get("path", "")
            path = directory / name
            if not path.is_file():
                checks.append(CalibrationCheck(name=name, status="failed", message="missing"))
                continue
            data = path.read_bytes()
            if len(data) != entry.get("size_bytes") or sha256_hex(data) != entry.get("sha256"):
                checks.append(
                    CalibrationCheck(name=name, status="failed", message="hash/size mismatch")
                )
            else:
                checks.append(CalibrationCheck(name=name, status="ok"))

        try:
            result = self.load(calibration_id)
            recomputed = compute_result_hash(result)
            match = recomputed == result.result_hash
            checks.append(
                CalibrationCheck(
                    name="result_hash",
                    status="ok" if match else "failed",
                    message="" if match else "recomputed result hash does not match",
                )
            )
        except (CalibrationStoreError, ValueError) as exc:
            checks.append(CalibrationCheck(name="result_hash", status="failed", message=str(exc)))

        errors = sum(1 for check in checks if check.status == "failed")
        return CalibrationVerification(
            calibration_id=calibration_id,
            result_hash=manifest.get("result_hash", ""),
            ok=errors == 0,
            checks=checks,
            errors=errors,
        )
