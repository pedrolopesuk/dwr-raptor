"""Universal, domain-agnostic scientific observation/data contract (M11A).

This module defines **what an observation is** in DRW, independent of any
scientific domain. It represents astrophysics light curves, spacecraft
trajectories, physics response curves, biology replicate series and climate
point observations through the same contract - there is no domain-specific
field anywhere.

Hierarchy::

    Dataset                     # immutable identity + provenance (unit of reference)
     └─ ObservationSet          # the scientific payload: a table over coordinates
         ├─ coordinates         # ordered independent axes (time, x, wavelength, lat, lon, ...)
         └─ variables           # columns: coordinate / measurement / derived /
                                #          uncertainty / quality / metadata

The **Observation** is a semantic *row* (a coordinate tuple plus its measured
values); it is deliberately **not** a stored class.

Design rules enforced here (all explicit, never silent):

* ``unit=None`` means **unspecified**, which is distinct from ``"dimensionless"``.
  No unit is ever inferred.
* Units are not globally required on a dataset, but **compatibility becomes
  mandatory** when an :class:`~drw.schema.observation.ObservationMapping` pairs a
  variable with a model output (see :mod:`drw.observations`).
* **Repeated coordinate values are allowed** - coordinates do not uniquely
  identify rows (e.g. ``time=1, replicate=1`` and ``time=1, replicate=2``).
* **Derived** variables stay distinguishable from **measurement** variables.
* Quality flags never silently delete observations; missing values (``None``)
  have explicit semantics.
* Uncertainty is a **tagged** representation (``none``/``std``/``stderr``/
  ``asymmetric``/``interval``/``precision``); the types are never collapsed.
  Covariance/correlation are deferred (M12).
* Time is either an absolute ISO-8601 ``datetime`` coordinate or an elapsed
  numeric coordinate with an explicit unit (no JD/MJD/astronomical time systems;
  those belong to adapters).
* Multiple coordinate columns and multi-coordinate variables are supported;
  **N-dimensional array storage is deferred** (M12).

Data integrity reuses :mod:`drw.schema.serialization`: the dataset's full
``content_hash`` is authoritative and ``dataset_id = "ds-" + content_hash[:12]``.
Prefix-collision ambiguity is detected by
:func:`~drw.observations.resolve_dataset_id` / :func:`~drw.observations.assert_same_dataset`
- two different full hashes can never silently resolve to the same id.

M11A defines contracts only: no storage, no import adapters, no CLI/web.
"""

from __future__ import annotations

import math
import re
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from drw.schema.model import ModelRef
from drw.schema.serialization import content_hash, to_plain

__all__ = [
    "OBSERVATION_SCHEMA_VERSION",
    "AdapterRef",
    "AlignmentSpec",
    "AlignmentStrategy",
    "Dataset",
    "DatasetFile",
    "DatasetRef",
    "MappingPair",
    "MissingReason",
    "ObservationMapping",
    "ObservationSet",
    "PreprocessStep",
    "Provenance",
    "QualitySpec",
    "SourceKind",
    "UncertaintySpec",
    "UncertaintyType",
    "UnitConversion",
    "Variable",
    "VariableKind",
    "VariableRole",
    "classify_value",
    "compute_dataset_hash",
    "dataset_identity_payload",
    "short_dataset_id",
]


OBSERVATION_SCHEMA_VERSION = "1.0.0"

VariableKind = Literal["float", "int", "bool", "categorical", "datetime"]
VariableRole = Literal["coordinate", "measurement", "derived", "uncertainty", "quality", "metadata"]
UncertaintyType = Literal["none", "std", "stderr", "asymmetric", "interval", "precision"]
#: Only exact alignment is supported in M11; interpolation/resampling/aggregation
#: belong to M12.
AlignmentStrategy = Literal["exact"]
#: Reasons an observation may be unusable. ``flagged`` is *usable but noteworthy*.
MissingReason = Literal["missing", "non_finite", "invalid", "censored", "rejected", "flagged"]
SourceKind = Literal["file", "url", "manual", "synthetic", "derived"]

DATASET_ID_PATTERN = re.compile(r"^ds-[0-9a-f]{12}$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_.\-]*$")

_MEASURED_ROLES = ("measurement", "derived")
_NUMERIC_KINDS = ("float", "int")
_COORDINATE_KINDS = ("float", "int", "datetime")


