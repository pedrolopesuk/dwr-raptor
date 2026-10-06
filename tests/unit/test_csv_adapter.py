"""Unit tests for the M11C CSV observation adapter."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from drw.adapters import adapter_for, get_adapter, list_adapters
from drw.adapters.csv_adapter import (
    CSV_ADAPTER,
    CSV_ADAPTER_ID,
    CSV_ADAPTER_VERSION,
    ColumnConfig,
    CsvAdapter,
    CsvImportConfig,
    DatasetImportError,
    InspectionError,
    import_csv,
)
from drw.dataset_store import DatasetStore
from drw.schema.observation import QualitySpec, UncertaintySpec

pytestmark = pytest.mark.unit


def write(tmp_path, name: str, text: str):
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return path


def col(column, role, **kwargs):
    return ColumnConfig(column=column, role=role, **kwargs)


# ---------------------------------------------------------------------------
# Registry.
# ---------------------------------------------------------------------------


def test_csv_adapter_is_registered():
    assert CSV_ADAPTER_ID == "csv"
    assert CSV_ADAPTER_VERSION == "1.0.0"
    assert get_adapter("csv") is CSV_ADAPTER
    assert {"id": "csv", "version": "1.0.0"} in list_adapters()
    assert adapter_for("something.csv") is CSV_ADAPTER
    assert adapter_for("something.parquet") is None


def test_can_handle_is_suffix_based():
    adapter = CsvAdapter()
    assert adapter.can_handle("a.csv") and adapter.can_handle("A.CSV")
    assert not adapter.can_handle("a.txt")


# ---------------------------------------------------------------------------
# Inspection (advisory only).
# ---------------------------------------------------------------------------


def test_inspection_reports_columns_rows_and_preview(tmp_path):
    path = write(tmp_path, "a.csv", "time,flux,flux_err\n1,10.0,0.1\n2,10.5,0.1\n")
    inspection = CSV_ADAPTER.inspect(path)
    assert inspection.filename == "a.csv"
    assert inspection.delimiter == ","
    assert inspection.has_header is True
    assert inspection.row_count == 2
    assert [c.column for c in inspection.columns] == ["time", "flux", "flux_err"]
    assert inspection.preview[0] == {"time": "1", "flux": "10.0", "flux_err": "0.1"}
    assert inspection.columns[0].kind == "int"
    assert inspection.columns[1].kind == "float"


def test_inspection_detects_primitive_kinds(tmp_path):
    path = write(
        tmp_path,
        "kinds.csv",
        "i,f,b,c,dt\n1,1.5,true,red,2026-01-01T00:00:00Z\n2,2.5,false,green,2026-01-02T00:00:00Z\n",
    )
    kinds = {c.column: c.kind for c in CSV_ADAPTER.inspect(path).columns}
    assert kinds == {"i": "int", "f": "float", "b": "bool", "c": "categorical", "dt": "datetime"}


def test_inspection_counts_missing_and_non_finite(tmp_path):
    path = write(
        tmp_path,
        "m.csv",
        "time,value\n1,10\n2,\n3,inf\n4,-999\n5,12\n",
    )
    inspection = CSV_ADAPTER.inspect(path, missing_codes=("-999",))
    value = next(c for c in inspection.columns if c.column == "value")
    assert value.missing_count == 2  # empty + configured sentinel
    assert value.non_finite_count == 1


def test_inspection_suggests_roles_but_they_are_advisory(tmp_path):
    path = write(
        tmp_path,
        "s.csv",
        "time,flux,flux_err,flag\n0,1.0,0.1,good\n1,1.1,0.1,bad\n",
    )
    columns = {c.column: c for c in CSV_ADAPTER.inspect(path).columns}
    assert columns["time"].suggested_role == "coordinate"
    assert columns["flux"].suggested_role == "measurement"
    assert columns["flux_err"].suggested_role == "uncertainty"
    assert columns["flux_err"].suggested_uncertainty_for == "flux"
    assert columns["flag"].suggested_role == "quality"


def test_inspection_reports_ragged_rows(tmp_path):
    path = write(tmp_path, "r.csv", "a,b\n1,2\n3\n4,5\n")
    inspection = CSV_ADAPTER.inspect(path)
    assert any(d.code == "ragged_rows" for d in inspection.diagnostics)


def test_inspection_empty_file(tmp_path):
    path = write(tmp_path, "empty.csv", "")
    inspection = CSV_ADAPTER.inspect(path)
    assert inspection.row_count == 0
    assert inspection.columns == []


def test_inspection_header_only(tmp_path):
    path = write(tmp_path, "h.csv", "a,b\n")
    inspection = CSV_ADAPTER.inspect(path)
    assert inspection.row_count == 0
    assert [c.column for c in inspection.columns] == ["a", "b"]


def test_inspection_missing_file_raises():
    with pytest.raises(InspectionError):
        CSV_ADAPTER.inspect("does-not-exist.csv")


def test_inspection_sniffs_delimiter(tmp_path):
    path = write(tmp_path, "semi.csv", "a;b\n1;2\n")
    assert CSV_ADAPTER.inspect(path).delimiter == ";"


# ---------------------------------------------------------------------------
# Import: explicit configuration only.
# ---------------------------------------------------------------------------


def _timeseries_config(**overrides):
    columns = (
        col("time", "coordinate", unit="s"),
        col("value", "measurement", unit="K", depends_on=("time",)),
    )
    payload = {
        "name": "series",
        "columns": columns,
        "imported_at": "2026-01-01T00:00:00+00:00",
    }
    payload.update(overrides)
    return CsvImportConfig(**payload)


def test_import_timeseries(tmp_path):
    path = write(tmp_path, "t.csv", "time,value\n0,10.0\n1,11.0\n2,12.0\n")
    dataset = CSV_ADAPTER.read(path, _timeseries_config())
    assert dataset.observation_set.row_count == 3
    assert dataset.observation_set.coordinates == ("time",)
    assert dataset.observation_set.variables[1].depends_on == ("time",)


def test_import_scalar_observations(tmp_path):
    path = write(tmp_path, "scalars.csv", "mass,length\n1.0,2.0\n1.5,2.5\n")
    config = CsvImportConfig(
        name="scalars",
        columns=(col("mass", "measurement", unit="kg"), col("length", "measurement", unit="m")),
    )
    dataset = CSV_ADAPTER.read(path, config)
    assert dataset.observation_set.coordinates == ()
    assert len(dataset.observation_set.variables) == 2


def test_import_repeated_coordinates(tmp_path):
    path = write(tmp_path, "rep.csv", "time,replicate,value\n1,1,5\n1,2,6\n2,1,7\n")
    config = CsvImportConfig(
        name="repeated",
        columns=(
            col("time", "coordinate", unit="s"),
            col("replicate", "coordinate"),
            col("value", "measurement", unit="count", depends_on=("time", "replicate")),
        ),
    )
    dataset = CSV_ADAPTER.read(path, config)
    assert dataset.observation_set.row_count == 3
    # Duplicate coordinate tuples are preserved.
    rows = dataset.observation_set.rows()
    assert rows[0]["time"] == rows[1]["time"] == 1


def test_import_multiple_coordinates(tmp_path):
    path = write(tmp_path, "m.csv", "time,wavelength,value\n0,5e-7,1\n0,6e-7,2\n")
    config = CsvImportConfig(
        name="multi",
        columns=(
            col("time", "coordinate", unit="s"),
            col("wavelength", "coordinate", unit="m"),
            col("value", "measurement", unit="Jy", depends_on=("time", "wavelength")),
        ),
    )
    dataset = CSV_ADAPTER.read(path, config)
    assert dataset.observation_set.coordinates == ("time", "wavelength")


def test_import_units_are_explicit_and_never_inferred(tmp_path):
    path = write(tmp_path, "u.csv", "value\n1.0\n2.0\n")
    inferred_unit = CSV_ADAPTER.read(path, CsvImportConfig(name="x", columns=(col("value", "measurement"),)))
    assert inferred_unit.observation_set.variables[0].unit is None
    explicit = CSV_ADAPTER.read(
        path, CsvImportConfig(name="x", columns=(col("value", "measurement", unit="K"),))
    )
    assert explicit.observation_set.variables[0].unit == "K"


def test_import_does_not_infer_uncertainty_or_roles(tmp_path):
    path = write(tmp_path, "a.csv", "flux,flux_err\n1.0,0.1\n1.1,0.1\n")
    config = CsvImportConfig(
        name="noinfer",
        columns=(col("flux", "measurement", unit="Jy"), col("flux_err", "measurement", unit="Jy")),
    )
    dataset = CSV_ADAPTER.read(path, config)
    assert all(v.uncertainty is None for v in dataset.observation_set.variables)


def test_import_uncertainty_companion(tmp_path):
    path = write(tmp_path, "e.csv", "time,flux,flux_err\n0,1.0,0.1\n1,1.1,0.2\n")
    config = CsvImportConfig(
        name="err",
        columns=(
            col("time", "coordinate", unit="s"),
            col(
                "flux", "measurement", unit="Jy", depends_on=("time",),
                uncertainty=UncertaintySpec(type="std", column="flux_err"),
            ),
            col("flux_err", "uncertainty", unit="Jy"),
        ),
    )
    dataset = CSV_ADAPTER.read(path, config)
    flux = next(v for v in dataset.observation_set.variables if v.name == "flux")
    assert flux.uncertainty.type == "std" and flux.uncertainty.column == "flux_err"


def test_import_asymmetric_uncertainty(tmp_path):
    path = write(tmp_path, "asym.csv", "x,y,y_lo,y_hi\n0,1.0,0.9,1.2\n1,2.0,1.8,2.3\n")
    config = CsvImportConfig(
        name="asym",
        columns=(
            col("x", "coordinate", unit="m"),
            col(
                "y", "measurement", unit="K", depends_on=("x",),
                uncertainty=UncertaintySpec(
                    type="asymmetric", lower_column="y_lo", upper_column="y_hi"
                ),
            ),
            col("y_lo", "uncertainty", unit="K"),
            col("y_hi", "uncertainty", unit="K"),
        ),
    )
    dataset = CSV_ADAPTER.read(path, config)
    y = next(v for v in dataset.observation_set.variables if v.name == "y")
    assert y.uncertainty.type == "asymmetric"


def test_import_quality_flags(tmp_path):
    path = write(tmp_path, "q.csv", "t,v,flag\n0,1.0,good\n1,2.0,bad\n")
    config = CsvImportConfig(
        name="quality",
        columns=(
            col("t", "coordinate", unit="s"),
            col(
                "v", "measurement", unit="K", depends_on=("t",),
                quality=QualitySpec(flag_column="flag", rejected_flags=("bad",)),
            ),
            col("flag", "quality"),
        ),
    )
    dataset = CSV_ADAPTER.read(path, config)
    assert dataset.observation_set.variables[1].quality.flag_column == "flag"


def test_import_missing_values(tmp_path):
    path = write(tmp_path, "miss.csv", "t,v\n0,1.0\n1,\n2,3.0\n")
    dataset = CSV_ADAPTER.read(
        path,
        CsvImportConfig(name="m", columns=(col("t", "coordinate", unit="s"), col("v", "measurement", unit="K", depends_on=("t",)))),
    )
    assert dataset.observation_set.columns["v"] == [1.0, None, 3.0]


def test_import_configured_missing_sentinels(tmp_path):
    path = write(tmp_path, "sent.csv", "t,v\n0,1.0\n1,-999\n2,3.0\n")
    config = CsvImportConfig(
        name="sent",
        missing_codes=("-999",),
        columns=(col("t", "coordinate", unit="s"), col("v", "measurement", unit="K", depends_on=("t",))),
    )
    dataset = CSV_ADAPTER.read(path, config)
    assert dataset.observation_set.columns["v"] == [1.0, None, 3.0]


def test_import_datetime_is_normalised(tmp_path):
    path = write(tmp_path, "dt.csv", "when,v\n2026-01-01T00:00:00Z,1.0\n2026-01-02T00:00:00Z,2.0\n")
    config = CsvImportConfig(
        name="dt",
        columns=(col("when", "coordinate"), col("v", "measurement", unit="K", depends_on=("when",))),
    )
    dataset = CSV_ADAPTER.read(path, config)
    assert dataset.observation_set.columns["when"][0] == "2026-01-01T00:00:00+00:00"


def test_import_non_finite_policy(tmp_path):
    path = write(tmp_path, "nf.csv", "v\n1.0\ninf\n3.0\n")
    with pytest.raises(DatasetImportError) as excinfo:
        CSV_ADAPTER.read(path, CsvImportConfig(name="nf", columns=(col("v", "measurement", unit="K"),)))
    assert any(d.code == "non_finite" for d in excinfo.value.diagnostics)

    tolerant = CSV_ADAPTER.read(
        path,
        CsvImportConfig(
            name="nf", non_finite_policy="missing",
            columns=(col("v", "measurement", unit="K"),),
        ),
    )
    assert tolerant.observation_set.columns["v"] == [1.0, None, 3.0]


def test_import_invalid_value_policy(tmp_path):
    path = write(tmp_path, "inv.csv", "v\n1.0\nabc\n3.0\n")
    with pytest.raises(DatasetImportError):
        CSV_ADAPTER.read(
            path,
            CsvImportConfig(name="i", columns=(col("v", "measurement", kind="float", unit="K"),)),
        )
    tolerant = CSV_ADAPTER.read(
        path,
        CsvImportConfig(
            name="i", invalid_policy="missing",
            columns=(col("v", "measurement", kind="float", unit="K"),),
        ),
    )
    assert tolerant.observation_set.columns["v"] == [1.0, None, 3.0]


# ---------------------------------------------------------------------------
# Invalid configurations.
# ---------------------------------------------------------------------------


def test_role_is_required_and_never_inferred():
    with pytest.raises(ValidationError):
        ColumnConfig(column="value")


def test_unknown_column_is_rejected(tmp_path):
    path = write(tmp_path, "u.csv", "a\n1\n")
    with pytest.raises(DatasetImportError, match="unknown column"):
        CSV_ADAPTER.read(path, CsvImportConfig(name="x", columns=(col("missing", "measurement"),)))


def test_incompatible_kind_is_rejected(tmp_path):
    path = write(tmp_path, "k.csv", "v\nabc\n")
    with pytest.raises(DatasetImportError):
        CSV_ADAPTER.read(
            path,
            CsvImportConfig(name="k", columns=(col("v", "measurement", kind="float", unit="K"),)),
        )


def test_invalid_unit_is_rejected(tmp_path):
    path = write(tmp_path, "unit.csv", "v\n1.0\n")
    with pytest.raises(DatasetImportError):
        CSV_ADAPTER.read(
            path,
            CsvImportConfig(name="u", columns=(col("v", "measurement", unit=""),)),
        )


def test_uncertainty_companion_must_be_declared(tmp_path):
    path = write(tmp_path, "e.csv", "flux\n1.0\n")
    with pytest.raises(DatasetImportError):
        CSV_ADAPTER.read(
            path,
            CsvImportConfig(
                name="e",
                columns=(
                    col(
                        "flux", "measurement", unit="Jy",
                        uncertainty=UncertaintySpec(type="std", column="missing_err"),
                    ),
                ),
            ),
        )


def test_ragged_rows_block_import(tmp_path):
    path = write(tmp_path, "r.csv", "a,b\n1,2\n3\n")
    with pytest.raises(DatasetImportError, match="column count"):
        CSV_ADAPTER.read(
            path,
            CsvImportConfig(name="r", columns=(col("a", "measurement"), col("b", "measurement"))),
        )


def test_empty_source_cannot_be_imported(tmp_path):
    path = write(tmp_path, "empty.csv", "")
    with pytest.raises(DatasetImportError):
        CSV_ADAPTER.read(path, CsvImportConfig(name="e", columns=(col("a", "measurement"),)))


def test_header_only_source_imports_zero_rows(tmp_path):
    path = write(tmp_path, "h.csv", "a,b\n")
    dataset = CSV_ADAPTER.read(
        path,
        CsvImportConfig(name="h", columns=(col("a", "measurement", unit="K"), col("b", "measurement", unit="K"))),
    )
    assert dataset.observation_set.row_count == 0


# ---------------------------------------------------------------------------
# Five domain fixtures (domain-neutral from the core's perspective).
# ---------------------------------------------------------------------------


def test_astrophysics_lightcurve_fixture(fixtures_dir):
    path = fixtures_dir / "csv" / "astrophysics_lightcurve.csv"
    config = CsvImportConfig(
        name="lightcurve",
        imported_at="2026-01-01T00:00:00+00:00",
        columns=(
            col("time", "coordinate"),
            col(
                "flux", "measurement", unit="Jy", depends_on=("time",),
                uncertainty=UncertaintySpec(type="std", column="flux_err"),
            ),
            col("flux_err", "uncertainty", unit="Jy"),
        ),
    )
    dataset = CSV_ADAPTER.read(path, config)
    assert dataset.observation_set.row_count == 5


def test_space_trajectory_fixture(fixtures_dir):
    path = fixtures_dir / "csv" / "space_trajectory.csv"
    config = CsvImportConfig(
        name="trajectory",
        imported_at="2026-01-01T00:00:00+00:00",
        columns=(
            col("time", "coordinate", unit="s"),
            col("x", "measurement", unit="km", depends_on=("time",)),
            col("y", "measurement", unit="km", depends_on=("time",)),
            col("z", "measurement", unit="km", depends_on=("time",)),
            col("vx", "measurement", unit="km/s", depends_on=("time",)),
            col("vy", "measurement", unit="km/s", depends_on=("time",)),
            col("vz", "measurement", unit="km/s", depends_on=("time",)),
        ),
    )
    assert CSV_ADAPTER.read(path, config).observation_set.row_count == 4


def test_physics_response_fixture(fixtures_dir):
    path = fixtures_dir / "csv" / "physics_response.csv"
    config = CsvImportConfig(
        name="response",
        imported_at="2026-01-01T00:00:00+00:00",
        columns=(
            col("x", "coordinate", unit="m"),
            col(
                "y", "measurement", unit="K", depends_on=("x",),
                uncertainty=UncertaintySpec(type="asymmetric", lower_column="y_lo", upper_column="y_hi"),
            ),
            col("y_lo", "uncertainty", unit="K"),
            col("y_hi", "uncertainty", unit="K"),
        ),
    )
    assert CSV_ADAPTER.read(path, config).observation_set.row_count == 4


def test_biology_replicates_fixture(fixtures_dir):
    path = fixtures_dir / "csv" / "biology_replicates.csv"
    config = CsvImportConfig(
        name="replicates",
        imported_at="2026-01-01T00:00:00+00:00",
        columns=(
            col("time", "coordinate", unit="h"),
            col("replicate", "coordinate"),
            col(
                "concentration", "measurement", unit="mol/L", depends_on=("time", "replicate"),
                uncertainty=UncertaintySpec(type="stderr", column="concentration_stderr"),
            ),
            col("concentration_stderr", "uncertainty", unit="mol/L"),
        ),
    )
    assert CSV_ADAPTER.read(path, config).observation_set.row_count == 6


def test_climate_points_fixture(fixtures_dir):
    path = fixtures_dir / "csv" / "climate_points.csv"
    config = CsvImportConfig(
        name="climate",
        imported_at="2026-01-01T00:00:00+00:00",
        columns=(
            col("timestamp", "coordinate"),
            col("latitude", "coordinate", unit="rad"),
            col("longitude", "coordinate", unit="rad"),
            col("altitude", "coordinate", unit="m"),
            col(
                "temperature", "measurement", unit="K",
                depends_on=("timestamp", "latitude", "longitude", "altitude"),
            ),
        ),
    )
    dataset = CSV_ADAPTER.read(path, config)
    assert dataset.observation_set.row_count == 3
    assert dataset.observation_set.coordinates == ("timestamp", "latitude", "longitude", "altitude")


# ---------------------------------------------------------------------------
# Integrity: import -> DatasetStore -> verify.
# ---------------------------------------------------------------------------


@pytest.fixture
def store(tmp_path):
    return DatasetStore(tmp_path / "workspace")


def test_import_persists_and_resolves(store, tmp_path):
    path = write(tmp_path, "g.csv", "time,value\n0,1.0\n1,2.0\n")
    config = _timeseries_config(name="persisted")
    ref = import_csv(path, config, store, dry_run=False)
    assert store.exists(ref.dataset_id)
    assert store.resolve(ref.content_hash) == ref
    assert store.verify(ref.dataset_id).ok is True
    assert store.load(ref.dataset_id).observation_set.row_count == 2


def test_dry_run_does_not_persist(store, tmp_path):
    path = write(tmp_path, "d.csv", "time,value\n0,1.0\n")
    ref = import_csv(path, _timeseries_config(name="dry"), store, dry_run=True)
    assert ref.dataset_id.startswith("ds-")
    assert store.list() == []


def test_identical_content_has_identical_identity(tmp_path):
    path = write(tmp_path, "same.csv", "time,value\n0,1.0\n1,2.0\n")
    config = _timeseries_config(name="same")
    first = CSV_ADAPTER.read(path, config)
    second = CSV_ADAPTER.read(path, config)
    assert first.content_hash == second.content_hash
    assert first.dataset_id == second.dataset_id


def test_one_changed_value_changes_identity(tmp_path):
    path_a = write(tmp_path, "a.csv", "time,value\n0,300.0\n1,301.0\n")
    path_b = write(tmp_path, "b.csv", "time,value\n0,301.0\n1,301.0\n")
    config = _timeseries_config(name="changed")
    dataset_a = CSV_ADAPTER.read(path_a, config)
    dataset_b = CSV_ADAPTER.read(path_b, config)
    assert dataset_a.content_hash != dataset_b.content_hash
    assert dataset_a.dataset_id != dataset_b.dataset_id


def test_failed_import_leaves_no_partial_dataset(store, tmp_path):
    path = write(tmp_path, "bad.csv", "a\n1\n")
    config = CsvImportConfig(name="bad", columns=(col("missing", "measurement"),))
    with pytest.raises(DatasetImportError):
        import_csv(path, config, store)
    assert store.list() == []
