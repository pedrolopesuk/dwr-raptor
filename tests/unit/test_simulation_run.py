"""Unit tests for running simulations and the synthetic/empirical boundary."""

from __future__ import annotations

import pytest

from drw.dataset_store import DatasetStore
from drw.execution.runner import Runner
from drw.model_compiler import compile_model_spec
from drw.model_store import ModelStore
from drw.schema.model import ModelRef
from drw.schema.model_spec import (
    ModelSpecification,
    ModelSpecParameter,
    ModelSpecProvenance,
    ModelSpecRelationship,
    ModelSpecVariable,
)
from drw.schema.simulation import (
    SimulationConfig,
    SimulationSpec,
    SyntheticObservationError,
    assert_empirical,
    is_synthetic,
)
from drw.simulation import (
    SimulationError,
    default_simulation_config,
    prepare_simulation,
    simulate,
    validate_simulation,
)
from drw.simulation_store import SimulationStore, simulation_id_for

pytestmark = pytest.mark.unit

_AT = "2026-01-01T00:00:00+00:00"


def _spec(*, nominal: float | None = 0.5) -> ModelSpecification:
    return ModelSpecification(
        model_id="decay",
        version="1.0.0",
        description="First-order decay.",
        domain="physics",
        kind="ode",
        parameters=(
            ModelSpecParameter(
                name="k", unit="1/s", nominal=nominal, lower=0.01, upper=5.0
            ),
        ),
        variables=(ModelSpecVariable(name="y", kind="state", unit="count"),),
        relationships=(
            ModelSpecRelationship(
                name="dy_dt", expression="-k * y", depends_on=("k", "y"), rate_of="y"
            ),
        ),
        assumptions=("constant rate",),
        initial_conditions={"y": 1.0},
        execution={"t_span": [0.0, 5.0], "n_points": 51},
        provenance=ModelSpecProvenance(created_at=_AT),
    )


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    root = tmp_path / "ws"
    monkeypatch.setenv("DRW_WORKSPACE", str(root))
    compiled = compile_model_spec(_spec())
    ModelStore(root).save(compiled)
    return root, compiled


def _simulation(compiled, **overrides) -> SimulationSpec:
    base = {
        "model_ref": ModelRef(model_id=compiled.model_id, version="1.0.0"),
        "model_hash": compiled.schema.content_hash(),
        "parameters": {"k": 0.5},
        "initial_conditions": {"y": 1.0},
        "scenario": "nominal",
        "config": SimulationConfig(t_span=(0.0, 5.0), n_points=51, seed=0),
    }
    base.update(overrides)
    return SimulationSpec(**base)


def test_simulate_runs_the_runner_and_stores_a_synthetic_dataset(workspace):
    root, compiled = workspace
    spec = _simulation(compiled)
    outcome = simulate(spec)  # default Runner (subprocess isolation)

    assert outcome.run.succeeded
    assert outcome.dataset_ref.dataset_id.startswith("ds-")
    assert outcome.result.simulation_hash == spec.content_hash()
    assert outcome.result.synthetic is True
    assert outcome.result.dataset_ref is not None
    assert outcome.result.observation_set is not None
    assert outcome.result.observation_set.row_count == 51

    provenance = outcome.dataset.provenance
    assert is_synthetic(provenance) is True
    assert provenance.source_kind == "synthetic"
    assert provenance.source_id == compiled.model_id
    assert provenance.preprocessing
    assert provenance.preprocessing[0].operation == "simulation"

    # Persisted and loadable.
    DatasetStore(root).save(outcome.dataset)
    reloaded = DatasetStore(root).load(outcome.dataset_ref.dataset_id)
    assert reloaded.content_hash == outcome.dataset.content_hash


def test_synthetic_dataset_is_refused_by_empirical_guards(workspace):
    _root, compiled = workspace
    outcome = simulate(_simulation(compiled))
    provenance = outcome.dataset.provenance
    for what in ("Evaluation", "Calibration", "Validation"):
        with pytest.raises(SyntheticObservationError):
            assert_empirical(provenance, what=what)


