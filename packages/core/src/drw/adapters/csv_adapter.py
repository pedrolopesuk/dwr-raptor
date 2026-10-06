"""CSV observation adapter (M11C).

Turns a CSV file into the M11A :class:`~drw.schema.observation.Dataset` contract
using the Python standard library only (``csv``), with **zero** new dependency.

Two operations, deliberately separated:

* :meth:`CsvAdapter.inspect` - reads the file and returns *advisory* structure
  (columns, inferred primitive kinds, counts, a preview, candidate roles). It does
  **not** persist anything and never turns a suggestion into scientific semantics.
* :meth:`CsvAdapter.read` - parses the file under an explicit
  :class:`CsvImportConfig` and builds a validated dataset. Roles, units,
  uncertainty meaning, coordinates, missing codes and datetime interpretation are
  configuration decisions, never inferred.

Structural inference (int/float/bool/categorical/datetime) is safe; **scientific**
inference (units, physical quantity, measurement/uncertainty meaning, domain) is
not performed. Non-finite/invalid cells are handled explicitly (error by default,
or an explicit ``missing`` policy) and never silently rewritten. Datetimes are
ISO-8601 via the standard library - no astronomical time systems.
"""

from __future__ import annotations

import csv
import io
import math
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from drw.adapters import register_adapter
from drw.observations import ObservationError, build_dataset
from drw.schema.observation import (
    AdapterRef,
    Dataset,
    ObservationSet,
    PreprocessStep,
    Provenance,
    QualitySpec,
    UncertaintySpec,
    Variable,
    VariableKind,
    VariableRole,
)
from drw.schema.result import Diagnostic
from drw.schema.serialization import sha256_hex

__all__ = [
    "CSV_ADAPTER_ID",
    "CSV_ADAPTER_VERSION",
    "ColumnConfig",
    "ColumnInspection",
    "CsvAdapter",
    "CsvImportConfig",
    "CsvInspection",
    "DatasetImportError",
    "InspectionError",
    "import_csv",
]

CSV_ADAPTER_ID = "csv"
CSV_ADAPTER_VERSION = "1.0.0"

_DELIMITERS = (",", ";", "\t", "|")
_COORDINATE_HINTS = frozenset(
    {
        "t", "time", "timestamp", "date", "datetime", "x", "y", "z",
        "lat", "latitude", "lon", "longitude", "alt", "altitude", "depth",
        "wavelength", "wavenumber", "frequency", "freq", "energy", "radius",
        "distance", "phase", "index", "position",
    }
)
_QUALITY_HINTS = frozenset({"flag", "flags", "quality", "qc", "status", "mask", "valid", "good"})
_UNCERTAINTY_SUFFIXES = ("_err", "_error", "_sigma", "_std", "_stderr", "_se", "_unc", "_uncertainty")
_TRUE = frozenset({"true", "yes", "1"})
_FALSE = frozenset({"false", "no", "0"})


class InspectionError(ValueError):
    """Raised when a source cannot be inspected."""


class DatasetImportError(ValueError):
    """Raised when a source cannot be imported under the given configuration."""

    def __init__(self, message: str, diagnostics: list[Diagnostic] | None = None) -> None:
        super().__init__(message)
        self.diagnostics = list(diagnostics or [])


# ---------------------------------------------------------------------------
# Advisory inspection models.
# ---------------------------------------------------------------------------


class ColumnInspection(BaseModel):
    """Advisory structure for one CSV column (a suggestion, never a fact)."""

    model_config = ConfigDict(extra="forbid")

    column: str
    index: int
    kind: VariableKind
    missing_count: int = 0
    non_finite_count: int = 0
    sample_values: list[str] = Field(default_factory=list)
    suggested_role: VariableRole | None = None
    suggested_name: str | None = None
    suggested_uncertainty_for: str | None = None
    note: str | None = None


