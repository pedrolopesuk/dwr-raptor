"""Structured independence and leakage checks for validation datasets (M12C-B).

Independence is **not a boolean**. Each declared dimension is checked
mechanically where possible and otherwise recorded as ``declared`` (asserted by
the user, recorded but never upgraded) or ``unverifiable`` (claimed but not
checkable). DRW never upgrades ``declared`` to ``verified``.

Mechanical checks: dataset identity / ``science_hash`` / source-file hashes,
coordinate/time-window disjointness and group-key disjointness. Declared-only:
measurement process and experiment lineage (supporting evidence, never proof).
"""

from __future__ import annotations

import math
from datetime import UTC, datetime

from drw.observations import science_hash
from drw.schema.observation import Dataset, ObservationMapping, Variable
from drw.schema.validation import (
    CoordinateRangeComparison,
    CoordinateWindow,
    IndependenceCheck,
    IndependenceReport,
    IndependenceSpec,
)

__all__ = [
    "check_dataset_identity",
    "check_experiment_lineage",
    "check_group_key",
    "check_measurement_process",
    "check_time_window",
    "coordinate_range_comparisons",
    "evaluate_independence",
    "unseen_groups",
]

_NUMERIC = ("float", "int")
_COORDINATE = ("float", "int", "datetime")


def _parse_iso(value: str) -> datetime:
    text = value[:-1] + "+00:00" if value.endswith("Z") else value
    return datetime.fromisoformat(text)


def _to_epoch(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, datetime):
        moment = value
    elif isinstance(value, str):
        try:
            moment = _parse_iso(value)
        except ValueError:
            return None
    else:
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    return moment.timestamp()


def _variable(dataset: Dataset, name: str) -> Variable | None:
    for variable in dataset.observation_set.variables:
        if variable.name == name:
            return variable
    return None


def _column(dataset: Dataset, name: str) -> list[object]:
    try:
        return list(dataset.observation_set.column(name))
    except KeyError:
        return []


def _coordinate_range(dataset: Dataset, name: str) -> tuple[str, float, float] | None:
    variable = _variable(dataset, name)
    if variable is None or variable.kind not in _COORDINATE:
        return None
    values = _column(dataset, name)
    if variable.kind == "datetime":
        points = [point for point in (_to_epoch(value) for value in values) if point is not None]
    else:
        points = [
            float(value)
            for value in values
            if isinstance(value, (int, float))
            and not isinstance(value, bool)
            and math.isfinite(float(value))
        ]
    if not points:
        return None
    return variable.kind, min(points), max(points)


def _group_values(dataset: Dataset, name: str) -> set[object] | None:
    variable = _variable(dataset, name)
    if variable is None:
        return None
    values: set[object] = set()
    for value in _column(dataset, name):
        if value is None:
            continue
        if isinstance(value, float) and not math.isfinite(value):
            continue
        if isinstance(value, (str, int, float, bool)):
            values.add(value)
    return values


def _box(lo: float | None, hi: float | None) -> tuple[float, float]:
    return (
        float("-inf") if lo is None else lo,
        float("inf") if hi is None else hi,
    )


def _window_bounds(window: CoordinateWindow, kind: str) -> tuple[float, float] | None:
    if kind == "datetime":
        lower = _to_epoch(window.lower) if window.lower is not None else None
        upper = _to_epoch(window.upper) if window.upper is not None else None
    else:
        lower = (
            float(window.lower)
            if isinstance(window.lower, (int, float)) and not isinstance(window.lower, bool)
            else None
        )
        upper = (
            float(window.upper)
            if isinstance(window.upper, (int, float)) and not isinstance(window.upper, bool)
            else None
        )
    if lower is None and upper is None:
        return None
    return _box(lower, upper)


def _overlaps(a: tuple[float, float], b: tuple[float, float]) -> bool:
    return not (b[1] < a[0] or b[0] > a[1])


