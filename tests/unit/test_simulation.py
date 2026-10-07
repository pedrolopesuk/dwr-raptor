"""Unit tests for simulation provenance and the synthetic/real boundary."""

from __future__ import annotations

import pytest

from drw.schema.model import ModelRef
from drw.schema.observation import Provenance
from drw.schema.simulation import (
    SimulationConfig,
    SimulationSpec,
    SimulationUnsupported,
    SyntheticObservationError,
    assert_empirical,
    is_synthetic,
    simulation_supported,
    synthetic_provenance,
)

pytestmark = pytest.mark.unit

_MODEL_HASH = "a" * 64
_AT = "2026-01-01T00:00:00+00:00"


def _empirical() -> Provenance:
    return Provenance(source_kind="file", imported_at=_AT, dataset_version="1.0.0")


def test_synthetic_provenance_marks_synthetic():
    provenance = synthetic_provenance(
        source_model_id="predator-prey",
        source_model_hash=_MODEL_HASH,
        imported_at=_AT,
        parameters={"alpha": 1.1},
        seed=7,
    )
    assert provenance.source_kind == "synthetic"
    assert provenance.source_sha256 == _MODEL_HASH
    assert "alpha=1.1" in provenance.notes
    assert "seed=7" in provenance.notes
    assert is_synthetic(provenance) is True


def test_empirical_provenance_is_not_synthetic():
    assert is_synthetic(_empirical()) is False
    assert is_synthetic(None) is False


def test_assert_empirical_accepts_real_and_rejects_synthetic():
    assert_empirical(_empirical(), what="Evaluation")  # does not raise
    synthetic = synthetic_provenance(
        source_model_id="m", source_model_hash="short", imported_at=_AT
    )
    with pytest.raises(SyntheticObservationError) as exc:
        assert_empirical(synthetic, what="Evaluation")
    assert "synthetic" in str(exc.value).lower()


def test_simulation_is_supported():
    supported, reason = simulation_supported()
    assert supported is True
    assert "synthetic" in reason.lower()
    # The fail-closed exception type still exists.
    assert issubclass(SimulationUnsupported, RuntimeError)


def test_simulation_spec_hash_is_deterministic():
    spec = SimulationSpec(
        model_ref=ModelRef(model_id="predator-prey"),
        model_hash=_MODEL_HASH,
        parameters={"alpha": 1.1},
        initial_conditions={"prey0": 10.0, "predator0": 5.0},
        scenario="nominal",
        config=SimulationConfig(seed=3),
    )
    assert spec.content_hash() == spec.content_hash()
    assert (
        spec.content_hash()
        != spec.model_copy(update={"scenario": "other"}).content_hash()
    )


def test_simulation_result_is_synthetic_by_construction():
    from drw.schema.simulation import SimulationProvenance, SimulationResult

    spec = SimulationSpec(
        model_ref=ModelRef(model_id="m"),
        model_hash=_MODEL_HASH,
        parameters={},
        initial_conditions={},
    )
    result = SimulationResult(
        simulation_hash=spec.content_hash(),
        spec=spec,
        provenance=SimulationProvenance(
            source_model_id="m",
            source_model_hash=_MODEL_HASH,
            generated_at=_AT,
        ),
    )
    assert result.synthetic is True
    assert result.provenance.source_kind == "synthetic"
