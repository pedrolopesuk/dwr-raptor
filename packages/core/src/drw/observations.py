"""Pure operations over the M11A observation contract.

Nothing here performs calibration, fitting, interpolation, resampling or any
scientific inference. These are deterministic, side-effect-free helpers:

* constructing a content-addressed :class:`~drw.schema.observation.Dataset`
  (``build_dataset``);
* reference/identity handling (``resolve_dataset_id``, ``assert_same_dataset``);
* cross-artifact validation of an
  :class:`~drw.schema.observation.ObservationMapping` against a dataset and a
  model schema (``validate_mapping``);
* explicit unit conversion for a mapped pair (``convert_to_output``);
* explicit missing/quality usability accounting (``summarize_usability``) that
  never deletes an observation;
* ``exact`` coordinate alignment only (``align``) - interpolation, resampling,
  nearest-neighbour and aggregation are M12.

All failures are explicit exceptions or ``error`` diagnostics; nothing is ever
assumed, inferred, normalized or dropped silently.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Sequence
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from drw.schema.experiment import dedupe_diagnostics
from drw.schema.model import ModelSchema
from drw.schema.observation import (
    OBSERVATION_SCHEMA_VERSION,
    Dataset,
    DatasetFile,
    DatasetRef,
    ObservationMapping,
    ObservationSet,
    Provenance,
    Variable,
    classify_value,
    dataset_identity_payload,
    short_dataset_id,
)
from drw.schema.result import Diagnostic
from drw.schema.serialization import content_hash, to_plain
from drw.schema.units import UnitError, convert, units_compatible

__all__ = [
    "AlignmentResult",
    "ObservationError",
    "ObservationIdentityError",
    "UsabilityEntry",
    "UsabilitySummary",
    "align",
    "assert_same_dataset",
    "build_dataset",
    "convert_to_output",
    "make_dataset_ref",
    "resolve_dataset_id",
    "science_hash",
    "summarize_usability",
    "validate_mapping",
]


class ObservationError(ValueError):
    """Raised when observation operations cannot proceed."""


class ObservationIdentityError(ObservationError):
    """Raised on dataset identity ambiguity (short-id hash-prefix collision)."""


# ---------------------------------------------------------------------------
# Construction and identity.
# ---------------------------------------------------------------------------


def build_dataset(
    name: str,
    observation_set: ObservationSet,
    provenance: Provenance,
    *,
    description: str = "",
    labels: dict[str, str] | None = None,
    files: Iterable[DatasetFile] = (),
    schema_version: str = OBSERVATION_SCHEMA_VERSION,
) -> Dataset:
    """Build a content-addressed dataset (computes ``content_hash``/``dataset_id``)."""
    if not isinstance(name, str) or not name.strip():
        raise ObservationError("dataset name must be a non-empty string")
    labels_map = dict(labels or {})
    files_tuple = tuple(files)
    digest = content_hash(
        dataset_identity_payload(
            schema_version=schema_version,
            name=name,
            description=description,
            labels=labels_map,
            provenance=provenance,
            observation_set=observation_set,
            files=files_tuple,
        )
    )
    return Dataset(
        schema_version=schema_version,
        name=name,
        description=description,
        labels=labels_map,
        provenance=provenance,
        observation_set=observation_set,
        files=files_tuple,
        content_hash=digest,
        dataset_id=short_dataset_id(digest),
    )


def make_dataset_ref(dataset: Dataset) -> DatasetRef:
    """Return the reference for a dataset (id + authoritative content hash)."""
    return dataset.ref()


def science_hash(dataset: Dataset) -> str:
    """Derived **scientific-content** hash, independent of provenance.

    Hashes the coordinates, the per-variable contract (name, kind, role, unit,
    ``depends_on``, uncertainty and quality semantics) and the column values.
    It deliberately **excludes** provenance, ``created_at``, source filename/URI,
    ``imported_at``, adapter metadata and ``DatasetFile`` transport metadata. It is
    derived and additive: it never replaces or alters ``content_hash`` (the
    authoritative artifact identity) and is not stored on the dataset.
    """
    observation_set = dataset.observation_set
    variables = sorted(
        (
            {
                "name": variable.name,
                "kind": variable.kind,
                "role": variable.role,
                "unit": variable.unit,
                "depends_on": sorted(variable.depends_on),
                "uncertainty": to_plain(variable.uncertainty)
                if variable.uncertainty is not None
                else None,
                "quality": to_plain(variable.quality) if variable.quality is not None else None,
            }
            for variable in observation_set.variables
        ),
        key=lambda item: item["name"],
    )
    payload = {
        "schema_version": dataset.schema_version,
        "coordinates": sorted(observation_set.coordinates),
        "variables": variables,
        "columns": to_plain(observation_set.columns),
    }
    return content_hash(payload)


def resolve_dataset_id(dataset_id: str, known: Iterable[DatasetRef]) -> str:
    """Resolve a short dataset id to its unique full content hash.

    Raises :class:`ObservationIdentityError` when no reference matches or when
    two or more distinct full hashes share the id (a short-id prefix collision);
    a short id is never silently mapped to an arbitrary full hash.
    """
    hashes = {ref.content_hash for ref in known if ref.dataset_id == dataset_id}
    if not hashes:
        raise ObservationIdentityError(f"no dataset with id {dataset_id!r}")
    if len(hashes) > 1:
        raise ObservationIdentityError(
            f"dataset identity ambiguity: {len(hashes)} distinct content hashes share "
            f"the id {dataset_id!r} (hash-prefix collision); the full content_hash is authoritative"
        )
    return next(iter(hashes))


def assert_same_dataset(left: DatasetRef, right: DatasetRef) -> None:
    """Raise if two references claim the same id but different full hashes."""
    if left.dataset_id == right.dataset_id and left.content_hash != right.content_hash:
        raise ObservationIdentityError(
            f"dataset identity ambiguity: id {left.dataset_id!r} maps to both "
            f"{left.content_hash} and {right.content_hash}"
        )


# ---------------------------------------------------------------------------
# Usability (missing / quality). Never deletes an observation.
# ---------------------------------------------------------------------------


class UsabilityEntry(BaseModel):
    """Usability accounting for one measured variable (no rows are removed)."""

    model_config = ConfigDict(extra="forbid")

    variable: str
    total: int
    usable: int
    excluded: int
    reasons: dict[str, int] = Field(default_factory=dict)


class UsabilitySummary(BaseModel):
    """Per-variable usability of an observation set, with explicit reasons."""

    model_config = ConfigDict(extra="forbid")

    row_count: int
    entries: list[UsabilityEntry]
    note: str = (
        "observations are never deleted; unusable rows are reported with explicit reasons"
    )


def summarize_usability(observation_set: ObservationSet) -> UsabilitySummary:
    """Account for usable/unusable measured rows with explicit reasons.

    A row of a measured variable is unusable when its own value is
    ``missing``/``non_finite``/``invalid``, or when its quality flag maps to
    ``missing``/``invalid``/``censored``/``rejected``. A ``flagged`` row stays
    usable but is counted. No row is dropped or fabricated.
    """
    columns = observation_set.columns
    entries: list[UsabilityEntry] = []
    for variable in observation_set.variables:
        if variable.role not in ("measurement", "derived"):
            continue
        column = columns.get(variable.name, [])
        flags = columns.get(variable.quality.flag_column, []) if variable.quality else []
        reasons: dict[str, int] = {}
        usable = 0
        for index, value in enumerate(column):
            reason = classify_value(variable.kind, value)
            if reason is None and variable.quality is not None and index < len(flags):
                reason = variable.quality.reason_for(flags[index])
            if reason in (None, "flagged"):
                usable += 1
                if reason == "flagged":
                    reasons["flagged"] = reasons.get("flagged", 0) + 1
            else:
                reasons[reason] = reasons.get(reason, 0) + 1
        entries.append(
            UsabilityEntry(
                variable=variable.name,
                total=len(column),
                usable=usable,
                excluded=len(column) - usable,
                reasons=reasons,
            )
        )
    return UsabilitySummary(row_count=observation_set.row_count, entries=entries)


def _measured_variable(observation_set: ObservationSet, name: str) -> Variable | None:
    for variable in observation_set.variables:
        if variable.name == name:
            return variable
    return None


# ---------------------------------------------------------------------------
# Unit conversion for a mapped pair (explicit only; never silent).
# ---------------------------------------------------------------------------


def convert_to_output(
    value: float,
    *,
    observation_unit: str | None,
    output_unit: str,
    conversion: Any | None = None,
) -> float:
    """Convert an observation value into a model output's unit.

    Rules (all explicit): an **unspecified** observation unit is an error; units
    must be compatible; a conversion is applied only when one is declared; if the
    units differ but are compatible, an explicit conversion is required (no hidden
    scaling); incompatible units hard-fail.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(
        float(value)
    ):
        raise ObservationError("value must be a finite number")
    if observation_unit is None:
        raise ObservationError(
            "observation unit is unspecified; assign a unit (use 'dimensionless' for a "
            "genuine dimensionless quantity) before converting"
        )
    if conversion is not None:
        if conversion.from_unit != observation_unit or conversion.to_unit != output_unit:
            raise ObservationError(
                "unit_conversion does not match the observation and output units "
                f"({conversion.from_unit!r} -> {conversion.to_unit!r} vs "
                f"{observation_unit!r} -> {output_unit!r})"
            )
        if not units_compatible(conversion.from_unit, conversion.to_unit):
            raise ObservationError(
                f"incompatible units: cannot convert {conversion.from_unit!r} "
                f"to {conversion.to_unit!r}"
            )
        try:
            return convert(float(value), conversion.from_unit, conversion.to_unit)
        except UnitError as exc:  # pragma: no cover - defensive
            raise ObservationError(str(exc)) from exc
    if observation_unit == output_unit:
        return float(value)
    if units_compatible(observation_unit, output_unit):
        raise ObservationError(
            f"units {observation_unit!r} and {output_unit!r} are compatible but differ; "
            "declare an explicit unit_conversion (no hidden scaling)"
        )
    raise ObservationError(
        f"incompatible units: observation {observation_unit!r} vs output {output_unit!r}"
    )


