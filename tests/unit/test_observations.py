"""Unit tests for the M11A universal observation/data contract.

Covers the five domain examples, canonical serialization, content hashing,
dataset references/identity, variable/coordinate validation, units, uncertainty,
missing/quality semantics, time, multi-coordinate variables, mapping validation
and exact alignment.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from drw.observations import (
    ObservationError,
    ObservationIdentityError,
    align,
    assert_same_dataset,
    build_dataset,
    convert_to_output,
    make_dataset_ref,
    resolve_dataset_id,
    summarize_usability,
    validate_mapping,
)
from drw.schema.model import ModelRef, ModelSchema, OutputSpec, ParameterSpec
from drw.schema.observation import (
    AlignmentSpec,
    Dataset,
    DatasetFile,
    DatasetRef,
    MappingPair,
    ObservationMapping,
    ObservationSet,
    Provenance,
    QualitySpec,
    UncertaintySpec,
    UnitConversion,
    Variable,
    classify_value,
    compute_dataset_hash,
    short_dataset_id,
)

pytestmark = pytest.mark.unit

_NAN = float("nan")
_INF = float("inf")


# ---------------------------------------------------------------------------
# Helpers.
# ---------------------------------------------------------------------------


def provenance(**overrides) -> Provenance:
    payload = {
        "source_kind": "synthetic",
        "imported_at": "2026-01-01T00:00:00+00:00",
        "dataset_version": "1.0.0",
    }
    payload.update(overrides)
    return Provenance(**payload)


def var(name, kind, role="measurement", unit=None, depends_on=(), uncertainty=None, quality=None):
    return Variable(
        name=name,
        kind=kind,
        role=role,
        unit=unit,
        depends_on=tuple(depends_on),
        uncertainty=uncertainty,
        quality=quality,
    )


def make_dataset(name, variables, columns, coordinates=(), **overrides):
    observation_set = ObservationSet(
        coordinates=tuple(coordinates), variables=tuple(variables), columns=columns
    )
    return build_dataset(
        name,
        observation_set,
        overrides.pop("provenance", provenance()),
        **overrides,
    )


def simple_dataset() -> Dataset:
    variables = [
        var("t", "float", "coordinate", unit="s"),
        var("y", "float", "measurement", unit="K", depends_on=["t"]),
    ]
    return make_dataset("simple", variables, {"t": [0.0, 1.0, 2.0], "y": [10.0, 11.0, 12.0]}, ["t"])


def demo_schema(output_name="temperature", output_unit="K") -> ModelSchema:
    return ModelSchema(
        model_id="demo",
        parameters=(ParameterSpec(name="k", type="float", nominal=1.0, lower=0.0, upper=2.0),),
        outputs=(OutputSpec(name=output_name, kind="scalar", unit=output_unit),),
    )


# ---------------------------------------------------------------------------
# 1. Five domain examples.
# ---------------------------------------------------------------------------


def test_astrophysics_light_curve():
    variables = [
        var("time_utc", "datetime", "coordinate"),
        var(
            "flux", "float", "measurement", unit="Jy", depends_on=["time_utc"],
            uncertainty=UncertaintySpec(type="std", column="flux_err"),
        ),
        var("flux_err", "float", "uncertainty", unit="Jy"),
    ]
    ds = make_dataset(
        "light curve",
        variables,
        {
            "time_utc": ["2026-01-01T00:00:00+00:00", "2026-01-01T00:01:00+00:00"],
            "flux": [1.2, 1.3],
            "flux_err": [0.1, 0.1],
        },
        ["time_utc"],
    )
    assert ds.dataset_id.startswith("ds-")
    assert ds.observation_set.row_count == 2
    assert ds.observation_set.variables[1].uncertainty.type == "std"


def test_space_trajectory():
    variables = [var("time", "float", "coordinate", unit="s")]
    for axis in ("x", "y", "z"):
        variables.append(
            var(
                f"position_{axis}", "float", "measurement", unit="km", depends_on=["time"],
                uncertainty=UncertaintySpec(type="std", column=f"sigma_{axis}"),
            )
        )
        variables.append(var(f"sigma_{axis}", "float", "uncertainty", unit="km"))
        variables.append(var(f"velocity_{axis}", "float", "measurement", unit="km/s", depends_on=["time"]))
    columns = {"time": [0.0, 1.0], "velocity_x": [1.0, 1.0], "velocity_y": [2.0, 2.0], "velocity_z": [3.0, 3.0]}
    for axis in ("x", "y", "z"):
        columns[f"position_{axis}"] = [0.0, 1.0]
        columns[f"sigma_{axis}"] = [0.01, 0.01]
    ds = make_dataset("trajectory", variables, columns, ["time"])
    assert {"position_x", "velocity_z", "sigma_y"} <= set(ds.observation_set.columns)


def test_physics_response():
    variables = [
        var("x", "float", "coordinate", unit="m"),
        var(
            "y", "float", "measurement", unit="K", depends_on=["x"],
            uncertainty=UncertaintySpec(type="asymmetric", lower_column="y_lo", upper_column="y_hi"),
        ),
        var("y_lo", "float", "uncertainty", unit="K"),
        var("y_hi", "float", "uncertainty", unit="K"),
    ]
    ds = make_dataset(
        "response",
        variables,
        {"x": [0.0, 1.0], "y": [1.0, 2.0], "y_lo": [0.9, 1.8], "y_hi": [1.2, 2.3]},
        ["x"],
    )
    assert ds.observation_set.variables[1].uncertainty.type == "asymmetric"


def test_biology_replicates():
    variables = [
        var("time", "float", "coordinate", unit="h"),
        var("replicate", "int", "coordinate"),
        var(
            "concentration", "float", "measurement", unit="mol/L", depends_on=["time", "replicate"],
            uncertainty=UncertaintySpec(type="stderr", value=0.05),
        ),
    ]
    ds = make_dataset(
        "replicates",
        variables,
        {"time": [0.0, 0.0, 1.0, 1.0], "replicate": [1, 2, 1, 2], "concentration": [1.0, 1.1, 0.5, 0.6]},
        ["time", "replicate"],
    )
    assert ds.observation_set.row_count == 4


def test_climate_point_observations():
    variables = [
        var("timestamp", "datetime", "coordinate"),
        var("latitude", "float", "coordinate", unit="rad"),
        var("longitude", "float", "coordinate", unit="rad"),
        var("altitude", "float", "coordinate", unit="m"),
        var(
            "temperature", "float", "measurement", unit="K",
            depends_on=["timestamp", "latitude", "longitude", "altitude"],
            uncertainty=UncertaintySpec(type="interval", level=0.95, lower_column="t_lo", upper_column="t_hi"),
        ),
        var("t_lo", "float", "uncertainty", unit="K"),
        var("t_hi", "float", "uncertainty", unit="K"),
    ]
    ds = make_dataset(
        "climate",
        variables,
        {
            "timestamp": ["2026-06-01T12:00:00+00:00"],
            "latitude": [0.7],
            "longitude": [1.3],
            "altitude": [100.0],
            "temperature": [288.0],
            "t_lo": [287.0],
            "t_hi": [289.0],
        },
        ["timestamp", "latitude", "longitude", "altitude"],
    )
    assert ds.observation_set.variables[4].uncertainty.type == "interval"


# ---------------------------------------------------------------------------
# 2-4. Serialization, deterministic hashing, references.
# ---------------------------------------------------------------------------


def test_canonical_serialization_round_trip():
    ds = simple_dataset()
    dumped = ds.model_dump(mode="json")
    again = Dataset.model_validate(dumped)
    assert again == ds
    assert again.content_hash == ds.content_hash
    assert again.dataset_id == ds.dataset_id


def test_content_hash_is_deterministic():
    assert simple_dataset().content_hash == simple_dataset().content_hash


def test_content_hash_changes_with_content():
    ds = simple_dataset()
    other = make_dataset(
        "simple",
        [var("t", "float", "coordinate", unit="s"), var("y", "float", "measurement", unit="K", depends_on=["t"])],
        {"t": [0.0, 1.0, 2.0], "y": [10.0, 11.0, 99.0]},
        ["t"],
    )
    assert other.content_hash != ds.content_hash
    assert other.dataset_id != ds.dataset_id


def test_dataset_ref_generation_matches_dataset():
    ds = simple_dataset()
    ref = make_dataset_ref(ds)
    assert ref.dataset_id == ds.dataset_id
    assert ref.content_hash == ds.content_hash
    assert ref.name == ds.name
    assert ref == ds.ref()


def test_compute_dataset_hash_matches_stored_field():
    ds = simple_dataset()
    assert compute_dataset_hash(ds) == ds.content_hash


def test_short_dataset_id_is_the_prefix():
    digest = "ab" * 32
    assert short_dataset_id(digest) == "ds-" + "ab" * 6
    with pytest.raises(ValueError):
        short_dataset_id("not-a-hash")


def test_dataset_rejects_inconsistent_content_hash():
    ds = simple_dataset()
    payload = ds.model_dump(mode="json")
    payload["content_hash"] = "0" * 64
    payload["dataset_id"] = short_dataset_id("0" * 64)
    with pytest.raises(ValidationError, match="content_hash does not match"):
        Dataset.model_validate(payload)


def test_dataset_rejects_inconsistent_dataset_id():
    ds = simple_dataset()
    payload = ds.model_dump(mode="json")
    payload["dataset_id"] = "ds-" + "0" * 12
    with pytest.raises(ValidationError, match="dataset_id"):
        Dataset.model_validate(payload)


def test_dataset_ref_rejects_mismatched_id():
    digest = "a" * 64
    with pytest.raises(ValidationError, match="does not match content_hash"):
        DatasetRef(dataset_id="ds-" + "b" * 12, content_hash=digest)


def test_resolve_dataset_id_returns_unique_full_hash():
    ds = simple_dataset()
    assert resolve_dataset_id(ds.dataset_id, [ds.ref()]) == ds.content_hash


def test_resolve_dataset_id_unknown_raises():
    ds = simple_dataset()
    with pytest.raises(ObservationIdentityError, match="no dataset"):
        resolve_dataset_id("ds-" + "0" * 12, [ds.ref()])


def test_resolve_dataset_id_prefix_collision_is_refused():
    # Two distinct full hashes that share the same 12-hex prefix (constructed
    # directly, since a real collision is computationally infeasible).
    shared = "ds-" + "0" * 12
    ref_a = DatasetRef.model_construct(dataset_id=shared, content_hash="a" * 64, name="a")
    ref_b = DatasetRef.model_construct(dataset_id=shared, content_hash="b" * 64, name="b")
    with pytest.raises(ObservationIdentityError, match="ambiguity"):
        resolve_dataset_id(shared, [ref_a, ref_b])


def test_assert_same_dataset_detects_prefix_collision():
    shared = "ds-" + "1" * 12
    ref_a = DatasetRef.model_construct(dataset_id=shared, content_hash="a" * 64, name="a")
    ref_b = DatasetRef.model_construct(dataset_id=shared, content_hash="b" * 64, name="b")
    with pytest.raises(ObservationIdentityError):
        assert_same_dataset(ref_a, ref_b)
    # A consistent pair is fine.
    assert_same_dataset(ref_a, ref_a)


# ---------------------------------------------------------------------------
# 5-7. Role, coordinate and column validation.
# ---------------------------------------------------------------------------


def test_coordinate_role_is_required():
    variables = [var("t", "float", "measurement", unit="s")]
    with pytest.raises(ValidationError, match="role 'coordinate'"):
        ObservationSet(coordinates=("t",), variables=tuple(variables), columns={"t": [0.0]})


def test_coordinate_variable_must_be_listed():
    variables = [var("t", "float", "coordinate", unit="s")]
    with pytest.raises(ValidationError, match="not listed in coordinates"):
        ObservationSet(coordinates=(), variables=tuple(variables), columns={"t": [0.0]})


def test_coordinate_kind_must_be_numeric_or_datetime():
    variables = [var("label", "categorical", "coordinate")]
    with pytest.raises(ValidationError, match="must be float/int/datetime"):
        ObservationSet(coordinates=("label",), variables=tuple(variables), columns={"label": ["a"]})


def test_unknown_dependency_is_rejected():
    variables = [var("y", "float", "measurement", unit="K", depends_on=["nope"])]
    with pytest.raises(ValidationError, match="undeclared coordinate"):
        ObservationSet(coordinates=(), variables=tuple(variables), columns={"y": [1.0]})


def test_duplicate_variable_names_are_rejected():
    variables = [var("y", "float", "measurement", unit="K"), var("y", "float", "measurement", unit="K")]
    with pytest.raises(ValidationError, match="duplicate variable names"):
        ObservationSet(variables=tuple(variables), columns={"y": [1.0]})


def test_columns_must_cover_exactly_the_variables():
    variables = [var("y", "float", "measurement", unit="K")]
    with pytest.raises(ValidationError, match="cover exactly the declared variables"):
        ObservationSet(variables=tuple(variables), columns={"y": [1.0], "extra": [2.0]})


def test_ragged_columns_are_rejected():
    variables = [var("t", "float", "coordinate", unit="s"), var("y", "float", "measurement", unit="K", depends_on=["t"])]
    with pytest.raises(ValidationError, match="same length"):
        ObservationSet(coordinates=("t",), variables=tuple(variables), columns={"t": [0.0, 1.0], "y": [1.0]})


def test_repeated_coordinate_values_are_allowed():
    variables = [
        var("time", "float", "coordinate", unit="s"),
        var("replicate", "int", "coordinate"),
        var("value", "float", "measurement", unit="count", depends_on=["time", "replicate"]),
    ]
    ds = make_dataset(
        "repeated",
        variables,
        {"time": [1.0, 1.0], "replicate": [1, 2], "value": [5.0, 6.0]},
        ["time", "replicate"],
    )
    assert ds.observation_set.row_count == 2
    assert ds.observation_set.rows()[0] == {"time": 1.0, "replicate": 1, "value": 5.0}


def test_derived_and_measurement_remain_distinguishable():
    variables = [
        var("t", "float", "coordinate", unit="s"),
        var("raw", "float", "measurement", unit="K", depends_on=["t"]),
        var("smooth", "float", "derived", unit="K", depends_on=["t"]),
    ]
    ds = make_dataset("derived", variables, {"t": [0.0], "raw": [1.0], "smooth": [1.1]}, ["t"])
    roles = {v.name: v.role for v in ds.observation_set.variables}
    assert roles["raw"] == "measurement" and roles["smooth"] == "derived"


# ---------------------------------------------------------------------------
# 8-11. Units.
# ---------------------------------------------------------------------------


def test_unspecified_unit_is_distinct_from_dimensionless():
    variable = var("x", "float", "measurement", unit=None)
    assert variable.unit is None
    assert var("x", "float", "measurement", unit="dimensionless").unit == "dimensionless"
    with pytest.raises(ValidationError):
        var("x", "float", "measurement", unit="")


def _mapping_dataset(unit: str | None = "K", name: str = "temperature"):
    variables = [var("t", "float", "coordinate", unit="s"), var(name, "float", "measurement", unit=unit, depends_on=["t"])]
    return make_dataset("mappable", variables, {"t": [0.0], name: [288.0]}, ["t"])


def test_mapping_with_compatible_units_is_valid():
    ds = _mapping_dataset("K")
    mapping = ObservationMapping(
        dataset=ds.ref(),
        model_ref=ModelRef(model_id="demo"),
        pairs=(MappingPair(observation="temperature", output="temperature", coordinates=("t",)),),
    )
    assert validate_mapping(mapping, dataset=ds, schema=demo_schema()) == ()


def test_mapping_with_incompatible_units_fails():
    ds = _mapping_dataset("m")
    mapping = ObservationMapping(
        dataset=ds.ref(),
        model_ref=ModelRef(model_id="demo"),
        pairs=(MappingPair(observation="temperature", output="temperature"),),
    )
    diagnostics = validate_mapping(mapping, dataset=ds, schema=demo_schema())
    assert [d.code for d in diagnostics] == ["incompatible_units"]


def test_mapping_with_unspecified_unit_fails():
    ds = _mapping_dataset(None)
    mapping = ObservationMapping(
        dataset=ds.ref(),
        model_ref=ModelRef(model_id="demo"),
        pairs=(MappingPair(observation="temperature", output="temperature"),),
    )
    diagnostics = validate_mapping(mapping, dataset=ds, schema=demo_schema())
    assert [d.code for d in diagnostics] == ["unspecified_unit"]


def test_mapping_with_explicit_conversion_is_valid():
    ds = _mapping_dataset("K", name="temperature")
    # exercise a compatible pair with a declared conversion between like units
    mapping = ObservationMapping(
        dataset=ds.ref(),
        model_ref=ModelRef(model_id="demo"),
        pairs=(
            MappingPair(
                observation="temperature", output="temperature",
                unit_conversion=UnitConversion(from_unit="K", to_unit="K"),
            ),
        ),
    )
    assert validate_mapping(mapping, dataset=ds, schema=demo_schema()) == ()


def test_mapping_with_wrong_unit_conversion_fails():
    ds = _mapping_dataset("K")
    mapping = ObservationMapping(
        dataset=ds.ref(),
        model_ref=ModelRef(model_id="demo"),
        pairs=(
            MappingPair(
                observation="temperature", output="temperature",
                unit_conversion=UnitConversion(from_unit="m", to_unit="K"),
            ),
        ),
    )
    diagnostics = validate_mapping(mapping, dataset=ds, schema=demo_schema())
    assert [d.code for d in diagnostics] == ["invalid_unit_conversion"]


def test_mapping_unknown_output_is_reported():
    ds = _mapping_dataset("K")
    mapping = ObservationMapping(
        dataset=ds.ref(), model_ref=ModelRef(model_id="demo"),
        pairs=(MappingPair(observation="temperature", output="nope"),),
    )
    assert [d.code for d in validate_mapping(mapping, dataset=ds, schema=demo_schema())] == [
        "unknown_output"
    ]


def test_mapping_coordinate_must_exist_and_be_depended_on():
    variables = [
        var("t", "float", "coordinate", unit="s"),
        var("w", "float", "coordinate", unit="m"),
        var("y", "float", "measurement", unit="K", depends_on=["t"]),
    ]
    ds = make_dataset("coords", variables, {"t": [0.0], "w": [1.0], "y": [1.0]}, ["t", "w"])
    unknown = ObservationMapping(
        dataset=ds.ref(), model_ref=ModelRef(model_id="demo"),
        pairs=(MappingPair(observation="y", output="temperature", coordinates=("missing",)),),
    )
    assert [d.code for d in validate_mapping(unknown, dataset=ds, schema=demo_schema())] == [
        "unknown_coordinate"
    ]
    not_dependent = ObservationMapping(
        dataset=ds.ref(), model_ref=ModelRef(model_id="demo"),
        pairs=(MappingPair(observation="y", output="temperature", coordinates=("w",)),),
    )
    assert [d.code for d in validate_mapping(not_dependent, dataset=ds, schema=demo_schema())] == [
        "coordinate_not_dependent"
    ]


def test_mapping_dataset_and_model_mismatch():
    ds = _mapping_dataset("K")
    other = simple_dataset()
    mapping = ObservationMapping(
        dataset=other.ref(), model_ref=ModelRef(model_id="other"),
        pairs=(MappingPair(observation="temperature", output="temperature"),),
    )
    codes = [d.code for d in validate_mapping(mapping, dataset=ds, schema=demo_schema())]
    assert "dataset_mismatch" in codes and "model_mismatch" in codes


def test_convert_to_output_explicit_conversion():
    converted = convert_to_output(
        1.0, observation_unit="km", output_unit="m",
        conversion=UnitConversion(from_unit="km", to_unit="m"),
    )
    assert converted == pytest.approx(1000.0)


def test_convert_requires_explicit_conversion_when_units_differ():
    # km and m are compatible but differ; no hidden scaling is allowed.
    with pytest.raises(ObservationError, match="explicit unit_conversion"):
        convert_to_output(1.0, observation_unit="km", output_unit="m")


def test_convert_identity_and_unspecified_and_incompatible():
    assert convert_to_output(2.0, observation_unit="K", output_unit="K") == 2.0
    with pytest.raises(ObservationError, match="unspecified"):
        convert_to_output(1.0, observation_unit=None, output_unit="K")
    with pytest.raises(ObservationError, match="incompatible"):
        convert_to_output(1.0, observation_unit="m", output_unit="K")


# ---------------------------------------------------------------------------
# 12-13. Uncertainty variants and companion columns.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("spec", [
    UncertaintySpec(type="none"),
    UncertaintySpec(type="std", value=0.1),
    UncertaintySpec(type="stderr", value=0.1),
    UncertaintySpec(type="precision", value=0.01),
    UncertaintySpec(type="asymmetric", lower=0.1, upper=0.2),
    UncertaintySpec(type="interval", level=0.95, lower=0.1, upper=0.2),
])
def test_uncertainty_variants_are_accepted(spec):
    assert spec.type in ("none", "std", "stderr", "precision", "asymmetric", "interval")


@pytest.mark.parametrize("kwargs", [
    {"type": "std", "value": 0.1, "column": "e"},
    {"type": "std"},
    {"type": "none", "value": 0.1},
    {"type": "asymmetric", "lower": 0.2, "upper": 0.1},
    {"type": "interval", "level": 1.5, "lower": 0.1, "upper": 0.2},
    {"type": "interval", "lower": 0.1, "upper": 0.2},
])
def test_invalid_uncertainty_combinations_are_rejected(kwargs):
    with pytest.raises(ValidationError):
        UncertaintySpec(**kwargs)


def test_companion_uncertainty_column_must_exist_and_be_role_uncertainty():
    good = make_dataset(
        "ok",
        [var("t", "float", "coordinate", unit="s"), var("y", "float", "measurement", unit="K", depends_on=["t"], uncertainty=UncertaintySpec(type="std", column="e")), var("e", "float", "uncertainty", unit="K")],
        {"t": [0.0], "y": [1.0], "e": [0.1]},
        ["t"],
    )
    assert good.observation_set.variables[1].uncertainty.column == "e"

    with pytest.raises(ValidationError, match="unknown column"):
        ObservationSet(
            coordinates=("t",),
            variables=(
                var("t", "float", "coordinate", unit="s"),
                var("y", "float", "measurement", unit="K", depends_on=["t"], uncertainty=UncertaintySpec(type="std", column="missing")),
            ),
            columns={"t": [0.0], "y": [1.0]},
        )

    with pytest.raises(ValidationError, match="role 'uncertainty'"):
        ObservationSet(
            coordinates=("t",),
            variables=(
                var("t", "float", "coordinate", unit="s"),
                var("y", "float", "measurement", unit="K", depends_on=["t"], uncertainty=UncertaintySpec(type="std", column="e")),
                var("e", "float", "measurement", unit="K"),
            ),
            columns={"t": [0.0], "y": [1.0], "e": [0.1]},
        )


def test_uncertainty_role_is_required():
    variables = [var("y", "float", "measurement", unit="K", uncertainty=UncertaintySpec(type="std", value=0.1))]
    # uncertainty inline on a measurement is fine; on a coordinate it is not
    assert variables[0].uncertainty is not None
    with pytest.raises(ValidationError, match="only valid on measured variables"):
        var("t", "float", "coordinate", unit="s", uncertainty=UncertaintySpec(type="std", value=0.1))


# ---------------------------------------------------------------------------
# 14. Missing / quality semantics.
# ---------------------------------------------------------------------------


def test_classify_value_semantics():
    assert classify_value("float", None) == "missing"
    assert classify_value("float", _NAN) == "non_finite"
    assert classify_value("float", _INF) == "non_finite"
    assert classify_value("float", True) == "invalid"
    assert classify_value("int", 1.5) == "invalid"
    assert classify_value("categorical", 3) == "invalid"
    assert classify_value("float", 1.0) is None


def test_non_finite_is_rejected_at_construction():
    variables = [var("y", "float", "measurement", unit="K")]
    with pytest.raises(ValidationError, match="non_finite"):
        ObservationSet(variables=tuple(variables), columns={"y": [_NAN]})


def test_invalid_kind_value_is_rejected_at_construction():
    variables = [var("y", "int", "measurement", unit="count")]
    with pytest.raises(ValidationError, match="invalid"):
        ObservationSet(variables=tuple(variables), columns={"y": [1.5]})


def test_quality_flags_do_not_delete_observations():
    quality = QualitySpec(flag_column="flag", rejected_flags=("bad",), censored_flags=("lo",), flagged_flags=("ok?",))
    variables = [
        var("t", "float", "coordinate", unit="s"),
        var("y", "float", "measurement", unit="K", depends_on=["t"], quality=quality),
        var("flag", "categorical", "quality"),
    ]
    ds = make_dataset(
        "quality",
        variables,
        {"t": [0.0, 1.0, 2.0, 3.0], "y": [1.0, 2.0, 3.0, 4.0], "flag": ["good", "bad", "lo", "ok?"]},
        ["t"],
    )
    summary = summarize_usability(ds.observation_set)
    entry = summary.entries[0]
    assert entry.total == 4
    # The 'bad' row is excluded; 'lo' is censored (excluded); 'ok?' is usable-but-flagged.
    assert entry.reasons == {"rejected": 1, "censored": 1, "flagged": 1}
    assert entry.usable == 2
    assert entry.excluded == 2
    # No row was deleted.
    assert ds.observation_set.row_count == 4


def test_missing_values_are_counted_not_dropped():
    variables = [var("y", "float", "measurement", unit="K")]
    ds = make_dataset("missing", variables, {"y": [1.0, None, 3.0]})
    entry = summarize_usability(ds.observation_set).entries[0]
    assert entry.total == 3 and entry.usable == 2 and entry.reasons == {"missing": 1}


# ---------------------------------------------------------------------------
# 15-16. Time.
# ---------------------------------------------------------------------------


def test_datetime_coordinate_is_accepted():
    variables = [var("timestamp", "datetime", "coordinate")]
    ds = make_dataset("dt", variables, {"timestamp": ["2026-01-01T00:00:00Z"]}, ["timestamp"])
    assert ds.observation_set.row_count == 1


def test_invalid_datetime_is_rejected():
    variables = [var("timestamp", "datetime", "coordinate")]
    with pytest.raises(ValidationError, match="invalid"):
        ObservationSet(coordinates=("timestamp",), variables=tuple(variables), columns={"timestamp": ["not-a-date"]})


def test_elapsed_time_coordinate():
    variables = [var("time", "float", "coordinate", unit="s")]
    ds = make_dataset("elapsed", variables, {"time": [0.0, 0.5, 1.0]}, ["time"])
    assert ds.observation_set.columns["time"] == [0.0, 0.5, 1.0]


# ---------------------------------------------------------------------------
# 17. Multi-coordinate variables.
# ---------------------------------------------------------------------------


def test_multi_coordinate_variable():
    variables = [
        var("time", "float", "coordinate", unit="s"),
        var("wavelength", "float", "coordinate", unit="m"),
        var("value", "float", "measurement", unit="Jy", depends_on=["time", "wavelength"]),
    ]
    ds = make_dataset(
        "multi",
        variables,
        {"time": [0.0, 0.0, 1.0], "wavelength": [5e-7, 6e-7, 5e-7], "value": [1.0, 1.1, 0.9]},
        ["time", "wavelength"],
    )
    assert ds.observation_set.variables[2].depends_on == ("time", "wavelength")


# ---------------------------------------------------------------------------
# 18-21. Mapping structure and exact alignment.
# ---------------------------------------------------------------------------


def test_mapping_requires_pairs():
    with pytest.raises(ValidationError, match="at least one pair"):
        ObservationMapping(dataset=simple_dataset().ref(), model_ref=ModelRef(model_id="demo"), pairs=())


def test_alignment_strategy_must_be_exact():
    assert AlignmentSpec().strategy == "exact"
    with pytest.raises(ValidationError):
        AlignmentSpec(strategy="interpolate")


def test_alignment_tolerance_must_be_valid():
    assert AlignmentSpec(tolerance=0.5).tolerance == 0.5
    with pytest.raises(ValidationError):
        AlignmentSpec(tolerance=-1.0)


def test_exact_alignment_matches_and_reports_unmatched():
    result = align([1.0, 2.0, 3.0], [1.0, 2.5, 3.0], tolerance=0.0)
    assert result.matches == [0, None, 2]
    assert result.matched == 2
    assert result.unmatched_query == [1]
    assert result.unmatched_reference == [1]


def test_alignment_tolerance_widens_the_match():
    result = align([1.0, 2.0, 3.0], [1.0, 2.5, 3.0], tolerance=0.5)
    assert result.matches == [0, 1, 2]
    assert result.matched == 3
    assert result.unmatched_query == []
    assert result.unmatched_reference == []


def test_unsupported_alignment_strategy_is_refused():
    with pytest.raises(ObservationError, match="unsupported alignment strategy"):
        align([1.0], [1.0], strategy="resample")


# ---------------------------------------------------------------------------
# Provenance.
# ---------------------------------------------------------------------------


def test_provenance_valid_and_invalid():
    assert provenance().source_kind == "synthetic"
    with pytest.raises(ValidationError):
        provenance(imported_at="yesterday")
    with pytest.raises(ValidationError):
        provenance(source_sha256="xyz")
    with pytest.raises(ValidationError):
        provenance(dataset_version="")
    with pytest.raises(ValidationError):
        provenance(source_kind="not-a-kind")


def test_dataset_file_metadata_validation():
    entry = DatasetFile(name="obs.csv", sha256="c" * 64, size_bytes=10, media_type="text/csv")
    assert entry.sha256 == "c" * 64
    with pytest.raises(ValidationError):
        DatasetFile(name="obs.csv", sha256="short", size_bytes=10)
    with pytest.raises(ValidationError):
        DatasetFile(name="obs.csv", sha256="c" * 64, size_bytes=-1)