def _check_identifier(value: str, label: str) -> str:
    if not isinstance(value, str) or not _IDENTIFIER.match(value):
        raise ValueError(
            f"{label} {value!r} must start with a letter/underscore and contain only "
            "letters, digits, '_', '.', '-'"
        )
    return value


def _parse_iso(value: str) -> datetime:
    """Parse an ISO-8601 timestamp (accepting a trailing ``Z``)."""
    text = value[:-1] + "+00:00" if value.endswith("Z") else value
    return datetime.fromisoformat(text)


def _check_iso(value: str | None) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"timestamp must be a string, got {type(value).__name__}")
    try:
        _parse_iso(value)
    except ValueError as exc:
        raise ValueError(f"timestamp {value!r} is not valid ISO-8601: {exc}") from exc
    return value


# ---------------------------------------------------------------------------
# Uncertainty (tagged; types are never collapsed).
# ---------------------------------------------------------------------------


class UncertaintySpec(BaseModel):
    """A tagged uncertainty for one measured variable.

    The ``type`` is authoritative: ``std`` (one standard deviation), ``stderr``
    (standard error), ``precision`` (known measurement precision), ``asymmetric``
    (lower/upper) and ``interval`` (lower/upper at a stated ``level``) are **not**
    interchangeable. A value may be inline or a **companion column** reference.
    Covariance and correlation are deliberately deferred (M12).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    type: UncertaintyType
    value: float | None = None
    column: str | None = None
    lower: float | None = None
    upper: float | None = None
    lower_column: str | None = None
    upper_column: str | None = None
    level: float | None = None
    note: str | None = None

    @model_validator(mode="after")
    def _check_consistency(self) -> UncertaintySpec:
        kind = self.type
        scalar = (self.value, self.column)
        interval = (self.lower, self.upper, self.lower_column, self.upper_column, self.level)

        def finite(name: str, value: float | None) -> None:
            if value is not None and (not math.isfinite(value)):
                raise ValueError(f"uncertainty {name} must be finite")

        if kind == "none":
            if any(item is not None for item in (*scalar, *interval)):
                raise ValueError("uncertainty type 'none' must not carry any values")
            return self

        if kind in ("std", "stderr", "precision"):
            if (self.value is None) == (self.column is None):
                raise ValueError(
                    f"uncertainty type {kind!r} requires exactly one of 'value' or 'column'"
                )
            finite("value", self.value)
            if self.value is not None and self.value < 0:
                raise ValueError("uncertainty value must be >= 0")
            if any(item is not None for item in interval):
                raise ValueError(f"uncertainty type {kind!r} must not carry interval fields")
            return self

        if kind == "asymmetric":
            if (self.lower is None) == (self.lower_column is None):
                raise ValueError(
                    "asymmetric uncertainty requires exactly one of 'lower' or 'lower_column'"
                )
            if (self.upper is None) == (self.upper_column is None):
                raise ValueError(
                    "asymmetric uncertainty requires exactly one of 'upper' or 'upper_column'"
                )
            finite("lower", self.lower)
            finite("upper", self.upper)
            if self.lower is not None and self.upper is not None and self.lower > self.upper:
                raise ValueError("asymmetric uncertainty requires lower <= upper")
            if self.value is not None or self.column is not None or self.level is not None:
                raise ValueError("asymmetric uncertainty must not carry value/column/level")
            return self

        if kind == "interval":
            if not isinstance(self.level, (int, float)) or isinstance(self.level, bool):
                raise ValueError("interval uncertainty requires a numeric 'level'")
            if not 0.0 < float(self.level) < 1.0:
                raise ValueError("interval uncertainty requires a level in (0, 1)")
            if (self.lower is None) == (self.lower_column is None):
                raise ValueError(
                    "interval uncertainty requires exactly one of 'lower' or 'lower_column'"
                )
            if (self.upper is None) == (self.upper_column is None):
                raise ValueError(
                    "interval uncertainty requires exactly one of 'upper' or 'upper_column'"
                )
            finite("lower", self.lower)
            finite("upper", self.upper)
            if self.lower is not None and self.upper is not None and self.lower > self.upper:
                raise ValueError("interval uncertainty requires lower <= upper")
            if self.value is not None or self.column is not None:
                raise ValueError("interval uncertainty must not carry value/column")
            return self

        return self  # pragma: no cover - exhaustive over the Literal

    def companion_columns(self) -> tuple[str, ...]:
        """Names of the companion variables this uncertainty references."""
        names = [name for name in (self.column, self.lower_column, self.upper_column) if name]
        return tuple(names)


class QualitySpec(BaseModel):
    """How a quality/flag companion column maps flag values to usability reasons.

    Flags are **descriptive**: they never delete an observation. A flag mapped to
    ``missing``/``invalid``/``censored``/``rejected`` marks a row unusable (with
    an explicit reason); a flag mapped to ``flagged`` leaves the row usable but
    noteworthy.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    flag_column: str
    missing_flags: tuple[str, ...] = ()
    invalid_flags: tuple[str, ...] = ()
    censored_flags: tuple[str, ...] = ()
    rejected_flags: tuple[str, ...] = ()
    flagged_flags: tuple[str, ...] = ()
    note: str | None = None

    @field_validator("flag_column")
    @classmethod
    def _check_flag_column(cls, value: str) -> str:
        return _check_identifier(value, "flag column name")

    def reason_for(self, flag: Any) -> MissingReason | None:
        """Map a flag value to a reason, in a fixed precedence order."""
        if flag is None:
            return None
        text = str(flag)
        if text in self.missing_flags:
            return "missing"
        if text in self.invalid_flags:
            return "invalid"
        if text in self.censored_flags:
            return "censored"
        if text in self.rejected_flags:
            return "rejected"
        if text in self.flagged_flags:
            return "flagged"
        return None