class CsvInspection(BaseModel):
    """The advisory result of inspecting a CSV file."""

    model_config = ConfigDict(extra="forbid")

    adapter_id: str = CSV_ADAPTER_ID
    adapter_version: str = CSV_ADAPTER_VERSION
    filename: str
    delimiter: str
    has_header: bool
    row_count: int
    columns: list[ColumnInspection]
    preview: list[dict[str, str]] = Field(default_factory=list)
    diagnostics: list[Diagnostic] = Field(default_factory=list)
    advisory: str = (
        "detections are advisory only: assign roles, units, coordinates and "
        "uncertainty explicitly in the import configuration"
    )


# ---------------------------------------------------------------------------
# Explicit import configuration (the only source of scientific semantics).
# ---------------------------------------------------------------------------


class ColumnConfig(BaseModel):
    """Explicit mapping of one CSV column to one M11A variable.

    Companion references inside ``uncertainty``/``quality`` use the *destination
    variable names* (which default to the source header), and are validated by the
    M11A observation contract.
    """

    model_config = ConfigDict(extra="forbid")

    column: str
    role: VariableRole
    name: str | None = None
    kind: VariableKind | None = None
    unit: str | None = None
    depends_on: tuple[str, ...] = ()
    uncertainty: UncertaintySpec | None = None
    quality: QualitySpec | None = None
    missing_codes: tuple[str, ...] = ()
    description: str = ""
    datetime_format: str | None = None


class CsvImportConfig(BaseModel):
    """The explicit configuration that turns a CSV into a dataset."""

    model_config = ConfigDict(extra="forbid")

    name: str
    columns: tuple[ColumnConfig, ...]
    description: str = ""
    labels: dict[str, str] = Field(default_factory=dict)
    dataset_version: str = "1.0.0"
    delimiter: str | None = None
    has_header: bool | None = None
    missing_codes: tuple[str, ...] = ()
    non_finite_policy: Literal["error", "missing"] = "error"
    invalid_policy: Literal["error", "missing"] = "error"
    imported_at: str | None = None
    license: str | None = None
    notes: str = ""


# ---------------------------------------------------------------------------
# Parsing helpers.
# ---------------------------------------------------------------------------


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _sanitize(name: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_.\-]", "_", name.strip())
    if not cleaned or not re.match(r"^[A-Za-z_]", cleaned):
        cleaned = "_" + cleaned
    return cleaned


def _parse_float(text: str) -> float | None:
    try:
        return float(text)
    except (TypeError, ValueError):
        return None


def _is_int(text: str) -> bool:
    try:
        int(text)
    except (TypeError, ValueError):
        return False
    return True


def _is_bool(text: str) -> bool:
    lowered = text.strip().lower()
    return lowered in _TRUE or lowered in _FALSE


def _parse_bool(text: str) -> bool | None:
    lowered = text.strip().lower()
    if lowered in _TRUE:
        return True
    if lowered in _FALSE:
        return False
    return None


def _parse_datetime(text: str, fmt: str | None) -> datetime | None:
    try:
        if fmt:
            return datetime.strptime(text, fmt)
        return datetime.fromisoformat(text[:-1] + "+00:00" if text.endswith("Z") else text)
    except (TypeError, ValueError):
        return None


def _infer_kind(values: list[str]) -> VariableKind:
    if not values:
        return "categorical"
    if all(_is_int(value) for value in values):
        return "int"
    if all(_parse_float(value) is not None for value in values):
        return "float"
    if all(_parse_datetime(value, None) is not None for value in values):
        return "datetime"
    if all(_is_bool(value) for value in values):
        return "bool"
    return "categorical"


class _Table:
    def __init__(
        self,
        *,
        columns: list[str],
        rows: list[list[str]],
        delimiter: str,
        has_header: bool,
        diagnostics: list[Diagnostic],
        sha256: str,
    ) -> None:
        self.columns = columns
        self.rows = rows
        self.delimiter = delimiter
        self.has_header = has_header
        self.diagnostics = diagnostics
        self.sha256 = sha256


def _sniff_delimiter(sample: str) -> str:
    best, best_count = ",", 0
    for candidate in _DELIMITERS:
        count = sample.count(candidate)
        if count > best_count:
            best, best_count = candidate, count
    return best


