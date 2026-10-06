"""Persistent, immutable, content-addressed storage for M11A datasets (M11B).

Layout under the workspace root (``DRW_WORKSPACE``)::

    <root>/
        datasets/
            <dataset_id>/                 # dataset_id = "ds-" + content_hash[:12]
                meta.json                 # identity + descriptive metadata + DatasetFile list
                schema.json               # coordinates + variables (the ObservationSet shape)
                data.json                 # the columns (the observation payload)
                provenance.json           # the M11A Provenance object
                files/                    # packaged referenced files (only when present)

Datasets are **append-only and content-addressed**: saving the same dataset again
is idempotent, while saving a *different* dataset under an existing id fails
(never silently overwritten). Every id is validated and every resolved path is
contained to the workspace, mirroring :class:`drw.store.ExperimentStore`.

Notes:

* The **full** ``content_hash`` is authoritative; ``verify`` recomputes it from the
  reconstructed content and refuses to "repair" a mismatch.
* Referenced ``DatasetFile`` metadata is stored, but the bytes are only present
  when the file has been **packaged** into ``files/`` - verification hash-checks a
  packaged file and reports a merely-referenced (external) file as
  ``not_packaged``, never as verified.
* This is storage only: no import adapters, no calibration, no CLI/web.
"""

from __future__ import annotations

import json
import os
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from drw.observations import ObservationError, build_dataset
from drw.schema.observation import (
    DATASET_ID_PATTERN,
    OBSERVATION_SCHEMA_VERSION,
    Dataset,
    DatasetFile,
    DatasetRef,
    ObservationSet,
    Provenance,
    compute_dataset_hash,
    short_dataset_id,
)
from drw.schema.serialization import dumps_pretty, sha256_hex, to_plain

__all__ = [
    "DatasetCheck",
    "DatasetCorruptedError",
    "DatasetExistsError",
    "DatasetNotFoundError",
    "DatasetStore",
    "DatasetStoreError",
    "DatasetVerification",
    "InvalidDatasetId",
    "default_dataset_store",
]

_HEX64 = re.compile(r"^[0-9a-f]{64}$")

_META_FILENAME = "meta.json"
_SCHEMA_FILENAME = "schema.json"
_DATA_FILENAME = "data.json"
_PROVENANCE_FILENAME = "provenance.json"
_FILES_DIRNAME = "files"
_REQUIRED = (
    ("meta", _META_FILENAME),
    ("schema", _SCHEMA_FILENAME),
    ("data", _DATA_FILENAME),
    ("provenance", _PROVENANCE_FILENAME),
)

CheckStatus = Literal["ok", "missing", "unreadable", "invalid", "mismatch", "not_packaged"]
_FAILING_STATUSES = ("missing", "unreadable", "invalid", "mismatch")


# ---------------------------------------------------------------------------
# Errors.
# ---------------------------------------------------------------------------


class DatasetStoreError(ValueError):
    """Base class for dataset storage failures."""


class InvalidDatasetId(DatasetStoreError):
    """Raised when a dataset id is malformed or would escape the workspace."""


class DatasetExistsError(DatasetStoreError):
    """Raised when a different dataset would overwrite an existing dataset id."""


class DatasetCorruptedError(DatasetStoreError):
    """Raised when stored dataset files cannot be reconstructed faithfully."""


class DatasetNotFoundError(DatasetStoreError, KeyError):
    """Raised when a dataset id (or content hash) has no stored dataset."""


# ---------------------------------------------------------------------------
# Verification result.
# ---------------------------------------------------------------------------


class DatasetCheck(BaseModel):
    """One verification check for a stored dataset."""

    model_config = ConfigDict(extra="forbid")

    name: str
    status: CheckStatus
    message: str = ""


class DatasetVerification(BaseModel):
    """Structured verification result for a stored dataset.

    ``ok`` is ``True`` only when every required check passed. A referenced file
    that is not packaged locally is reported ``not_packaged`` and does **not** fail
    verification (it was never claimed to be present); a packaged file with the
    wrong bytes is a ``mismatch`` and does.
    """

    model_config = ConfigDict(extra="forbid")

    schema_version: str = "1.0.0"
    dataset_id: str
    content_hash: str | None = None
    ok: bool
    errors: int
    checks: list[DatasetCheck]
    extra_files: list[str] = Field(default_factory=list)
    note: str = (
        "verification is a consistency check over locally stored bytes; a "
        "referenced file that is not packaged locally is reported, never verified"
    )