# ---------------------------------------------------------------------------
# Variables.
# ---------------------------------------------------------------------------


class Variable(BaseModel):
    """A named column of an :class:`ObservationSet`.

    ``role`` distinguishes a coordinate axis from a measured value, a derived
    value, a companion uncertainty column, a quality flag and per-row metadata.
    ``depends_on`` lists the coordinates the variable varies over (empty = it does
    not depend on any declared coordinate).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    kind: VariableKind
    role: VariableRole = "measurement"
    unit: str | None = None
    depends_on: tuple[str, ...] = ()
    uncertainty: UncertaintySpec | None = None
    quality: QualitySpec | None = None
    description: str = ""

    @field_validator("name")
    @classmethod
    def _check_name(cls, value: str) -> str:
        return _check_identifier(value, "variable name")

    @field_validator("unit")
    @classmethod
    def _check_unit(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if not isinstance(value, str) or not value.strip():
            raise ValueError("unit must be None (unspecified) or a non-empty string")
        return value

    @model_validator(mode="after")
    def _check_metadata(self) -> Variable:
        if self.uncertainty is not None and self.role not in _MEASURED_ROLES:
            raise ValueError(
                f"uncertainty is only valid on measured variables, not role {self.role!r}"
            )
        if self.quality is not None and self.role not in _MEASURED_ROLES:
            raise ValueError(
                f"quality is only valid on measured variables, not role {self.role!r}"
            )
        if len(set(self.depends_on)) != len(self.depends_on):
            raise ValueError(f"variable {self.name!r} lists duplicate coordinates in depends_on")
        return self


# ---------------------------------------------------------------------------
# The scientific payload.
# ---------------------------------------------------------------------------


class ObservationSet(BaseModel):
    """A table of variables over one or more shared coordinates.

    Rows are the semantic **observations**. ``columns`` holds the payload
    (columnar, one list per variable). Repeated coordinate values are allowed.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    coordinates: tuple[str, ...] = ()
    variables: tuple[Variable, ...]
    columns: dict[str, list[Any]] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _check_structure(self) -> ObservationSet:
        if not self.variables:
            raise ValueError("an observation set must declare at least one variable")
        names = [variable.name for variable in self.variables]
        duplicates = sorted({name for name in names if names.count(name) > 1})
        if duplicates:
            raise ValueError(f"duplicate variable names: {duplicates}")
        by_name = {variable.name: variable for variable in self.variables}

        if len(set(self.coordinates)) != len(self.coordinates):
            raise ValueError("coordinate names must be unique")
        for name in self.coordinates:
            variable = by_name.get(name)
            if variable is None:
                raise ValueError(f"coordinate {name!r} is not a declared variable")
            if variable.role != "coordinate":
                raise ValueError(f"coordinate {name!r} must have role 'coordinate'")
            if variable.kind not in _COORDINATE_KINDS:
                raise ValueError(
                    f"coordinate {name!r} must be float/int/datetime, got {variable.kind!r}"
                )
        coordinate_set = set(self.coordinates)
        for variable in self.variables:
            if variable.role == "coordinate" and variable.name not in coordinate_set:
                raise ValueError(
                    f"variable {variable.name!r} has role 'coordinate' but is not listed in coordinates"
                )
            missing = [name for name in variable.depends_on if name not in coordinate_set]
            if missing:
                raise ValueError(
                    f"variable {variable.name!r} depends on undeclared coordinate(s): {missing}"
                )
            if variable.uncertainty is not None:
                for companion in variable.uncertainty.companion_columns():
                    companion_variable = by_name.get(companion)
                    if companion_variable is None:
                        raise ValueError(
                            f"uncertainty for {variable.name!r} references unknown column {companion!r}"
                        )
                    if companion_variable.role != "uncertainty":
                        raise ValueError(
                            f"uncertainty companion {companion!r} must have role 'uncertainty'"
                        )
                    if companion_variable.kind not in _NUMERIC_KINDS:
                        raise ValueError(
                            f"uncertainty companion {companion!r} must be numeric"
                        )
            if variable.quality is not None:
                flag = by_name.get(variable.quality.flag_column)
                if flag is None:
                    raise ValueError(
                        f"quality flag column {variable.quality.flag_column!r} for "
                        f"{variable.name!r} is not a declared variable"
                    )
                if flag.role != "quality":
                    raise ValueError(
                        f"quality flag column {variable.quality.flag_column!r} must have role 'quality'"
                    )
                if flag.kind not in ("categorical", "int", "bool"):
                    raise ValueError(
                        f"quality flag column {variable.quality.flag_column!r} must be "
                        "categorical/int/bool"
                    )

        expected = set(names)
        provided = set(self.columns)
        if expected != provided:
            missing = sorted(expected - provided)
            extra = sorted(provided - expected)
            raise ValueError(
                f"columns must cover exactly the declared variables "
                f"(missing={missing}, unexpected={extra})"
            )
        lengths = {name: len(column) for name, column in self.columns.items()}
        distinct = set(lengths.values())
        if len(distinct) > 1:
            raise ValueError(f"all columns must have the same length, got {lengths}")
        for name, column in self.columns.items():
            kind = by_name[name].kind
            for index, value in enumerate(column):
                reason = classify_value(kind, value)
                # ``missing`` (None) is a valid, explicit stored value; only
                # non-finite and type-invalid cells are rejected.
                if reason is not None and reason != "missing":
                    raise ValueError(
                        f"column {name!r} row {index} is {reason} for kind {kind!r}: {value!r} "
                        "(represent missing values as null; non-finite is not storable)"
                    )
        return self

    @property
    def row_count(self) -> int:
        return len(self.columns[self.variables[0].name]) if self.variables else 0

    def column(self, name: str) -> list[Any]:
        """Return the raw column for ``name`` (raises :class:`KeyError`)."""
        if name not in self.columns:
            raise KeyError(f"no column named {name!r}")
        return self.columns[name]

    def rows(self) -> list[dict[str, Any]]:
        """Return the payload as a list of row dicts (the semantic observations)."""
        return [
            {name: column[index] for name, column in self.columns.items()}
            for index in range(self.row_count)
        ]


