"""Unit tests for M12C-B structured independence and leakage checks."""

from __future__ import annotations

import pytest

from drw.observations import build_dataset
from drw.schema.model import ModelRef
from drw.schema.observation import (
    Dataset,
    DatasetFile,
    MappingPair,
    ObservationMapping,
    ObservationSet,
    Provenance,
    Variable,
)
from drw.schema.validation import CoordinateWindow, IndependenceSpec
from drw.validation.independence import (
    check_dataset_identity,
    check_group_key,
    check_measurement_process,
    check_time_window,
    coordinate_range_comparisons,
    evaluate_independence,
    unseen_groups,
)

pytestmark = pytest.mark.unit

FILE_SHA = "f" * 64
SOURCE_SHA = "e" * 64


def make_dataset(
    name: str,
    specs: list[tuple[str, str, str, str | None, tuple[str, ...]]],
    columns: dict[str, list[object]],
    coordinates: tuple[str, ...] = (),
    *,
    files: tuple[DatasetFile, ...] = (),
    **prov,
) -> Dataset:
    provenance = Provenance(
        source_kind=prov.pop("source_kind", "synthetic"),
        imported_at=prov.pop("imported_at", "2026-01-01T00:00:00+00:00"),
        dataset_version=prov.pop("dataset_version", "1.0.0"),
        **prov,
    )
    observation_set = ObservationSet(
        coordinates=coordinates,
        variables=tuple(
            Variable(name=n, kind=k, role=r, unit=u, depends_on=d) for (n, k, r, u, d) in specs
        ),
        columns=columns,
    )
    return build_dataset(name, observation_set, provenance, files=files)


TIMESERIES = [
    ("t", "float", "coordinate", None, ()),
    ("y", "float", "measurement", "K", ("t",)),
]


def timeseries(values: list[float], *, times: list[float] | None = None, **prov) -> Dataset:
    return make_dataset(
        "ds",
        TIMESERIES,
        {"t": times if times is not None else list(range(len(values))), "y": values},
        coordinates=("t",),
        **prov,
    )


def grouped(sites: list[str], *, values: list[float] | None = None, **prov) -> Dataset:
    values = values if values is not None else [float(index) for index in range(len(sites))]
    return make_dataset(
        "ds",
        [*TIMESERIES, ("site", "categorical", "metadata", None, ())],
        {"t": list(range(len(sites))), "y": values, "site": sites},
        coordinates=("t",),
        **prov,
    )


def mapping_for(dataset: Dataset) -> ObservationMapping:
    return ObservationMapping(
        dataset=dataset.ref(),
        model_ref=ModelRef(model_id="model"),
        pairs=(MappingPair(observation="y", output="y", coordinates=("t",)),),
    )


def spec_for(dataset: Dataset, **over) -> IndependenceSpec:
    payload = {"vs_dataset": dataset.ref()}
    payload.update(over)
    return IndependenceSpec(**payload)


# ---------------------------------------------------------------------------
# Dataset identity / leakage.
# ---------------------------------------------------------------------------


def test_same_dataset_is_violated():
    dataset = timeseries([1.0, 2.0, 3.0])
    check = check_dataset_identity(dataset, dataset)
    assert check.state == "violated"
    assert "calibration dataset" in check.message


def test_same_science_different_provenance_is_violated():
    calibration = timeseries([1.0, 2.0, 3.0], source_id="a")
    validation = timeseries([1.0, 2.0, 3.0], source_id="b")
    assert calibration.content_hash != validation.content_hash
    check = check_dataset_identity(calibration, validation)
    assert check.state == "violated"
    assert "science_hash" in check.message


def test_shared_source_file_is_violated():
    entry = DatasetFile(name="obs.csv", sha256=FILE_SHA, size_bytes=10)
    calibration = timeseries([1.0, 2.0, 3.0], files=(entry,))
    validation = timeseries([4.0, 5.0, 6.0], files=(entry,))
    check = check_dataset_identity(calibration, validation)
    assert check.state == "violated"
    assert "source file" in check.message


def test_shared_source_sha256_is_violated():
    calibration = timeseries([1.0, 2.0, 3.0], source_sha256=SOURCE_SHA)
    validation = timeseries([4.0, 5.0, 6.0], source_sha256=SOURCE_SHA)
    check = check_dataset_identity(calibration, validation)
    assert check.state == "violated"
    assert "source_sha256" in check.message


def test_distinct_datasets_are_verified():
    calibration = timeseries([1.0, 2.0, 3.0])
    validation = timeseries([4.0, 5.0, 6.0])
    check = check_dataset_identity(calibration, validation)
    assert check.state == "verified"


# ---------------------------------------------------------------------------
# Time windows.
# ---------------------------------------------------------------------------


def test_overlapping_time_windows_violated():
    calibration = timeseries([1.0, 2.0, 3.0], times=[0.0, 1.0, 2.0])
    validation = timeseries([4.0, 5.0, 6.0], times=[1.0, 2.0, 3.0])
    check = check_time_window(calibration, validation, mapping_for(validation))
    assert check.state == "violated"


def test_disjoint_time_windows_verified():
    calibration = timeseries([1.0, 2.0, 3.0], times=[0.0, 1.0, 2.0])
    validation = timeseries([4.0, 5.0, 6.0], times=[10.0, 11.0, 12.0])
    check = check_time_window(calibration, validation, mapping_for(validation))
    assert check.state == "verified"


