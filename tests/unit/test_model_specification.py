"""Unit tests for structured model specifications and their store."""

from __future__ import annotations

import pytest

from drw.model_spec_store import InvalidModelSpecId, ModelSpecStore
from drw.schema.model_spec import (
    ModelSpecification,
    ModelSpecParameter,
    ModelSpecProvenance,
    ModelSpecRelationship,
    ModelSpecVariable,
    compilation_supported,
    specification_to_schema,
    validate_model_specification,
)

pytestmark = pytest.mark.unit


def _spec(**overrides) -> ModelSpecification:
    base = {
        "model_id": "projectile",
        "version": "1.0.0",
        "description": "A vertical projectile under constant gravity.",
        "domain": "physics",
        "kind": "ode",
        "parameters": (
            ModelSpecParameter(
                name="g", unit="m/s^2", nominal=9.81, lower=1.0, upper=20.0
            ),
        ),
        "variables": (ModelSpecVariable(name="v", kind="state", unit="m/s"),),
        "relationships": (
            ModelSpecRelationship(name="dvdt", expression="-g", depends_on=("g",)),
        ),
        "assumptions": ("gravity is constant and uniform.",),
        "initial_conditions": {"v": 0.0},
        "provenance": ModelSpecProvenance(created_at="2026-01-01T00:00:00+00:00"),
    }
    base.update(overrides)
    return ModelSpecification(**base)


def test_valid_specification_has_no_errors():
    diagnostics = validate_model_specification(_spec())
    assert [d for d in diagnostics if d.level == "error"] == []


def test_missing_initial_condition_is_an_error():
    spec = _spec(
        variables=(ModelSpecVariable(name="v", kind="state", unit="m/s"),),
        initial_conditions={},
    )
    codes = {d.code for d in validate_model_specification(spec) if d.level == "error"}
    assert "missing_initial_condition" in codes


def test_duplicate_names_are_rejected():
    spec = _spec(
        parameters=(
            ModelSpecParameter(
                name="v", unit="dimensionless", nominal=1.0, lower=0.0, upper=2.0
            ),
        )
    )
    codes = {d.code for d in validate_model_specification(spec) if d.level == "error"}
    assert "duplicate_names" in codes


def test_unknown_relationship_dependency_is_an_error():
    spec = _spec(
        relationships=(
            ModelSpecRelationship(name="dvdt", expression="-g", depends_on=("nope",)),
        )
    )
    codes = {d.code for d in validate_model_specification(spec) if d.level == "error"}
    assert "unknown_relationship_dependency" in codes


def test_incomplete_and_invalid_bounds_are_errors():
    incomplete = _spec(
        parameters=(
            ModelSpecParameter(name="g", unit="m/s^2", nominal=9.81, lower=1.0),
        )
    )
    assert any(
        d.code == "incomplete_bounds" for d in validate_model_specification(incomplete)
    )

    invalid = _spec(
        parameters=(
            ModelSpecParameter(
                name="g", unit="m/s^2", nominal=9.81, lower=20.0, upper=1.0
            ),
        )
    )
    assert any(
        d.code == "invalid_bounds" for d in validate_model_specification(invalid)
    )


def test_nominal_outside_bounds_is_an_error():
    spec = _spec(
        parameters=(
            ModelSpecParameter(
                name="g", unit="m/s^2", nominal=50.0, lower=1.0, upper=20.0
            ),
        )
    )
    assert any(
        d.code == "nominal_out_of_bounds" for d in validate_model_specification(spec)
    )


def test_compilation_is_supported_and_bounded():
    supported, reason = compilation_supported()
    assert supported is True
    assert "bounded" in reason.lower()


def test_specification_projects_to_a_declared_schema():
    schema = specification_to_schema(_spec())
    assert schema.model_id == "projectile"
    names = schema.parameter_names()
    assert "g" in names and "v" in names
    assert schema.parameter("v").role == "state"
    outputs = {o.name: o.kind for o in schema.outputs}
    assert outputs["v"] == "timeseries"
    assert outputs["dvdt"] == "scalar"
    assert schema.metadata["compiled"] is False
    assert schema.metadata["spec_hash"] == _spec().content_hash()


def test_spec_id_is_content_addressed():
    assert _spec().spec_id().startswith("mspec-")
    assert _spec().spec_id() == _spec().spec_id()
    changed = _spec(description="different")
    assert changed.spec_id() != _spec().spec_id()


def test_model_spec_store_round_trip_and_verify(tmp_path):
    store = ModelSpecStore(tmp_path / "ws")
    ref = store.save(_spec())
    assert store.exists(ref.spec_id) is True
    loaded = store.load(ref.spec_id)
    assert loaded.model_id == "projectile"
    assert loaded.content_hash() == ref.content_hash
    verification = store.verify(ref.spec_id)
    assert verification.ok is True
    assert store.list()[0].spec_id == ref.spec_id


def test_model_spec_store_rejects_bad_ids(tmp_path):
    store = ModelSpecStore(tmp_path / "ws")
    with pytest.raises(InvalidModelSpecId):
        store.path("mspec-zzzz")