def check_dataset_identity(calibration: Dataset, validation: Dataset) -> IndependenceCheck:
    """Same dataset / same science / shared source file ⇒ leakage (violated)."""
    if (
        validation.content_hash == calibration.content_hash
        or validation.dataset_id == calibration.dataset_id
    ):
        return IndependenceCheck(
            dimension="dataset",
            state="violated",
            message="the validation dataset is the calibration dataset (leakage)",
        )
    if science_hash(validation) == science_hash(calibration):
        return IndependenceCheck(
            dimension="dataset",
            state="violated",
            message="the validation dataset has the same science_hash as the calibration dataset "
            "(same measurements, different provenance)",
        )
    calibration_files = {item.sha256 for item in calibration.files}
    validation_files = {item.sha256 for item in validation.files}
    if calibration_files & validation_files:
        return IndependenceCheck(
            dimension="dataset",
            state="violated",
            message="the datasets share an identical source file (leakage)",
        )
    source = calibration.provenance.source_sha256
    if source is not None and source == validation.provenance.source_sha256:
        return IndependenceCheck(
            dimension="dataset",
            state="violated",
            message="the datasets share an identical source_sha256 (leakage)",
        )
    return IndependenceCheck(
        dimension="dataset",
        state="verified",
        message="distinct content_hash and science_hash",
    )


def check_time_window(
    calibration: Dataset,
    validation: Dataset,
    mapping: ObservationMapping,
    windows: tuple[CoordinateWindow, ...] = (),
) -> IndependenceCheck:
    """Disjoint mapped coordinate ranges ⇒ verified; overlapping ⇒ violated."""
    declared = {window.coordinate: window for window in windows}
    coordinates: list[str] = []
    for pair in mapping.pairs:
        for coordinate in pair.coordinates:
            if coordinate not in coordinates:
                coordinates.append(coordinate)
    for window in windows:
        if window.coordinate not in coordinates:
            coordinates.append(window.coordinate)

    comparable = 0
    overlaps: list[str] = []
    for coordinate in coordinates:
        calibration_range = _coordinate_range(calibration, coordinate)
        validation_range = _coordinate_range(validation, coordinate)
        if calibration_range is None or validation_range is None:
            continue
        kind = calibration_range[0]
        comparable += 1
        if coordinate in declared:
            bounds = _window_bounds(declared[coordinate], kind)
            calibration_box = bounds if bounds is not None else (calibration_range[1], calibration_range[2])
        else:
            calibration_box = (calibration_range[1], calibration_range[2])
        if _overlaps(calibration_box, (validation_range[1], validation_range[2])):
            overlaps.append(coordinate)

    if comparable == 0:
        return IndependenceCheck(
            dimension="time_window",
            state="unverifiable",
            message="no comparable coordinate range is available on both datasets",
        )
    if overlaps:
        return IndependenceCheck(
            dimension="time_window",
            state="violated",
            message=f"overlapping coordinate range(s): {', '.join(overlaps)}",
        )
    return IndependenceCheck(
        dimension="time_window",
        state="verified",
        message="mapped coordinate ranges are disjoint",
    )


def check_group_key(
    calibration: Dataset, validation: Dataset, group_key: str, dimension: str = "entity"
) -> IndependenceCheck:
    """Disjoint group-key value sets ⇒ verified; shared values ⇒ violated."""
    calibration_values = _group_values(calibration, group_key)
    validation_values = _group_values(validation, group_key)
    if calibration_values is None or validation_values is None:
        return IndependenceCheck(
            dimension=dimension,
            state="unverifiable",
            message=f"group key {group_key!r} is not present on both datasets",
        )
    shared = calibration_values & validation_values
    if shared:
        preview = ", ".join(sorted(str(item) for item in shared)[:5])
        return IndependenceCheck(
            dimension=dimension,
            state="violated",
            message=f"group key {group_key!r} shares values: {preview}",
        )
    return IndependenceCheck(
        dimension=dimension,
        state="verified",
        message=f"group key {group_key!r} value sets are disjoint",
    )


def check_measurement_process(calibration: Dataset, validation: Dataset) -> IndependenceCheck:
    """Compare provenance: supporting evidence only, never upgraded to verified."""
    left = calibration.provenance
    right = validation.provenance
    same = (
        left.source_kind == right.source_kind
        and left.adapter == right.adapter
        and left.source_uri == right.source_uri
    )
    message = (
        "the recorded measurement process is identical"
        if same
        else "a different measurement process is recorded (supporting evidence only)"
    )
    return IndependenceCheck(dimension="measurement_process", state="declared", message=message)


