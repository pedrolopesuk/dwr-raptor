"""Unit tests for ModelSchema validation."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from drw.schema.model import ModelSchema, OutputSpec, ParameterSpec

pytestmark = pytest.mark.unit


def _schema(**overrides):
    data = {
        "model_id": "demo",
        "parameters": (
            ParameterSpec(name="k", type="float", nominal=1.0, lower=0.1, upper=10.0),
            ParameterSpec(name="x0", type="float", nominal=1.0, role="state"),
        ),
        "outputs": (OutputSpec(name="x"),),
    }
    data.update(overrides)
    return ModelSchema.model_validate(data)


def test_valid_schema_exposes_state_parameters():
    schema = _schema()
    assert [p.name for p in schema.state_parameters()] == ["x0"]
    assert schema.has_parameter("k")
    with pytest.raises(KeyError):
        schema.parameter("missing")


def test_duplicate_parameter_names_rejected():
    with pytest.raises(ValidationError):
        _schema(
            parameters=(
                ParameterSpec(name="k", type="float", nominal=1.0),
                ParameterSpec(name="k", type="float", nominal=2.0),
            )
        )


def test_nominal_outside_bounds_rejected():
    with pytest.raises(ValidationError):
        ParameterSpec(name="k", type="float", nominal=99.0, lower=0.0, upper=10.0)


def test_lower_must_be_below_upper():
    with pytest.raises(ValidationError):
        ParameterSpec(name="k", type="float", lower=10.0, upper=1.0)


def test_categorical_requires_options_and_valid_nominal():
    with pytest.raises(ValidationError):
        ParameterSpec(name="mode", type="categorical")
    with pytest.raises(ValidationError):
        ParameterSpec(name="mode", type="categorical", options=("a", "b"), nominal="c")
    param = ParameterSpec(name="mode", type="categorical", options=("a", "b"), nominal="a")
    assert param.options == ("a", "b")


def test_unknown_unit_is_treated_as_opaque_not_rejected():
    param = ParameterSpec(name="p", type="float", unit="prey", nominal=1.0)
    assert param.unit == "prey"


def test_content_hash_changes_with_schema():
    assert _schema().content_hash() == _schema().content_hash()
    assert _schema().content_hash() != _schema(version="9.9.9").content_hash()