def _load_table(
    source: str | Path, *, delimiter: str | None = None, has_header: bool | None = None
) -> _Table:
    path = Path(source)
    if not path.is_file():
        raise InspectionError(f"file not found: {path}")
    try:
        raw = path.read_bytes()
        text = raw.decode("utf-8-sig")
    except (OSError, UnicodeDecodeError) as exc:
        raise InspectionError(f"could not read {path.name!r}: {exc}") from exc

    if delimiter is None:
        sample = next((line for line in text.splitlines() if line.strip()), "")
        delimiter = _sniff_delimiter(sample)

    rows = [
        row
        for row in csv.reader(io.StringIO(text), delimiter=delimiter)
        if row and any(cell.strip() for cell in row)
    ]
    diagnostics: list[Diagnostic] = []

    if not rows:
        return _Table(
            columns=[], rows=[], delimiter=delimiter, has_header=False,
            diagnostics=diagnostics, sha256=sha256_hex(raw),
        )

    if has_header is None:
        has_header = not all(_parse_float(cell) is not None for cell in rows[0])

    if has_header:
        columns = list(rows[0])
        data = rows[1:]
    else:
        columns = [f"column_{index + 1}" for index in range(len(rows[0]))]
        data = rows

    duplicates = sorted({name for name in columns if columns.count(name) > 1})
    if duplicates:
        diagnostics.append(
            Diagnostic(
                level="warning",
                code="duplicate_columns",
                message=f"duplicate columns: {duplicates}",
            )
        )
    ragged = [index for index, row in enumerate(data) if len(row) != len(columns)]
    if ragged:
        diagnostics.append(
            Diagnostic(
                level="warning",
                code="ragged_rows",
                message=(
                    f"{len(ragged)} data row(s) do not match the {len(columns)} "
                    f"column(s): {ragged[:10]}"
                ),
            )
        )
    return _Table(
        columns=columns, rows=data, delimiter=delimiter, has_header=has_header,
        diagnostics=diagnostics, sha256=sha256_hex(raw),
    )


def _column_cells(table: _Table, index: int) -> list[str]:
    return [row[index] if index < len(row) else "" for row in table.rows]


def _is_missing(cell: str, codes: frozenset[str]) -> bool:
    stripped = cell.strip()
    return stripped == "" or stripped in codes


def _suggest_role(name: str, kind: VariableKind) -> tuple[VariableRole | None, str | None]:
    lowered = name.strip().lower()
    if lowered in _QUALITY_HINTS or lowered.startswith("flag"):
        return "quality", "name suggests a quality flag (advisory)"
    if lowered in _COORDINATE_HINTS or kind == "datetime":
        return "coordinate", "name/kind suggests a coordinate (advisory)"
    if kind in ("float", "int"):
        return "measurement", None
    if kind in ("categorical", "bool"):
        return "metadata", None
    return None, None


def _inspect_column(
    table: _Table, index: int, name: str, codes: frozenset[str], all_names: set[str]
) -> ColumnInspection:
    cells = _column_cells(table, index)
    missing = 0
    non_finite = 0
    non_missing: list[str] = []
    for cell in cells:
        if _is_missing(cell, codes):
            missing += 1
            continue
        parsed = _parse_float(cell)
        if parsed is not None and not math.isfinite(parsed):
            non_finite += 1
        non_missing.append(cell.strip())

    kind = _infer_kind(non_missing)
    suggested_role, note = _suggest_role(name, kind)
    suggested_for: str | None = None
    lowered = name.strip().lower()
    for suffix in _UNCERTAINTY_SUFFIXES:
        if kind in ("float", "int") and lowered.endswith(suffix) and len(lowered) > len(suffix):
            base = name[: -len(suffix)]
            if base in all_names:
                suggested_for = base
    if suggested_for is not None:
        suggested_role = "uncertainty"
    if not non_missing:
        note = "no non-missing values"
    return ColumnInspection(
        column=name,
        index=index,
        kind=kind,
        missing_count=missing,
        non_finite_count=non_finite,
        sample_values=non_missing[:5],
        suggested_role=suggested_role,
        suggested_name=_sanitize(name),
        suggested_uncertainty_for=suggested_for,
        note=note,
    )


