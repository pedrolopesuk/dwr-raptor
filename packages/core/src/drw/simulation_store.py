"""Content-addressed persistence for simulation results.

A simulation result is an inspectable artifact that links a source model, a
:class:`~drw.schema.simulation.SimulationSpec` and an explicitly synthetic dataset.
It is stored append-only and content-addressed, mirroring the other DRW stores.

Layout under the workspace root::

    <root>/simulations/<simulation_id>/{spec,result,provenance,manifest}.json

``simulation_id = "sim-" + simulation_hash[:12]`` where ``simulation_hash`` is the
deterministic content hash of the simulation specification, so the same request is
idempotent. Nothing here executes a model.
"""

from __future__ import annotations

import json
import os
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict

from drw.schema.serialization import dumps_pretty, sha256_hex, to_plain
from drw.schema.simulation import SimulationResult

__all__ = [
    "InvalidSimulationId",
    "SimulationNotFoundError",
    "SimulationRef",
    "SimulationStore",
    "SimulationStoreError",
    "SimulationVerification",
    "default_simulation_store",
]

SIMULATION_ID_PATTERN = re.compile(r"^sim-[0-9a-f]{12}$")

_SPEC = "spec.json"
_RESULT = "result.json"
_PROVENANCE = "provenance.json"
_MANIFEST = "manifest.json"


class SimulationStoreError(RuntimeError):
    """Base class for simulation-store failures."""


class InvalidSimulationId(SimulationStoreError, ValueError):
    """Raised for a malformed simulation id or a path that escapes the store."""


class SimulationNotFoundError(SimulationStoreError, KeyError):
    """Raised when a simulation id does not exist in the store."""


class SimulationRef(BaseModel):
    model_config = ConfigDict(extra="forbid")

    simulation_id: str
    simulation_hash: str
    model_id: str
    dataset_id: str | None = None
    created_at: str | None = None


class SimulationVerification(BaseModel):
    model_config = ConfigDict(extra="forbid")

    simulation_id: str
    simulation_hash: str
    ok: bool
    checks: list[dict[str, str]]
    errors: int


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _default_root() -> Path:
    return Path(os.environ.get("DRW_WORKSPACE", ".drw/workspace"))


def default_simulation_store() -> SimulationStore:
    return SimulationStore(_default_root())


def simulation_id_for(simulation_hash: str) -> str:
    return "sim-" + simulation_hash[:12]


class SimulationStore:
    """Filesystem-backed, content-addressed store for simulation results."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)

    @property
    def simulations_dir(self) -> Path:
        return self.root / "simulations"

    def directory(self, simulation_id: str) -> Path:
        if not isinstance(simulation_id, str) or not SIMULATION_ID_PATTERN.match(
            simulation_id
        ):
            raise InvalidSimulationId(f"invalid simulation id {simulation_id!r}")
        base = self.simulations_dir.resolve()
        candidate = (base / simulation_id).resolve()
        if candidate.parent != base:
            raise InvalidSimulationId(
                f"simulation path escapes the store: {simulation_id!r}"
            )
        return candidate

    def exists(self, simulation_id: str) -> bool:
        try:
            return (self.directory(simulation_id) / _MANIFEST).is_file()
        except InvalidSimulationId:
            return False

    def _read(self, simulation_id: str, filename: str) -> dict[str, Any]:
        path = self.directory(simulation_id) / filename
        if not path.is_file():
            raise SimulationNotFoundError(f"simulation {simulation_id!r} not found")
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise SimulationStoreError(
                f"simulation {simulation_id!r} has unreadable {filename}: {exc}"
            ) from exc

    def ref(self, simulation_id: str) -> SimulationRef:
        manifest = self._read(simulation_id, _MANIFEST)
        return SimulationRef(
            simulation_id=simulation_id,
            simulation_hash=manifest.get("simulation_hash", ""),
            model_id=manifest.get("model_id", ""),
            dataset_id=manifest.get("dataset_id"),
            created_at=manifest.get("created_at"),
        )

    def list(self) -> list[SimulationRef]:
        if not self.simulations_dir.is_dir():
            return []
        references: list[SimulationRef] = []
        for directory in sorted(self.simulations_dir.iterdir()):
            if (
                not directory.is_dir()
                or not SIMULATION_ID_PATTERN.match(directory.name)
                or not (directory / _MANIFEST).is_file()
            ):
                continue
            try:
                references.append(self.ref(directory.name))
            except (
                SimulationStoreError,
                ValueError,
            ):  # pragma: no cover - corrupt entry
                continue
        return references

    def load(self, simulation_id: str) -> SimulationResult:
        document = self._read(simulation_id, _RESULT)
        try:
            result = SimulationResult.model_validate(document)
        except Exception as exc:
            raise SimulationStoreError(
                f"simulation {simulation_id!r} does not reconstruct: {exc}"
            ) from exc
        if simulation_id_for(result.simulation_hash) != simulation_id:
            raise SimulationStoreError(
                f"simulation {simulation_id!r} does not match its simulation_hash"
            )
        return result

    def save(
        self, result: SimulationResult, *, created_at: str | None = None
    ) -> SimulationRef:
        simulation_id = simulation_id_for(result.simulation_hash)
        directory = self.directory(simulation_id)
        if directory.is_dir():
            return self.ref(simulation_id)  # idempotent for the same request
        directory.mkdir(parents=True, exist_ok=True)
        documents = {
            _SPEC: to_plain(result.spec),
            _RESULT: to_plain(result),
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
            "simulation_id": simulation_id,
            "simulation_hash": result.simulation_hash,
            "model_id": result.spec.model_ref.model_id,
            "dataset_id": result.dataset_ref.dataset_id if result.dataset_ref else None,
            "created_at": created_at or _now(),
            "files": files,
        }
        (directory / _MANIFEST).write_bytes(
            (dumps_pretty(manifest) + "\n").encode("utf-8")
        )
        return self.ref(simulation_id)

    def verify(self, simulation_id: str) -> SimulationVerification:
        directory = self.directory(simulation_id)
        manifest = self._read(simulation_id, _MANIFEST)
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
            result = self.load(simulation_id)
            matches = result.simulation_hash == manifest.get("simulation_hash")
        except (SimulationStoreError, ValueError) as exc:
            matches = False
            checks.append({"name": "identity", "status": "failed", "message": str(exc)})
        else:
            checks.append(
                {
                    "name": "identity",
                    "status": "ok" if matches else "failed",
                    "message": "" if matches else "simulation hash mismatch",
                }
            )
        errors = sum(1 for check in checks if check["status"] == "failed")
        return SimulationVerification(
            simulation_id=simulation_id,
            simulation_hash=manifest.get("simulation_hash", ""),
            ok=errors == 0,
            checks=checks,
            errors=errors,
        )
