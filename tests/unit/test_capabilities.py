"""Unit tests for model capability discovery."""

from __future__ import annotations

import pytest

from drw.capabilities import model_capabilities
from drw.models.registry import build_model
from drw.schema.model import ModelSchema, OutputSpec, ParameterSpec

pytestmark = pytest.mark.unit


def test_predator_prey_capabilities():
    caps = model_capabilities(build_model("predator-prey").describe())
    factorable = {p["name"] for p in caps["factorable_parameters"]}
    assert {"alpha", "beta", "delta", "gamma"} <= factorable
    assert "prey" in caps["timeseries_outputs"]
    assert "peak_prey" in caps["scalar_outputs"]
    assert caps["sensitivity"] == "oat"
    assert caps["analysis_methods"] == ["delta", "relative_delta"]
    assert caps["limitations"] == []


def test_capabilities_report_limitations_honestly():
    schema = ModelSchema(
        model_id="fixed-only",
        parameters=(ParameterSpec(name="x0", type="float", nominal=1.0, role="state"),),
        outputs=(OutputSpec(name="x", kind="matrix"),),
    )
    caps = model_capabilities(schema)
    assert caps["factorable_parameters"] == []
    assert caps["sensitivity"] is None
    assert any("bounds" in note for note in caps["limitations"])
    assert any("time-series" in note for note in caps["limitations"])