def classify_value(kind: str, value: Any) -> MissingReason | None:
    """Classify a raw cell against a variable kind (missing/non_finite/invalid)."""
    if value is None:
        return "missing"
    if kind == "float":
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return "invalid"
        return None if math.isfinite(float(value)) else "non_finite"
    if kind == "int":
        if isinstance(value, bool) or not isinstance(value, int):
            return "invalid"
        return None
    if kind == "bool":
        return None if isinstance(value, bool) else "invalid"
    if kind == "categorical":
        return None if isinstance(value, str) else "invalid"
    if kind == "datetime":
        if not isinstance(value, str):
            return "invalid"
        try:
            _parse_iso(value)
        except ValueError:
            return "invalid"
        return None
    return "invalid"  # pragma: no cover - exhaustive over the Literal


# ---------------------------------------------------------------------------
# Provenance.
# ---------------------------------------------------------------------------


class AdapterRef(BaseModel):
    """The import adapter that produced a dataset (id + version)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    version: str

    @field_validator("id")
    @classmethod
    def _check_id(cls, value: str) -> str:
        return _check_identifier(value, "adapter id")

    @field_validator("version")
    @classmethod
    def _check_version(cls, value: str) -> str:
        if not value:
            raise ValueError("adapter version must not be empty")
        return value


class PreprocessStep(BaseModel):
    """One recorded preprocessing/transformation step."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    operation: str
    version: str | None = None
    params: dict[str, Any] = Field(default_factory=dict)
    at: str | None = None

    @field_validator("at")
    @classmethod
    def _check_at(cls, value: str | None) -> str | None:
        return _check_iso(value)