def test_simulation_is_deterministic_with_a_fixed_timestamp(workspace):
    _root, compiled = workspace
    spec = _simulation(compiled)
    first = simulate(spec, generated_at=_AT)
    second = simulate(spec, generated_at=_AT)
    assert first.dataset_ref.dataset_id == second.dataset_ref.dataset_id
    assert first.dataset_ref.content_hash == second.dataset_ref.content_hash
    assert first.result.observation_set.columns == second.result.observation_set.columns
    assert first.result.simulation_hash == second.result.simulation_hash


def test_simulation_store_is_idempotent(workspace):
    root, compiled = workspace
    outcome = simulate(_simulation(compiled), generated_at=_AT)
    store = SimulationStore(root)
    first = store.save(outcome.result)
    second = store.save(outcome.result)
    assert first.simulation_id == second.simulation_id
    assert first.simulation_id == simulation_id_for(outcome.result.simulation_hash)
    assert (
        store.load(first.simulation_id).simulation_hash
        == outcome.result.simulation_hash
    )
    assert store.verify(first.simulation_id).ok is True


def test_default_simulation_config_matches_the_model_window(workspace):
    _root, compiled = workspace
    config = default_simulation_config(compiled.model_id)
    assert config.t_span == (0.0, 5.0)
    assert config.n_points == 51


def test_validate_simulation_reports_structured_problems(workspace):
    _root, compiled = workspace

    unknown = _simulation(
        compiled, model_ref=ModelRef(model_id="mdl-000000000000", version="1.0.0")
    )
    errors = validate_simulation(unknown)
    assert any(d.code == "unknown_model" for d in errors)

    mismatch = _simulation(compiled, model_hash="b" * 64)
    assert any(d.code == "model_hash_mismatch" for d in validate_simulation(mismatch))

    bad_window = _simulation(
        compiled, config=SimulationConfig(t_span=(0.0, 99.0), n_points=51)
    )
    assert any(
        d.code == "simulation_window_mismatch" for d in validate_simulation(bad_window)
    )

    unknown_output = _simulation(compiled, outputs=("nope",))
    assert any(d.code == "unknown_output" for d in validate_simulation(unknown_output))

    unknown_param = _simulation(compiled, parameters={"nope": 1.0})
    assert any(
        d.code == "unknown_parameter" for d in validate_simulation(unknown_param)
    )

    out_of_bounds = _simulation(compiled, parameters={"k": 99.0})
    assert any(
        d.code == "value_out_of_bounds" for d in validate_simulation(out_of_bounds)
    )


def test_missing_parameter_fails_closed(tmp_path, monkeypatch):
    root = tmp_path / "ws"
    monkeypatch.setenv("DRW_WORKSPACE", str(root))
    compiled = compile_model_spec(_spec(nominal=None))
    ModelStore(root).save(compiled)
    spec = _simulation(compiled, parameters={})
    assert any(d.code == "missing_parameter" for d in validate_simulation(spec))
    with pytest.raises(SimulationError) as exc:
        prepare_simulation(spec)
    assert exc.value.code == "missing_parameter"


def test_scalar_output_cannot_be_stored_as_a_dataset(tmp_path, monkeypatch):
    root = tmp_path / "ws"
    monkeypatch.setenv("DRW_WORKSPACE", str(root))
    # The built-in oscillator declares a scalar output.
    from drw.models.registry import build_model

    schema = build_model("oscillator").describe()
    config = default_simulation_config("oscillator")
    spec = SimulationSpec(
        model_ref=ModelRef(model_id="oscillator", version=schema.version),
        model_hash=schema.content_hash(),
        parameters={"m": 1.0, "k": 4.0, "c": 0.2, "x0": 1.0, "v0": 0.0},
        initial_conditions={"x0": 1.0, "v0": 0.0},
        outputs=("peak_displacement",),
        config=config,
    )
    errors = validate_simulation(spec)
    assert any(d.code == "unsupported_output_kind" for d in errors)


def test_simulate_can_use_an_injected_runner(workspace):
    _root, compiled = workspace
    adapter = compiled.build_adapter()
    outcome = simulate(
        _simulation(compiled), runner=Runner(adapter=adapter), generated_at=_AT
    )
    assert outcome.run.succeeded
    assert outcome.dataset_ref.dataset_id.startswith("ds-")