# ---------------------------------------------------------------------------
# Helpers.
# ---------------------------------------------------------------------------


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(dumps_pretty(payload) + "\n", encoding="utf-8")


def default_dataset_store() -> DatasetStore:
    """Build a dataset store from ``DRW_WORKSPACE`` (read at call time)."""
    return DatasetStore(Path(os.environ.get("DRW_WORKSPACE", ".drw/workspace")))


# ---------------------------------------------------------------------------
# Store.
# ---------------------------------------------------------------------------


class DatasetStore:
    """Filesystem-backed, immutable store for M11A datasets."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)

    # -- paths --------------------------------------------------------------

    def _contained(self, *parts: str) -> Path:
        candidate = (self.root.joinpath(*parts)).resolve()
        root = self.root.resolve()
        if root != candidate and root not in candidate.parents:
            raise InvalidDatasetId(f"path escapes the workspace: {'/'.join(parts)}")
        return candidate

    def dataset_dir(self, dataset_id: str) -> Path:
        if not isinstance(dataset_id, str) or not DATASET_ID_PATTERN.match(dataset_id):
            raise InvalidDatasetId(f"invalid dataset id {dataset_id!r}")
        candidate = self._contained("datasets", dataset_id)
        expected = (self.root / "datasets").resolve()
        if candidate.parent != expected:
            raise InvalidDatasetId(f"dataset path escapes the workspace: {dataset_id!r}")
        return candidate

    def _packaged_path(self, directory: Path, name: str) -> Path:
        if not isinstance(name, str) or not name:
            raise InvalidDatasetId("packaged file name must be a non-empty string")
        relative = Path(name)
        if relative.is_absolute() or ".." in relative.parts:
            raise InvalidDatasetId(f"unsafe packaged file name {name!r}")
        files_dir = (directory / _FILES_DIRNAME).resolve()
        resolved = (files_dir / relative).resolve()
        if resolved != files_dir and files_dir not in resolved.parents:
            raise InvalidDatasetId(f"packaged file path escapes the dataset: {name!r}")
        return files_dir / relative

    # -- write ---------------------------------------------------------------

    def save(self, dataset: Dataset) -> Path:
        """Persist ``dataset`` and return its directory (append-only, idempotent)."""
        directory = self.dataset_dir(dataset.dataset_id)
        if not _HEX64.match(dataset.content_hash):
            raise DatasetCorruptedError("content_hash must be a 64-character lowercase hex digest")
        if compute_dataset_hash(dataset) != dataset.content_hash:
            raise DatasetCorruptedError("content_hash does not match the dataset content")

        if directory.exists():
            meta_path = directory / _META_FILENAME
            if not meta_path.is_file():
                raise DatasetCorruptedError(
                    f"dataset directory {dataset.dataset_id!r} exists without {_META_FILENAME}"
                )
            existing = _read_json(meta_path)
            if isinstance(existing, dict) and existing.get("content_hash") == dataset.content_hash:
                return directory  # idempotent: the exact same dataset already exists
            raise DatasetExistsError(
                f"refusing to overwrite dataset {dataset.dataset_id!r}: the id is already bound "
                "to a different content_hash (possible short-id collision); datasets are immutable"
            )

        if dataset.dataset_id != short_dataset_id(dataset.content_hash):
            raise DatasetCorruptedError("dataset_id does not match content_hash")

        directory.mkdir(parents=True, exist_ok=False)
        self._write(directory, dataset)
        return directory

    def _write(self, directory: Path, dataset: Dataset) -> None:
        meta = {
            "dataset_id": dataset.dataset_id,
            "content_hash": dataset.content_hash,
            "name": dataset.name,
            "description": dataset.description,
            "labels": to_plain(dataset.labels),
            "schema_version": dataset.schema_version,
            "created_at": _now(),
            "files": to_plain(dataset.files),
        }
        schema = {
            "coordinates": list(dataset.observation_set.coordinates),
            "variables": to_plain(dataset.observation_set.variables),
        }
        data = {"columns": to_plain(dataset.observation_set.columns)}
        _write_json(directory / _META_FILENAME, meta)
        _write_json(directory / _SCHEMA_FILENAME, schema)
        _write_json(directory / _DATA_FILENAME, data)
        _write_json(directory / _PROVENANCE_FILENAME, to_plain(dataset.provenance))
        (directory / _FILES_DIRNAME).mkdir(parents=True, exist_ok=True)

    def package_file(self, dataset_id: str, source: str | Path, *, name: str | None = None) -> Path:
        """Copy a local file into ``files/`` after checking it against the declared hash.

        This is a storage primitive (it makes a dataset self-contained for
        portability), not an import adapter: it never downloads anything and it
        refuses to package bytes that do not match the dataset's ``DatasetFile``
        metadata, and never overwrites an existing packaged file.
        """
        dataset = self.load(dataset_id)
        packaged_name = name or Path(source).name
        entry = next((item for item in dataset.files if item.name == packaged_name), None)
        if entry is None:
            raise DatasetStoreError(
                f"dataset {dataset_id!r} declares no file named {packaged_name!r}"
            )
        data = Path(source).read_bytes()
        if len(data) != entry.size_bytes or sha256_hex(data) != entry.sha256:
            raise DatasetStoreError(
                f"file bytes do not match the declared DatasetFile metadata for {packaged_name!r}"
            )
        directory = self.dataset_dir(dataset_id)
        destination = self._packaged_path(directory, packaged_name)
        (directory / _FILES_DIRNAME).mkdir(parents=True, exist_ok=True)
        if destination.is_file():
            if destination.read_bytes() == data:
                return destination  # idempotent
            raise DatasetExistsError(f"refusing to overwrite packaged file {packaged_name!r}")
        destination.write_bytes(data)
        return destination

    # -- reconstruct ---------------------------------------------------------

    def _components(
        self, loaded: dict[str, Any]
    ) -> tuple[ObservationSet, Provenance, tuple[DatasetFile, ...]]:
        schema = loaded.get("schema")
        data = loaded.get("data")
        provenance = loaded.get("provenance")
        meta = loaded.get("meta")
        if not all(isinstance(item, dict) for item in (schema, data, provenance, meta)):
            raise DatasetCorruptedError("a dataset file is not a JSON object")
        try:
            observation_set = ObservationSet.model_validate(
                {
                    "coordinates": schema.get("coordinates", []),
                    "variables": schema.get("variables", []),
                    "columns": data.get("columns", {}),
                }
            )
        except ValidationError as exc:
            raise DatasetCorruptedError(f"cannot reconstruct the observation set: {exc}") from exc
        try:
            provenance_obj = Provenance.model_validate(provenance)
        except ValidationError as exc:
            raise DatasetCorruptedError(f"cannot reconstruct provenance: {exc}") from exc
        files_raw = meta.get("files", [])
        if not isinstance(files_raw, list):
            raise DatasetCorruptedError("meta.files must be a list")
        try:
            files = tuple(DatasetFile.model_validate(entry) for entry in files_raw)
        except ValidationError as exc:
            raise DatasetCorruptedError(f"cannot reconstruct DatasetFile metadata: {exc}") from exc
        return observation_set, provenance_obj, files

    def _recompute(self, meta: dict[str, Any], loaded: dict[str, Any]) -> Dataset:
        """Rebuild the dataset from its content, independently of stored identity."""
        observation_set, provenance, files = self._components(loaded)
        try:
            return build_dataset(
                name=meta.get("name") or "",
                observation_set=observation_set,
                provenance=provenance,
                description=meta.get("description", ""),
                labels=meta.get("labels") or {},
                files=files,
                schema_version=meta.get("schema_version") or OBSERVATION_SCHEMA_VERSION,
            )
        except (ObservationError, ValidationError) as exc:
            raise DatasetCorruptedError(f"cannot reconstruct the dataset: {exc}") from exc

    # -- read ----------------------------------------------------------------

    def exists(self, dataset_id: str) -> bool:
        try:
            return (self.dataset_dir(dataset_id) / _META_FILENAME).is_file()
        except InvalidDatasetId:
            return False

    def load(self, dataset_id: str) -> Dataset:
        """Load and fully reconstruct a stored dataset (fails loudly if corrupt)."""
        directory = self.dataset_dir(dataset_id)
        if not directory.is_dir() or not (directory / _META_FILENAME).is_file():
            raise DatasetNotFoundError(f"dataset {dataset_id!r} not found")
        loaded: dict[str, Any] = {}
        for key, filename in _REQUIRED:
            path = directory / filename
            if not path.is_file():
                raise DatasetCorruptedError(f"dataset {dataset_id!r} is missing {filename}")
            try:
                loaded[key] = _read_json(path)
            except (OSError, json.JSONDecodeError) as exc:
                raise DatasetCorruptedError(f"dataset {dataset_id!r} has unreadable {filename}: {exc}") from exc
        meta = loaded["meta"]
        if not isinstance(meta, dict) or meta.get("dataset_id") != dataset_id:
            raise DatasetCorruptedError("meta.dataset_id does not match the directory name")
        dataset = self._recompute(meta, loaded)
        if meta.get("content_hash") != dataset.content_hash:
            raise DatasetCorruptedError(
                "stored content_hash does not match the reconstructed content"
            )
        if meta.get("dataset_id") != dataset_id or dataset.dataset_id != dataset_id:
            raise DatasetCorruptedError("stored identity does not match the reconstructed dataset")
        return dataset

    def ref(self, dataset_id: str) -> DatasetRef:
        """Return the reference for a stored dataset (reads metadata only)."""
        directory = self.dataset_dir(dataset_id)
        meta_path = directory / _META_FILENAME
        if not meta_path.is_file():
            raise DatasetNotFoundError(f"dataset {dataset_id!r} not found")
        try:
            meta = _read_json(meta_path)
        except (OSError, json.JSONDecodeError) as exc:
            raise DatasetCorruptedError(f"dataset {dataset_id!r} has unreadable metadata: {exc}") from exc
        if not isinstance(meta, dict) or meta.get("dataset_id") != dataset_id:
            raise DatasetCorruptedError("meta.dataset_id does not match the directory name")
        content_hash = meta.get("content_hash")
        if not isinstance(content_hash, str) or not _HEX64.match(content_hash):
            raise DatasetCorruptedError("meta.content_hash is missing or malformed")
        if short_dataset_id(content_hash) != dataset_id:
            raise DatasetCorruptedError("dataset_id does not match the stored content_hash")
        return DatasetRef(
            dataset_id=dataset_id,
            content_hash=content_hash,
            name=meta.get("name", ""),
            created_at=meta.get("created_at"),
        )

    def provenance(self, dataset_id: str) -> Provenance:
        """Return the stored provenance for a dataset (reads ``provenance.json`` only)."""
        directory = self.dataset_dir(dataset_id)
        path = directory / _PROVENANCE_FILENAME
        if not path.is_file():
            raise DatasetNotFoundError(f"dataset {dataset_id!r} not found")
        try:
            raw = _read_json(path)
        except (OSError, json.JSONDecodeError) as exc:
            raise DatasetCorruptedError(
                f"dataset {dataset_id!r} has unreadable provenance: {exc}"
            ) from exc
        try:
            return Provenance.model_validate(raw)
        except ValidationError as exc:
            raise DatasetCorruptedError(
                f"dataset {dataset_id!r} has invalid provenance: {exc}"
            ) from exc

    def resolve(self, content_hash: str) -> DatasetRef:
        """Look up a dataset by its authoritative full content hash."""
        if not isinstance(content_hash, str) or not _HEX64.match(content_hash):
            raise DatasetStoreError("content_hash must be a 64-character lowercase hex digest")
        dataset_id = short_dataset_id(content_hash)
        directory = self.dataset_dir(dataset_id)
        if not (directory / _META_FILENAME).is_file():
            raise DatasetNotFoundError(f"no dataset with content hash {content_hash}")
        reference = self.ref(dataset_id)
        if reference.content_hash != content_hash:
            raise DatasetNotFoundError(f"no dataset with content hash {content_hash}")
        return reference

    def list(self) -> list[DatasetRef]:
        """Return references to every stored dataset, deterministically ordered.

        Only ``meta.json`` is read (never the observation payload). Directory names
        are validated and unrelated entries are ignored; a dataset whose stored
        identity is inconsistent is excluded (and is reported by :meth:`verify`).
        """
        datasets_root = self.root / "datasets"
        if not datasets_root.is_dir():
            return []
        references: list[DatasetRef] = []
        for directory in sorted(datasets_root.iterdir()):
            if not directory.is_dir() or not DATASET_ID_PATTERN.match(directory.name):
                continue
            meta_path = directory / _META_FILENAME
            if not meta_path.is_file():
                continue
            try:
                meta = _read_json(meta_path)
            except (OSError, json.JSONDecodeError):
                continue
            if not isinstance(meta, dict):
                continue
            content_hash = meta.get("content_hash")
            if (
                meta.get("dataset_id") != directory.name
                or not isinstance(content_hash, str)
                or not _HEX64.match(content_hash)
                or short_dataset_id(content_hash) != directory.name
            ):
                continue
            try:
                references.append(
                    DatasetRef(
                        dataset_id=directory.name,
                        content_hash=content_hash,
                        name=meta.get("name", ""),
                        created_at=meta.get("created_at"),
                    )
                )
            except ValidationError:
                continue
        references.sort(key=lambda item: (item.created_at or "", item.dataset_id), reverse=True)
        return references

    # -- verify --------------------------------------------------------------

    def verify(self, dataset_id: str) -> DatasetVerification:
        """Verify a stored dataset's files, identity and packaged bytes (read-only)."""
        directory = self.dataset_dir(dataset_id)  # validates the id format
        checks: list[DatasetCheck] = []
        if not directory.is_dir():
            checks.append(
                DatasetCheck(name="directory", status="missing", message="dataset directory not found")
            )
            return self._finish(dataset_id, None, checks, [])

        loaded: dict[str, Any] = {}
        for key, filename in _REQUIRED:
            path = directory / filename
            if not path.is_file():
                checks.append(DatasetCheck(name=key, status="missing", message=f"{filename} not found"))
                continue
            try:
                loaded[key] = _read_json(path)
            except (OSError, json.JSONDecodeError) as exc:
                checks.append(DatasetCheck(name=key, status="unreadable", message=str(exc)))
                continue
            checks.append(DatasetCheck(name=key, status="ok"))

        meta = loaded.get("meta")
        stored_hash = meta.get("content_hash") if isinstance(meta, dict) else None
        if len(loaded) != len(_REQUIRED) or not isinstance(meta, dict):
            return self._finish(
                dataset_id, stored_hash if isinstance(stored_hash, str) else None, checks, []
            )

        try:
            dataset = self._recompute(meta, loaded)
        except DatasetCorruptedError as exc:
            checks.append(DatasetCheck(name="reconstruction", status="invalid", message=str(exc)))
            return self._finish(
                dataset_id, stored_hash if isinstance(stored_hash, str) else None, checks, []
            )

        checks.append(
            DatasetCheck(
                name="dataset_id",
                status="ok" if meta.get("dataset_id") == dataset_id else "mismatch",
                message="" if meta.get("dataset_id") == dataset_id else "meta.dataset_id ≠ directory name",
            )
        )
        checks.append(
            DatasetCheck(
                name="content_hash",
                status="ok" if meta.get("content_hash") == dataset.content_hash else "mismatch",
                message=""
                if meta.get("content_hash") == dataset.content_hash
                else "stored content_hash ≠ recomputed content hash",
            )
        )
        checks.append(
            DatasetCheck(
                name="identity",
                status="ok" if dataset.dataset_id == dataset_id else "mismatch",
                message=""
                if dataset.dataset_id == dataset_id
                else "dataset_id is not the short hash of the content",
            )
        )
        extra_files = self._verify_files(directory, dataset, checks)
        return self._finish(dataset_id, dataset.content_hash, checks, extra_files)

    def _verify_files(
        self, directory: Path, dataset: Dataset, checks: list[DatasetCheck]
    ) -> list[str]:
        declared: set[str] = set()
        for entry in dataset.files:
            declared.add(entry.name)
            try:
                path = self._packaged_path(directory, entry.name)
            except InvalidDatasetId as exc:
                checks.append(DatasetCheck(name=f"file:{entry.name}", status="invalid", message=str(exc)))
                continue
            if not path.is_file():
                checks.append(
                    DatasetCheck(
                        name=f"file:{entry.name}",
                        status="not_packaged",
                        message="referenced file is not packaged locally (external metadata only)",
                    )
                )
                continue
            data = path.read_bytes()
            matches = len(data) == entry.size_bytes and sha256_hex(data) == entry.sha256
            checks.append(
                DatasetCheck(
                    name=f"file:{entry.name}",
                    status="ok" if matches else "mismatch",
                    message=""
                    if matches
                    else "packaged bytes do not match the declared sha256/size",
                )
            )
        files_dir = directory / _FILES_DIRNAME
        if not files_dir.is_dir():
            return []
        extras: list[str] = []
        for candidate in sorted(files_dir.iterdir()):
            if candidate.is_file() and candidate.name not in declared:
                extras.append(candidate.name)
        return extras

    def _finish(
        self,
        dataset_id: str,
        content_hash: str | None,
        checks: list[DatasetCheck],
        extra_files: list[str],
    ) -> DatasetVerification:
        errors = sum(1 for check in checks if check.status in _FAILING_STATUSES)
        return DatasetVerification(
            dataset_id=dataset_id,
            content_hash=content_hash,
            ok=errors == 0,
            errors=errors,
            checks=checks,
            extra_files=extra_files,
        )