def check_experiment_lineage(calibration: Dataset, validation: Dataset) -> IndependenceCheck:
    """Compare source lineage if recorded; never mechanical proof."""
    left = calibration.provenance.source_id
    right = validation.provenance.source_id
    if left is not None and right is not None and left != right:
        message = f"different source lineage recorded ({left!r} vs {right!r})"
    elif left is not None and right is not None:
        message = f"the recorded source lineage is identical ({left!r})"
    else:
        message = "source lineage is not recorded on both datasets"
    return IndependenceCheck(dimension="experiment", state="declared", message=message)


def evaluate_independence(
    spec: IndependenceSpec,
    calibration: Dataset,
    validation: Dataset,
    mapping: ObservationMapping,
) -> IndependenceReport:
    """Run the mechanical checks and roll them up into an :class:`IndependenceReport`."""
    claimed = set(spec.claimed_dimensions)
    checks: list[IndependenceCheck] = [check_dataset_identity(calibration, validation)]

    if "time_window" in claimed or spec.coordinate_windows:
        checks.append(
            check_time_window(calibration, validation, mapping, spec.coordinate_windows)
        )
    for dimension in ("entity", "region"):
        if dimension in claimed:
            if spec.group_key is None:
                checks.append(
                    IndependenceCheck(
                        dimension=dimension,
                        state="unverifiable",
                        message="no group_key was declared",
                    )
                )
            else:
                checks.append(
                    check_group_key(calibration, validation, spec.group_key, dimension)
                )
    if "measurement_process" in claimed:
        checks.append(check_measurement_process(calibration, validation))
    if "experiment" in claimed:
        checks.append(check_experiment_lineage(calibration, validation))

    if any(check.state == "violated" for check in checks):
        status = "violated"
    elif not claimed:
        status = "declared_only"
    else:
        claimed_states = [check.state for check in checks if check.dimension in claimed]
        if claimed_states and all(state == "verified" for state in claimed_states):
            status = "verified"
        elif any(state == "verified" for state in claimed_states):
            status = "partially_verified"
        else:
            status = "declared_only"

    if status == "violated":
        note = "independence is violated: the validation dataset is not independent."
    elif status == "verified":
        note = "every claimed independence dimension was verified mechanically."
    elif status == "partially_verified":
        note = (
            "some claimed dimensions were verified mechanically; the rest are declared or "
            "unverifiable and are not proof."
        )
    else:
        note = "independence is declared by the user, not verified mechanically."
    return IndependenceReport(
        status=status, checks=tuple(checks), declaration=spec.declaration, note=note
    )


def coordinate_range_comparisons(
    calibration: Dataset, validation: Dataset, mapping: ObservationMapping
) -> tuple[CoordinateRangeComparison, ...]:
    """Compare mapped coordinate ranges (interpolation vs extrapolation context)."""
    coordinates: list[str] = []
    for pair in mapping.pairs:
        for coordinate in pair.coordinates:
            if coordinate not in coordinates:
                coordinates.append(coordinate)
    comparisons: list[CoordinateRangeComparison] = []
    for coordinate in coordinates:
        calibration_range = _coordinate_range(calibration, coordinate)
        validation_range = _coordinate_range(validation, coordinate)
        if calibration_range is None or validation_range is None:
            comparisons.append(CoordinateRangeComparison(coordinate=coordinate, kind="unknown"))
            continue
        within = (
            validation_range[1] >= calibration_range[1]
            and validation_range[2] <= calibration_range[2]
        )
        comparisons.append(
            CoordinateRangeComparison(
                coordinate=coordinate,
                kind=calibration_range[0],
                calibration_min=calibration_range[1],
                calibration_max=calibration_range[2],
                validation_min=validation_range[1],
                validation_max=validation_range[2],
                classification="within_range" if within else "outside_range",
            )
        )
    return tuple(comparisons)


def unseen_groups(calibration: Dataset, validation: Dataset, group_key: str | None) -> tuple[str, ...]:
    """Group-key values present in validation but absent from calibration."""
    if group_key is None:
        return ()
    calibration_values = _group_values(calibration, group_key)
    validation_values = _group_values(validation, group_key)
    if not calibration_values or not validation_values:
        return ()
    unseen = sorted(str(value) for value in (validation_values - calibration_values))
    return tuple(unseen)
