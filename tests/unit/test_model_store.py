"""Unit tests for the compiled-model store."""

from __future__ import annotations

import json

import pytest

from drw.model_compiler import compile_model_spec
from drw.model_store import (
    InvalidModelId,
    ModelCorruptedError,
    ModelNotFoundError,
    ModelStore,
)
from drw.schema.model_spec import (
    ModelSpecification,
    ModelSpecParameter,
    ModelSpecProvenance,
    ModelSpecRelationship,
    ModelSpecVariable,
)

pytestmark = pytest.mark.unit


def _spec() -> ModelSpecification:
    return ModelSpecification(
        model_id="decay",
        version="1.0.0",
        description="decay",
        domain="physics",
        kind="ode",
        parameters=(
            ModelSpecParameter(
                name="k", unit="1/s", nominal=0.5, lower=0.01, upper=5.0
            ),
        ),
        variables=(ModelSpecVariable(name="y", kind="state", unit="count"),),
        relationships=(
            ModelSpecRelationship(
                name="dy_dt", expression="-k * y", depends_on=("k", "y"), rate_of="y"
            ),
        ),
        initial_conditions={"y": 1.0},
        execution={"t_span": [0.0, 5.0], "n_points": 51},
        provenance=ModelSpecProvenance(created_at="2026-01-01T00:00:00+00:00"),
    )


@pytest.fixture
def store(tmp_path) -> ModelStore:
    return ModelStore(tmp_path / "ws")


def test_save_load_round_trip(store):
    compiled = compile_model_spec(_spec())
    ref = store.save(compiled)
    assert ref.model_id == compiled.model_id
    assert ref.model_id == "mdl-" + compiled.compile_hash[:12]
    assert store.exists(ref.model_id) is True

    loaded = store.load(ref.model_id)
    assert loaded.model_id == compiled.model_id
    assert loaded.state_names == ("y",)
    assert loaded.parameter_names == ("k",)
    assert loaded.rate_expressions == {"y": "-k * y"}
    assert loaded.schema.content_hash() == compiled.schema.content_hash()

    adapter = store.build(ref.model_id)
    assert [o.name for o in adapter.describe().outputs] == ["y"]


def test_save_is_idempotent(store):
    compiled = compile_model_spec(_spec())
    first = store.save(compiled)
    second = store.save(compiled)
    assert first.model_id == second.model_id
    assert len(store.list()) == 1


def test_list_and_ref(store):
    compiled = compile_model_spec(_spec())
    store.save(compiled)
    refs = store.list()
    assert [ref.model_id for ref in refs] == [compiled.model_id]
    assert refs[0].model_name == "decay"
    assert refs[0].compile_hash == compiled.compile_hash


def test_verify_ok(store):
    compiled = compile_model_spec(_spec())
    ref = store.save(compiled)
    report = store.verify(ref.model_id)
    assert report.ok is True
    assert report.errors == 0


def test_verify_detects_artifact_tampering(store):
    compiled = compile_model_spec(_spec())
    ref = store.save(compiled)
    artifact = store.directory(ref.model_id) / "artifact.json"
    document = json.loads(artifact.read_text(encoding="utf-8"))
    document["rate_expressions"] = {"y": "-999 * y"}
    artifact.write_text(json.dumps(document), encoding="utf-8")

    report = store.verify(ref.model_id)
    assert report.ok is False
    with pytest.raises(ModelCorruptedError):
        store.load(ref.model_id)


def test_missing_model_raises_not_found(store):
    with pytest.raises(ModelNotFoundError):
        store.load("mdl-0123456789ab")


@pytest.mark.parametrize(
    "bad_id", ["", "model", "mdl-zzzz", "../escape", "mdl-0123456789abc"]
)
def test_invalid_model_id_is_rejected(store, bad_id):
    with pytest.raises(InvalidModelId):
        store.directory(bad_id)


def test_changed_specification_yields_a_different_model(store):
    first = compile_model_spec(_spec())
    changed = _spec()
    changed = changed.model_copy(
        update={
            "relationships": (
                ModelSpecRelationship(
                    name="dy_dt",
                    expression="-2 * k * y",
                    depends_on=("k", "y"),
                    rate_of="y",
                ),
            )
        }
    )
    second = compile_model_spec(changed)
    store.save(first)
    store.save(second)
    assert first.model_id != second.model_id
    assert len(store.list()) == 2