# ---------------------------------------------------------------------------
# Adapter.
# ---------------------------------------------------------------------------


class CsvAdapter:
    """The built-in CSV observation adapter."""

    id = CSV_ADAPTER_ID
    version = CSV_ADAPTER_VERSION

    def can_handle(self, source: str | Path) -> bool:
        return Path(str(source)).suffix.lower() == ".csv"

    def inspect(
        self,
        source: str | Path,
        *,
        delimiter: str | None = None,
        has_header: bool | None = None,
        missing_codes: tuple[str, ...] = (),
        preview_limit: int = 10,
    ) -> CsvInspection:
        """Return an advisory, non-persistent inspection of a CSV file."""
        table = _load_table(source, delimiter=delimiter, has_header=has_header)
        codes = frozenset({code.strip() for code in missing_codes if code != ""})
        all_names = set(table.columns)
        columns = [
            _inspect_column(table, index, name, codes, all_names)
            for index, name in enumerate(table.columns)
        ]
        preview = [
            {
                name: (row[index] if index < len(row) else "")
                for index, name in enumerate(table.columns)
            }
            for row in table.rows[: max(0, preview_limit)]
        ]
        return CsvInspection(
            filename=Path(source).name,
            delimiter=table.delimiter,
            has_header=table.has_header,
            row_count=len(table.rows),
            columns=columns,
            preview=preview,
            diagnostics=table.diagnostics,
        )

    def read(self, source: str | Path, config: CsvImportConfig) -> Dataset:
        """Parse ``source`` under ``config`` into a validated dataset."""
        if not config.columns:
            raise DatasetImportError("the import configuration declares no columns")
        table = _load_table(source, delimiter=config.delimiter, has_header=config.has_header)
        if not table.columns:
            raise DatasetImportError("the source has no columns")
        if any(len(row) != len(table.columns) for row in table.rows):
            raise DatasetImportError(
                "the source has rows that do not match the column count",
                [d for d in table.diagnostics if d.code == "ragged_rows"] or table.diagnostics,
            )
        index_of = {name: index for index, name in enumerate(table.columns)}
        duplicates = sorted({name for name in table.columns if table.columns.count(name) > 1})
        if duplicates:
            raise DatasetImportError(f"the source has duplicate columns: {duplicates}")

        global_codes = frozenset({code.strip() for code in config.missing_codes if code != ""})
        variables: list[Variable] = []
        columns: dict[str, list[Any]] = {}
        diagnostics: list[Diagnostic] = []

        for column_config in config.columns:
            if column_config.column not in index_of:
                raise DatasetImportError(
                    f"config references unknown column {column_config.column!r}"
                )
            index = index_of[column_config.column]
            name = column_config.name or column_config.column
            inferred = _infer_kind(
                [
                    cell.strip()
                    for cell in _column_cells(table, index)
                    if not _is_missing(cell, global_codes)
                ]
            )
            kind = column_config.kind or inferred
            codes = global_codes | frozenset(
                {code.strip() for code in column_config.missing_codes if code != ""}
            )
            values, column_diagnostics = self._parse_column(
                table, index, name, kind, codes, column_config, config
            )
            diagnostics.extend(column_diagnostics)
            columns[name] = values
            try:
                variable = Variable(
                    name=name,
                    kind=kind,
                    role=column_config.role,
                    unit=column_config.unit,
                    depends_on=column_config.depends_on,
                    uncertainty=column_config.uncertainty,
                    quality=column_config.quality,
                    description=column_config.description,
                )
            except ValueError as exc:
                raise DatasetImportError(
                    f"column {column_config.column!r} does not describe a valid variable: {exc}"
                ) from exc
            variables.append(variable)

        if any(diagnostic.level == "error" for diagnostic in diagnostics):
            raise DatasetImportError(
                "the source cannot be imported under this configuration", diagnostics
            )

        coordinates = tuple(
            (column_config.name or column_config.column)
            for column_config in config.columns
            if column_config.role == "coordinate"
        )
        try:
            observation_set = ObservationSet(
                coordinates=coordinates, variables=tuple(variables), columns=columns
            )
            provenance = Provenance(
                source_kind="file",
                imported_at=config.imported_at or _now(),
                dataset_version=config.dataset_version,
                adapter=AdapterRef(id=self.id, version=self.version),
                original_filename=Path(source).name,
                source_sha256=table.sha256,
                preprocessing=(
                    PreprocessStep(
                        operation="parse_csv",
                        version=self.version,
                        params={"delimiter": table.delimiter, "has_header": table.has_header},
                    ),
                ),
                notes=config.notes,
                license=config.license,
            )
            return build_dataset(
                config.name,
                observation_set,
                provenance,
                description=config.description,
                labels=config.labels,
            )
        except (ObservationError, ValueError) as exc:
            raise DatasetImportError(
                f"the configuration does not produce a valid dataset: {exc}"
            ) from exc

    def _parse_column(
        self,
        table: _Table,
        index: int,
        name: str,
        kind: VariableKind,
        codes: frozenset[str],
        column_config: ColumnConfig,
        config: CsvImportConfig,
    ) -> tuple[list[Any], list[Diagnostic]]:
        diagnostics: list[Diagnostic] = []
        values: list[Any] = []
        for row_index, row in enumerate(table.rows):
            cell = row[index] if index < len(row) else ""
            if _is_missing(cell, codes):
                values.append(None)
                continue
            text = cell.strip()
            if kind == "float":
                parsed = _parse_float(text)
                if parsed is None:
                    values.append(None)
                    diagnostics.append(_cell("invalid", name, row_index, text, config.invalid_policy))
                elif not math.isfinite(parsed):
                    values.append(None)
                    diagnostics.append(
                        _cell("non_finite", name, row_index, text, config.non_finite_policy)
                    )
                else:
                    values.append(parsed)
            elif kind == "int":
                if _is_int(text):
                    values.append(int(text))
                else:
                    values.append(None)
                    diagnostics.append(_cell("invalid", name, row_index, text, config.invalid_policy))
            elif kind == "bool":
                parsed_bool = _parse_bool(text)
                if parsed_bool is None:
                    values.append(None)
                    diagnostics.append(_cell("invalid", name, row_index, text, config.invalid_policy))
                else:
                    values.append(parsed_bool)
            elif kind == "datetime":
                parsed_dt = _parse_datetime(text, column_config.datetime_format)
                if parsed_dt is None:
                    values.append(None)
                    diagnostics.append(_cell("invalid", name, row_index, text, config.invalid_policy))
                else:
                    values.append(parsed_dt.isoformat())
            else:  # categorical
                values.append(text)
        return values, diagnostics


def _cell(reason: str, name: str, row_index: int, text: str, policy: str) -> Diagnostic:
    level = "warning" if policy == "missing" else "error"
    suffix = " (imported as missing by policy)" if policy == "missing" else ""
    return Diagnostic(
        level=level,
        code=reason,
        message=f"column {name!r} row {row_index} is {reason}: {text!r}{suffix}",
    )


CSV_ADAPTER = CsvAdapter()
register_adapter(CSV_ADAPTER)


def import_csv(source: str | Path, config: CsvImportConfig, store: Any, *, dry_run: bool = False):
    """Parse ``source`` and persist the dataset, returning its :class:`DatasetRef`.

    A ``dry_run`` validates the source and configuration and returns the computed
    reference **without** persisting anything. This is the single import path used
    by the CLI and the bridge, so persistence is never duplicated.
    """
    dataset = CSV_ADAPTER.read(source, config)
    if dry_run:
        return dataset.ref()
    store.save(dataset)
    return store.ref(dataset.dataset_id)
