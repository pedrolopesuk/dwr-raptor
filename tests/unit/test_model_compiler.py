"""Unit tests for the bounded model compiler."""

from __future__ import annotations

import math

import pytest

from drw.execution.context import RunContext
from drw.model_compiler import (
    COMPILER_VERSION,
    ModelCompilationError,
    compile_model_spec,
    compute_compile_hash,
)
from drw.schema.model_spec import (
    ModelSpecification,
    ModelSpecParameter,
    ModelSpecProvenance,
    ModelSpecRelationship,
    ModelSpecVariable,
    specification_to_schema,
    validate_model_specification,
)

pytestmark = pytest.mark.unit


def _spec(**overrides) -> ModelSpecification:
    base: dict = {
        "model_id": "decay",
        "version": "1.0.0",
        "description": "First-order exponential decay.",
        "domain": "physics",
        "kind": "ode",
        "parameters": (
            ModelSpecParameter(
                name="k", unit="1/s", nominal=0.5, lower=0.01, upper=5.0
            ),
        ),
        "variables": (ModelSpecVariable(name="y", kind="state", unit="count"),),
        "relationships": (
            ModelSpecRelationship(
                name="dy_dt", expression="-k * y", depends_on=("k", "y"), rate_of="y"
            ),
        ),
        "assumptions": ("first-order decay with a constant rate",),
        "initial_conditions": {"y": 1.0},
        "execution": {"t_span": [0.0, 5.0], "n_points": 51},
        "provenance": ModelSpecProvenance(created_at="2026-01-01T00:00:00+00:00"),
    }
    base.update(overrides)
    return ModelSpecification(**base)


def test_valid_specification_compiles():
    compiled = compile_model_spec(_spec())
    assert compiled.model_id.startswith("mdl-")
    assert compiled.compiler_version == COMPILER_VERSION
    assert compiled.state_names == ("y",)
    assert compiled.parameter_names == ("k",)
    assert compiled.rate_expressions == {"y": "-k * y"}
    assert compiled.schema.model_id == compiled.model_id
    assert compiled.schema.runtime == "drw/compiled-ode"
    assert compiled.schema.metadata["compiled"] is True
    assert compiled.schema.metadata["spec_hash"] == compiled.spec_hash
    assert [o.name for o in compiled.schema.outputs] == ["y"]
    assert [p.name for p in compiled.schema.parameters] == ["y", "k"]


def test_compiled_model_executes_and_matches_the_analytic_solution():
    compiled = compile_model_spec(_spec())
    adapter = compiled.build_adapter()
    result = adapter.run(
        {"k": 0.5, "y": 1.0}, RunContext(run_id="r", experiment_id="e")
    )
    assert result.ok
    values = result.outputs["y"].values
    assert len(values) == 51
    assert values[0] == pytest.approx(1.0)
    assert values[-1] == pytest.approx(math.exp(-0.5 * 5.0), rel=1e-3)


def test_identity_is_deterministic_and_sensitive_to_content():
    first = compile_model_spec(_spec())
    second = compile_model_spec(_spec())
    assert first.model_id == second.model_id
    assert first.compile_hash == second.compile_hash

    changed_expression = _spec(
        relationships=(
            ModelSpecRelationship(
                name="dy_dt",
                expression="-2 * k * y",
                depends_on=("k", "y"),
                rate_of="y",
            ),
        )
    )
    assert compile_model_spec(changed_expression).model_id != first.model_id

    changed_version = _spec(version="2.0.0")
    assert compile_model_spec(changed_version).model_id != first.model_id


def test_compute_compile_hash_is_deterministic():
    payload = dict(
        spec_hash="a" * 64,
        declared_model_id="m",
        version="1.0.0",
        state_names=["y"],
        parameter_names=["k"],
        rate_expressions={"y": "-k*y"},
        t_span=[0.0, 1.0],
        n_points=11,
        solver="auto",
        time_unit="s",
    )
    assert compute_compile_hash(**payload) == compute_compile_hash(**payload)


def test_two_state_system_compiles():
    spec = _spec(
        parameters=(
            ModelSpecParameter(
                name="k", unit="1/s", nominal=1.0, lower=0.1, upper=10.0
            ),
        ),
        variables=(
            ModelSpecVariable(name="x", kind="state", unit="m"),
            ModelSpecVariable(name="v", kind="state", unit="m/s"),
        ),
        relationships=(
            ModelSpecRelationship(
                name="dx", expression="v", depends_on=("v",), rate_of="x"
            ),
            ModelSpecRelationship(
                name="dv", expression="-k * x", depends_on=("k", "x"), rate_of="v"
            ),
        ),
        initial_conditions={"x": 1.0, "v": 0.0},
    )
    compiled = compile_model_spec(spec)
    assert compiled.state_names == ("x", "v")
    assert set(compiled.rate_expressions) == {"x", "v"}