# ---------------------------------------------------------------------------
# Mapping validation (cross-artifact checks).
# ---------------------------------------------------------------------------


def validate_mapping(
    mapping: ObservationMapping,
    *,
    dataset: Dataset,
    schema: ModelSchema,
) -> tuple[Diagnostic, ...]:
    """Validate a mapping against a concrete dataset and model schema.

    Returns ``error`` diagnostics (empty = valid) using the project convention.
    Structural checks live on the models; this performs the cross-artifact unit
    and reference checks. Nothing is assumed: unspecified units are rejected.
    """
    diagnostics: list[Diagnostic] = []

    def error(code: str, message: str) -> None:
        diagnostics.append(Diagnostic(level="error", code=code, message=message))

    reference = mapping.dataset
    if reference.dataset_id != dataset.dataset_id or reference.content_hash != dataset.content_hash:
        error(
            "dataset_mismatch",
            f"mapping references {reference.dataset_id}/{reference.content_hash} but the "
            f"dataset is {dataset.dataset_id}/{dataset.content_hash}",
        )
    if mapping.model_ref.model_id != schema.model_id:
        error(
            "model_mismatch",
            f"mapping references model {mapping.model_ref.model_id!r} but schema is "
            f"{schema.model_id!r}",
        )

    observation_set = dataset.observation_set
    outputs = {output.name: output for output in schema.outputs}

    for pair in mapping.pairs:
        variable = _measured_variable(observation_set, pair.observation)
        if variable is None:
            error("unknown_observation", f"dataset has no variable {pair.observation!r}")
            continue
        if variable.role != "measurement":
            error(
                "observation_not_measurement",
                f"variable {pair.observation!r} has role {variable.role!r}; only 'measurement' "
                "variables can be mapped",
            )
            continue
        output = outputs.get(pair.output)
        if output is None:
            error("unknown_output", f"model has no output {pair.output!r}")
            continue
        for coordinate in pair.coordinates:
            if coordinate not in observation_set.coordinates:
                error(
                    "unknown_coordinate",
                    f"pair {pair.observation!r} references unknown coordinate {coordinate!r}",
                )
            elif coordinate not in variable.depends_on:
                error(
                    "coordinate_not_dependent",
                    f"variable {pair.observation!r} does not depend on coordinate {coordinate!r}",
                )
        if variable.unit is None:
            error(
                "unspecified_unit",
                f"variable {pair.observation!r} has no unit; assign one (use 'dimensionless' "
                "for a genuine dimensionless quantity) - unspecified is not assumed compatible",
            )
            continue
        if not units_compatible(variable.unit, output.unit):
            error(
                "incompatible_units",
                f"variable {pair.observation!r} unit {variable.unit!r} is incompatible with "
                f"output {pair.output!r} unit {output.unit!r}",
            )
            continue
        if pair.unit_conversion is not None:
            conversion = pair.unit_conversion
            if conversion.from_unit != variable.unit or conversion.to_unit != output.unit:
                error(
                    "invalid_unit_conversion",
                    f"unit_conversion for {pair.observation!r} must be "
                    f"{variable.unit!r} -> {output.unit!r}",
                )
            elif not units_compatible(conversion.from_unit, conversion.to_unit):
                error(
                    "invalid_unit_conversion",
                    f"unit_conversion {conversion.from_unit!r} -> {conversion.to_unit!r} "
                    "is not dimensionally compatible",
                )
    return tuple(dedupe_diagnostics(diagnostics))