def test_time_window_unverifiable_without_comparable_coordinate():
    calibration = make_dataset(
        "a", [("x", "float", "coordinate", None, ())], {"x": [0.0]}, coordinates=("x",)
    )
    validation = make_dataset(
        "b", [("x", "float", "coordinate", None, ())], {"x": [1.0]}, coordinates=("x",)
    )
    mapping = ObservationMapping(
        dataset=validation.ref(),
        model_ref=ModelRef(model_id="model"),
        pairs=(MappingPair(observation="x", output="x", coordinates=("t",)),),
    )
    check = check_time_window(calibration, validation, mapping)
    assert check.state == "unverifiable"


def test_explicit_window_override_is_used():
    calibration = timeseries([1.0, 2.0, 3.0], times=[0.0, 1.0, 2.0])
    validation = timeseries([4.0, 5.0, 6.0], times=[1.0, 2.0, 3.0])
    window = CoordinateWindow(coordinate="t", lower=10.0, upper=20.0)
    check = check_time_window(calibration, validation, mapping_for(validation), (window,))
    assert check.state == "verified"


# ---------------------------------------------------------------------------
# Group keys.
# ---------------------------------------------------------------------------


def test_shared_group_key_violated():
    calibration = grouped(["A", "B"])
    validation = grouped(["A", "C"])
    check = check_group_key(calibration, validation, "site")
    assert check.state == "violated"
    assert "A" in check.message


def test_disjoint_group_key_verified():
    calibration = grouped(["A", "B"])
    validation = grouped(["C", "D"])
    check = check_group_key(calibration, validation, "site")
    assert check.state == "verified"


def test_missing_group_key_unverifiable():
    calibration = timeseries([1.0, 2.0])
    validation = timeseries([3.0, 4.0])
    check = check_group_key(calibration, validation, "site")
    assert check.state == "unverifiable"


# ---------------------------------------------------------------------------
# Declared-only dimensions.
# ---------------------------------------------------------------------------


def test_measurement_process_is_always_declared():
    calibration = timeseries([1.0, 2.0, 3.0], source_uri="a")
    validation = timeseries([4.0, 5.0, 6.0], source_uri="b")
    check = check_measurement_process(calibration, validation)
    assert check.state == "declared"
    assert "supporting evidence" in check.message


# ---------------------------------------------------------------------------
# Roll-up.
# ---------------------------------------------------------------------------


def test_rollup_verified_when_all_claimed_verified():
    calibration = timeseries([1.0, 2.0, 3.0])
    validation = timeseries([4.0, 5.0, 6.0])
    report = evaluate_independence(
        spec_for(calibration, claimed_dimensions=("dataset",)),
        calibration,
        validation,
        mapping_for(validation),
    )
    assert report.status == "verified"


def test_rollup_partially_verified_with_declared_dimension():
    calibration = timeseries([1.0, 2.0, 3.0])
    validation = timeseries([4.0, 5.0, 6.0])
    report = evaluate_independence(
        spec_for(calibration, claimed_dimensions=("dataset", "measurement_process")),
        calibration,
        validation,
        mapping_for(validation),
    )
    assert report.status == "partially_verified"


def test_rollup_declared_only_without_claims():
    calibration = timeseries([1.0, 2.0, 3.0])
    validation = timeseries([4.0, 5.0, 6.0])
    report = evaluate_independence(
        spec_for(calibration), calibration, validation, mapping_for(validation)
    )
    assert report.status == "declared_only"


def test_rollup_violated_even_when_dataset_dimension_not_claimed():
    dataset = timeseries([1.0, 2.0, 3.0])
    report = evaluate_independence(
        spec_for(dataset), dataset, dataset, mapping_for(dataset)
    )
    assert report.status == "violated"


def test_rollup_unverifiable_claim_is_declared_only():
    calibration = grouped(["A", "B"])
    validation = grouped(["C", "D"])
    report = evaluate_independence(
        spec_for(calibration, claimed_dimensions=("entity",)),
        calibration,
        validation,
        mapping_for(validation),
    )
    assert report.status == "declared_only"
    assert any(check.state == "unverifiable" for check in report.checks)


def test_rollup_group_key_violation():
    calibration = grouped(["A", "B"])
    validation = grouped(["A", "C"])
    report = evaluate_independence(
        spec_for(calibration, claimed_dimensions=("entity",), group_key="site"),
        calibration,
        validation,
        mapping_for(validation),
    )
    assert report.status == "violated"


# ---------------------------------------------------------------------------
# Context.
# ---------------------------------------------------------------------------


def test_context_within_range():
    calibration = timeseries([1.0, 2.0, 3.0], times=[0.0, 1.0, 2.0])
    validation = timeseries([4.0, 5.0], times=[0.5, 1.5])
    comparisons = coordinate_range_comparisons(calibration, validation, mapping_for(validation))
    assert comparisons[0].classification == "within_range"


def test_context_outside_range():
    calibration = timeseries([1.0, 2.0, 3.0], times=[0.0, 1.0, 2.0])
    validation = timeseries([4.0, 5.0], times=[10.0, 11.0])
    comparisons = coordinate_range_comparisons(calibration, validation, mapping_for(validation))
    assert comparisons[0].classification == "outside_range"


def test_unseen_groups():
    calibration = grouped(["A", "B"])
    validation = grouped(["B", "C", "D"])
    assert unseen_groups(calibration, validation, "site") == ("C", "D")
    assert unseen_groups(calibration, validation, None) == ()
