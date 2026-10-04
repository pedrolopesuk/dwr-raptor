"""Unit tests for deterministic sampling designs."""

from __future__ import annotations

import numpy as np
import pytest

from drw.numerics.sampling import expand_design
from drw.schema.experiment import ExperimentSpec
from drw.schema.model import ModelSchema, OutputSpec, ParameterSpec

pytestmark = pytest.mark.unit


def _schema() -> ModelSchema:
    return ModelSchema(
        model_id="demo",
        parameters=(
            ParameterSpec(name="k", type="float", nominal=1.0, lower=0.0, upper=10.0),
            ParameterSpec(name="j", type="float", nominal=1.0, lower=0.0, upper=5.0),
        ),
        outputs=(OutputSpec(name="x"),),
    )


def _spec(**overrides) -> ExperimentSpec:
    data = {
        "hypothesis": "h",
        "model_ref": {"model_id": "demo"},
        "baseline": {"k": 1.0, "j": 1.0},
        "factors": (
            {"parameter": "k", "values": [0.0, 1.0, 2.0]},
            {"parameter": "j", "values": [0.0, 1.0]},
        ),
    }
    data.update(overrides)
    return ExperimentSpec.model_validate(data)


def test_grid_is_cartesian_in_declared_order():
    design = expand_design(_spec(), _schema())
    assert len(design) == 6
    assert design.samples[0] == {"k": 0.0, "j": 0.0}
    assert design.samples[1] == {"k": 0.0, "j": 1.0}
    assert design.samples[-1] == {"k": 2.0, "j": 1.0}


def test_random_sampling_is_seeded_and_deterministic():
    spec = _spec(
        factors=(
            {"parameter": "k", "lower": 0.0, "upper": 10.0},
            {"parameter": "j", "lower": 0.0, "upper": 5.0},
        ),
        sampling={"method": "random", "n_samples": 4, "seed": 7},
    )
    first = expand_design(spec, _schema()).samples
    second = expand_design(spec, _schema()).samples
    other_seed = expand_design(
        spec.model_copy(update={"sampling": spec.sampling.model_copy(update={"seed": 8})}), _schema()
    ).samples
    assert first == second
    assert first != other_seed


@pytest.mark.parametrize("method", ["random", "latin_hypercube", "sobol"])
def test_stochastic_designs_respect_bounds(method):
    spec = _spec(
        factors=(
            {"parameter": "k", "lower": 0.0, "upper": 10.0},
            {"parameter": "j", "lower": 0.0, "upper": 5.0},
        ),
        sampling={"method": method, "n_samples": 8, "seed": 3},
    )
    design = expand_design(spec, _schema())
    assert len(design) == 8
    for sample in design.samples:
        assert 0.0 <= sample["k"] <= 10.0
        assert 0.0 <= sample["j"] <= 5.0


def test_sobol_warns_when_not_power_of_two():
    spec = _spec(
        factors=({"parameter": "k", "lower": 0.0, "upper": 10.0},),
        sampling={"method": "sobol", "n_samples": 6, "seed": 1},
    )
    design = expand_design(spec, _schema())
    assert any(w.code == "sobol_non_power_of_two" for w in design.warnings)


def test_no_factors_yields_empty_design():
    assert expand_design(_spec(factors=()), _schema()).samples == []


def test_values_are_floats():
    for sample in expand_design(_spec(), _schema()).samples:
        assert all(isinstance(v, float) for v in sample.values())
    assert np.isfinite(list(expand_design(_spec(), _schema()).samples[0].values())).all()