# ---------------------------------------------------------------------------
# Exact alignment only (M11). Interpolation/resampling/aggregation are M12.
# ---------------------------------------------------------------------------


class AlignmentResult(BaseModel):
    """The result of matching observation coordinates to model coordinates."""

    model_config = ConfigDict(extra="forbid")

    strategy: str
    tolerance: float
    reference_count: int
    query_count: int
    #: For each query (observation) value: the matched reference index, or None.
    matches: list[int | None]
    matched: int
    unmatched_query: list[int]
    unmatched_reference: list[int]


def align(
    reference: Sequence[float],
    query: Sequence[float],
    *,
    strategy: str = "exact",
    tolerance: float = 0.0,
) -> AlignmentResult:
    """Match numeric query coordinates to reference coordinates (``exact`` only).

    ``exact`` means ``abs(reference - query) <= tolerance``; the first matching
    reference index is used. Any other strategy is refused - interpolation,
    resampling, nearest-neighbour and aggregation belong to M12.
    """
    if strategy != "exact":
        raise ObservationError(
            f"unsupported alignment strategy {strategy!r}; only 'exact' is supported in M11"
        )
    if not math.isfinite(tolerance) or tolerance < 0:
        raise ObservationError("alignment tolerance must be finite and >= 0")

    def numbers(values: Sequence[float], label: str) -> list[float]:
        result: list[float] = []
        for value in values:
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ObservationError(f"{label} must be numeric, got {value!r}")
            result.append(float(value))
        return result

    ref = numbers(reference, "reference coordinate")
    qry = numbers(query, "query coordinate")
    matches: list[int | None] = []
    for value in qry:
        found: int | None = None
        for index, candidate in enumerate(ref):
            if abs(candidate - value) <= tolerance:
                found = index
                break
        matches.append(found)
    matched_reference = {index for index in matches if index is not None}
    return AlignmentResult(
        strategy="exact",
        tolerance=float(tolerance),
        reference_count=len(ref),
        query_count=len(qry),
        matches=matches,
        matched=sum(1 for index in matches if index is not None),
        unmatched_query=[index for index, value in enumerate(matches) if value is None],
        unmatched_reference=[index for index in range(len(ref)) if index not in matched_reference],
    )