class Provenance(BaseModel):
    """Where an observation dataset came from (contract only; M11B persists it)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    source_kind: SourceKind
    imported_at: str
    dataset_version: str
    adapter: AdapterRef | None = None
    source_id: str | None = None
    source_uri: str | None = None
    original_filename: str | None = None
    acquisition_time: str | None = None
    source_sha256: str | None = None
    preprocessing: tuple[PreprocessStep, ...] = ()
    notes: str = ""
    license: str | None = None

    @field_validator("imported_at", "acquisition_time")
    @classmethod
    def _check_times(cls, value: str | None) -> str | None:
        return _check_iso(value)

    @field_validator("dataset_version")
    @classmethod
    def _check_version(cls, value: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValueError("dataset_version must be a non-empty string")
        return value

    @field_validator("source_sha256")
    @classmethod
    def _check_sha(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if not isinstance(value, str) or not _HEX64.match(value):
            raise ValueError("source_sha256 must be a 64-character lowercase hex digest")
        return value


# ---------------------------------------------------------------------------
# Files and identity.
# ---------------------------------------------------------------------------


class DatasetFile(BaseModel):
    """A referenced payload/source file recorded in a dataset (metadata only)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    sha256: str
    size_bytes: int
    media_type: str | None = None
    role: Literal["source", "payload"] = "source"

    @field_validator("name")
    @classmethod
    def _check_name(cls, value: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValueError("file name must be a non-empty string")
        return value

    @field_validator("sha256")
    @classmethod
    def _check_sha(cls, value: str) -> str:
        if not isinstance(value, str) or not _HEX64.match(value):
            raise ValueError("sha256 must be a 64-character lowercase hex digest")
        return value

    @field_validator("size_bytes")
    @classmethod
    def _check_size(cls, value: int) -> int:
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ValueError("size_bytes must be a non-negative integer")
        return value


class DatasetRef(BaseModel):
    """A stable reference to an exact dataset version.

    Carries both the short ``dataset_id`` and the **authoritative** full
    ``content_hash``; the id is required to equal ``short_dataset_id(content_hash)``,
    so a reference can never point at an ambiguous prefix. ``created_at`` is
    optional storage-layer metadata (added in M11B) and is not part of identity.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    dataset_id: str
    content_hash: str
    name: str = ""
    created_at: str | None = None

    @field_validator("created_at")
    @classmethod
    def _check_created_at(cls, value: str | None) -> str | None:
        return _check_iso(value)

    @model_validator(mode="after")
    def _check_identity(self) -> DatasetRef:
        if not _HEX64.match(self.content_hash):
            raise ValueError("content_hash must be a 64-character lowercase hex digest")
        if not DATASET_ID_PATTERN.match(self.dataset_id):
            raise ValueError(f"invalid dataset id {self.dataset_id!r}")
        expected = short_dataset_id(self.content_hash)
        if self.dataset_id != expected:
            raise ValueError(
                f"dataset_id {self.dataset_id!r} does not match content_hash "
                f"(expected {expected!r})"
            )
        return self


class Dataset(BaseModel):
    """An immutable, content-addressed observation dataset.

    The full ``content_hash`` is authoritative; ``dataset_id`` is its 12-hex
    prefix (``ds-<12 hex>``). Both are validated against the canonical content, so
    a dataset can never be constructed with a mismatched identity.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: str = OBSERVATION_SCHEMA_VERSION
    name: str
    description: str = ""
    labels: dict[str, str] = Field(default_factory=dict)
    provenance: Provenance
    observation_set: ObservationSet
    files: tuple[DatasetFile, ...] = ()
    content_hash: str
    dataset_id: str

    @model_validator(mode="after")
    def _check_identity(self) -> Dataset:
        if not _HEX64.match(self.content_hash):
            raise ValueError("content_hash must be a 64-character lowercase hex digest")
        expected = compute_dataset_hash(self)
        if self.content_hash != expected:
            raise ValueError(
                "content_hash does not match the dataset content "
                f"(expected {expected}, got {self.content_hash})"
            )
        if self.dataset_id != short_dataset_id(self.content_hash):
            raise ValueError(
                f"dataset_id {self.dataset_id!r} does not match content_hash "
                f"(expected {short_dataset_id(self.content_hash)!r})"
            )
        return self

    def ref(self) -> DatasetRef:
        """Return the reference a future experiment/calibration would record."""
        return DatasetRef(
            dataset_id=self.dataset_id, content_hash=self.content_hash, name=self.name
        )


def dataset_identity_payload(
    *,
    schema_version: str,
    name: str,
    description: str,
    labels: dict[str, str],
    provenance: Provenance,
    observation_set: ObservationSet,
    files: tuple[DatasetFile, ...],
) -> dict[str, Any]:
    """The canonical, identity-defining payload (excludes the derived identity)."""
    return {
        "schema_version": schema_version,
        "name": name,
        "description": description,
        "labels": dict(labels),
        "provenance": to_plain(provenance),
        "observation_set": to_plain(observation_set),
        "files": to_plain(files),
    }


def compute_dataset_hash(dataset: Dataset) -> str:
    """Full SHA-256 content hash of a dataset (reuses canonical serialization)."""
    return content_hash(
        dataset_identity_payload(
            schema_version=dataset.schema_version,
            name=dataset.name,
            description=dataset.description,
            labels=dataset.labels,
            provenance=dataset.provenance,
            observation_set=dataset.observation_set,
            files=dataset.files,
        )
    )


def short_dataset_id(content_hash: str) -> str:
    """Derive the short dataset id from a full content hash (``ds-<12 hex>``)."""
    if not isinstance(content_hash, str) or not _HEX64.match(content_hash):
        raise ValueError("content_hash must be a 64-character lowercase hex digest")
    return f"ds-{content_hash[:12]}"


# ---------------------------------------------------------------------------
# Observation <-> model mapping (contract only; no fitting).
# ---------------------------------------------------------------------------


class UnitConversion(BaseModel):
    """An explicit unit conversion (``from_unit`` -> ``to_unit``); never implicit."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    from_unit: str
    to_unit: str

    @field_validator("from_unit", "to_unit")
    @classmethod
    def _check_unit(cls, value: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValueError("conversion units must be non-empty strings")
        return value


class MappingPair(BaseModel):
    """One observation variable mapped to one model output."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    observation: str
    output: str
    coordinates: tuple[str, ...] = ()
    unit_conversion: UnitConversion | None = None
    transform: Literal["identity"] = "identity"


class AlignmentSpec(BaseModel):
    """How observation coordinates are matched to model output coordinates.

    M11 supports **only** ``strategy="exact"`` with an explicit tolerance; any
    other strategy is rejected (interpolation/resampling/aggregation are M12).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    strategy: AlignmentStrategy = "exact"
    tolerance: float = 0.0

    @field_validator("tolerance")
    @classmethod
    def _check_tolerance(cls, value: float) -> float:
        if not math.isfinite(value) or value < 0:
            raise ValueError("alignment tolerance must be finite and >= 0")
        return value


class ObservationMapping(BaseModel):
    """A standalone mapping from an observation dataset to a model (no fitting).

    Deliberately separate from both the :class:`Dataset` (which stays
    model-agnostic) and any future calibration spec: it is the glue a future
    M12 calibration would consume. Structural validation happens here; the
    cross-artifact checks (variables, outputs, units, coordinates) are performed
    by :func:`drw.observations.validate_mapping`.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    dataset: DatasetRef
    model_ref: ModelRef
    pairs: tuple[MappingPair, ...]
    alignment: AlignmentSpec = Field(default_factory=AlignmentSpec)
    notes: str = ""

    @model_validator(mode="after")
    def _check_pairs(self) -> ObservationMapping:
        if not self.pairs:
            raise ValueError("an observation mapping must declare at least one pair")
        names = [pair.observation for pair in self.pairs]
        duplicates = sorted({name for name in names if names.count(name) > 1})
        if duplicates:
            raise ValueError(f"duplicate mapped observations: {duplicates}")
        return self