def test_whitelisted_functions_and_time_are_allowed():
    spec = _spec(
        relationships=(
            ModelSpecRelationship(
                name="dy_dt",
                expression="-k * y + sin(t) + exp(-t)",
                depends_on=("k", "y"),
                rate_of="y",
            ),
        )
    )
    compile_model_spec(spec)  # does not raise


def test_structural_errors_block_compilation():
    spec = _spec(initial_conditions={})
    with pytest.raises(ModelCompilationError) as exc:
        compile_model_spec(spec)
    assert exc.value.code == "invalid_model_spec"
    assert any(d.code == "missing_initial_condition" for d in exc.value.diagnostics)


def test_non_ode_kind_is_rejected():
    with pytest.raises(ModelCompilationError) as exc:
        compile_model_spec(_spec(kind="algebraic"))
    assert exc.value.code == "unsupported_model_kind"


def test_derived_variables_are_rejected():
    spec = _spec(
        variables=(
            ModelSpecVariable(name="y", kind="state", unit="count"),
            ModelSpecVariable(name="z", kind="derived", unit="count"),
        )
    )
    with pytest.raises(ModelCompilationError) as exc:
        compile_model_spec(spec)
    assert exc.value.code == "unsupported_variable_kind"


def test_non_rate_relationship_is_rejected():
    spec = _spec(
        relationships=(
            ModelSpecRelationship(name="dy_dt", expression="-k * y", rate_of="y"),
            ModelSpecRelationship(
                name="energy", expression="0.5 * y", depends_on=("y",)
            ),
        )
    )
    with pytest.raises(ModelCompilationError) as exc:
        compile_model_spec(spec)
    assert exc.value.code == "unsupported_relationship"


def test_missing_rate_equation_is_rejected():
    spec = _spec(
        variables=(
            ModelSpecVariable(name="y", kind="state", unit="count"),
            ModelSpecVariable(name="w", kind="state", unit="count"),
        ),
        relationships=(
            ModelSpecRelationship(name="dy_dt", expression="-k * y", rate_of="y"),
        ),
        initial_conditions={"y": 1.0, "w": 1.0},
    )
    with pytest.raises(ModelCompilationError) as exc:
        compile_model_spec(spec)
    assert exc.value.code == "missing_rate_equation"


def test_duplicate_rate_equation_is_rejected():
    spec = _spec(
        relationships=(
            ModelSpecRelationship(name="dy_dt", expression="-k * y", rate_of="y"),
            ModelSpecRelationship(name="dy_dt_2", expression="-y", rate_of="y"),
        )
    )
    with pytest.raises(ModelCompilationError) as exc:
        compile_model_spec(spec)
    assert exc.value.code == "duplicate_rate_equation"


@pytest.mark.parametrize(
    "expression",
    [
        "z * y",  # unknown symbol
        "__import__('os')",  # call is not a whitelisted function
        "y.real",  # attribute access
        "y if k else 0",  # conditional expression
        "lambda t: t",  # lambda (also not an expression body)
        "y > 1",  # comparison
        "os.system('echo')",  # attribute call
        "'text'",  # non-numeric literal
        "[y, k]",  # list
    ],
)
def test_unsupported_expressions_fail_closed(expression):
    spec = _spec(
        relationships=(
            ModelSpecRelationship(name="dy_dt", expression=expression, rate_of="y"),
        )
    )
    with pytest.raises(ModelCompilationError) as exc:
        compile_model_spec(spec)
    assert exc.value.code == "unsupported_expression"


@pytest.mark.parametrize(
    "execution",
    [
        {"t_span": [5.0, 0.0], "n_points": 11},
        {"t_span": [0.0, 1.0], "n_points": 1},
        {"t_span": [0.0, 1.0], "n_points": 11, "solver": "magic"},
        {"t_span": [0.0], "n_points": 11},
    ],
)
def test_invalid_execution_config_is_rejected(execution):
    with pytest.raises(ModelCompilationError) as exc:
        compile_model_spec(_spec(execution=execution))
    assert exc.value.code == "invalid_execution_config"


def test_declarative_projection_skips_rate_relationships():
    schema = specification_to_schema(_spec())
    assert [o.name for o in schema.outputs] == ["y"]
    assert schema.metadata["compiled"] is False


def test_ode_without_rate_equations_warns():
    spec = _spec(
        relationships=(
            ModelSpecRelationship(
                name="dy_dt", expression="-k * y", depends_on=("k", "y")
            ),
        )
    )
    codes = {d.code for d in validate_model_specification(spec)}
    assert "no_rate_equations" in codes
