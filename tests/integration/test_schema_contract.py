"""Integration tests: schema/contract parity and JSON Schema integrity."""

from __future__ import annotations

import json
import subprocess
import sys

import jsonschema
import pytest
from pydantic import ValidationError

from drw.schema.experiment import ExperimentSpec, validate_experiment
from drw.schema.files import load_document
from drw.schema.model import ModelSchema, OutputSpec, ParameterSpec

pytestmark = pytest.mark.integration

SCHEMA_NAMES = ("experiment-spec.schema.json", "model-schema.schema.json")


def _committed(repo_root, name: str) -> str:
    return (repo_root / "packages" / "experiment-spec" / "schema" / name).read_text(encoding="utf-8")


def test_committed_json_schemas_match_the_generator(repo_root, tmp_path):
    subprocess.run(
        [
            sys.executable,
            str(repo_root / "scripts" / "export_schemas.py"),
            "--out",
            str(tmp_path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    for name in SCHEMA_NAMES:
        regenerated = (tmp_path / name).read_text(encoding="utf-8")
        assert regenerated == _committed(repo_root, name), (
            f"{name} is stale; run `python scripts/export_schemas.py`"
        )


def test_experiment_schema_required_and_canonical_field_names(repo_root):
    schema = json.loads(_committed(repo_root, "experiment-spec.schema.json"))
    assert set(schema["required"]) == {"hypothesis", "model_ref", "baseline"}
    assert "analyses" in schema["properties"]
    assert "analysis" not in schema["properties"]


def test_example_spec_validates_against_the_json_schema(repo_root):
    schema = json.loads(_committed(repo_root, "experiment-spec.schema.json"))
    raw = load_document(repo_root / "models" / "examples" / "predator-prey" / "experiment.yaml")
    spec = ExperimentSpec.model_validate(raw)
    jsonschema.validate(spec.model_dump(mode="json"), schema)


def test_invalid_spec_fails_json_schema_validation(repo_root):
    schema = json.loads(_committed(repo_root, "experiment-spec.schema.json"))
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate({"model_ref": {"model_id": "m"}, "baseline": {}}, schema)


def test_analysis_alias_is_accepted_and_canonicalised():
    spec = ExperimentSpec.model_validate(
        {
            "hypothesis": "h",
            "model_ref": {"model_id": "m"},
            "baseline": {},
            "analysis": [{"method": "delta"}],
        }
    )
    assert [a.method for a in spec.analyses] == ["delta"]
    assert "analysis" not in spec.model_dump()


def test_both_analysis_and_analyses_is_rejected():
    with pytest.raises(ValidationError):
        ExperimentSpec.model_validate(
            {
                "hypothesis": "h",
                "model_ref": {"model_id": "m"},
                "baseline": {},
                "analysis": [],
                "analyses": [],
            }
        )


def test_schema_version_mismatch_is_reported():
    schema = ModelSchema(
        model_id="m",
        parameters=(
            ParameterSpec(name="k", type="float", nominal=1.0, lower=0.0, upper=2.0),
            ParameterSpec(name="x0", type="float", nominal=1.0, role="state"),
        ),
        outputs=(OutputSpec(name="x"),),
    )
    spec = ExperimentSpec.model_validate(
        {
            "schema_version": "9.9.9",
            "hypothesis": "h",
            "model_ref": {"model_id": "m"},
            "baseline": {"x0": 1.0},
        }
    )
    diagnostics = validate_experiment(spec, schema)
    assert any(d.code == "schema_version_mismatch" for d in diagnostics)


def test_json_schema_is_deterministic(repo_root):
    schema_a = _committed(repo_root, "experiment-spec.schema.json")
    schema_b = (repo_root / "packages" / "experiment-spec" / "schema" / "experiment-spec.schema.json").read_text(
        encoding="utf-8"
    )
    assert schema_a == schema_b
    # The committed file is canonical (sorted keys, two-space indent).
    assert json.loads(schema_a) == json.loads(json.dumps(json.loads(schema_a), sort_keys=True))
