"""Bounded, deterministic compilation of a ModelSpecification into a DRW model.

The compiler consumes **only** the structured
:class:`~drw.schema.model_spec.ModelSpecification`. It never executes LLM-authored
Python: each relationship expression is parsed with the standard-library ``ast``
module and walked against a strict whitelist of node types and function names, then
frozen into a closure. Anything outside the supported subset fails **closed** with
a structured :class:`ModelCompilationError` - nothing is approximated.

Supported subset (M14):

* ``kind == "ode"``, state variables only (no ``derived`` variables);
* one rate equation per state variable: a relationship with ``rate_of`` naming that
  state (``d<state>/dt = expression``); non-rate relationships are unsupported;
* expressions over numeric literals, the declared state variables, the declared
  parameters, the independent variable ``t`` and the constants ``pi``/``e``, using
  ``+ - * / **``, unary ``+/-`` and calls to a fixed list of math functions.

The compiled model is projected onto the engine's existing
:class:`~drw.schema.model.ModelSchema` and executed by the existing
:class:`~drw.numerics.ode.OdeModel` / :class:`~drw.execution.runner.Runner`.
"""

from __future__ import annotations

import ast
import math
import operator
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from drw.schema.model import ModelSchema
from drw.schema.model_spec import (
    ModelSpecification,
    specification_to_schema,
    validate_model_specification,
)
from drw.schema.result import Diagnostic
from drw.schema.serialization import content_hash

__all__ = [
    "COMPILER_ID",
    "COMPILER_VERSION",
    "CompiledModel",
    "ModelCompilationError",
    "compile_model_spec",
    "compute_compile_hash",
    "supported_subset",
]

COMPILER_ID = "drw.model-compiler"
COMPILER_VERSION = "1.0.0"

_DEFAULT_T_SPAN = (0.0, 10.0)
_DEFAULT_N_POINTS = 200
_DEFAULT_TIME_UNIT = "s"
_SOLVERS = ("auto", "explicit", "stiff")

#: The whitelist of functions usable inside a rate equation. No attribute access,
#: no imports, no user-defined calls are possible.
_MATH_FUNCTIONS: dict[str, Callable[..., float]] = {
    "sin": math.sin,
    "cos": math.cos,
    "tan": math.tan,
    "sinh": math.sinh,
    "cosh": math.cosh,
    "tanh": math.tanh,
    "asin": math.asin,
    "acos": math.acos,
    "atan": math.atan,
    "exp": math.exp,
    "log": math.log,
    "log10": math.log10,
    "sqrt": math.sqrt,
    "fabs": math.fabs,
    "floor": math.floor,
    "ceil": math.ceil,
    "sign": lambda value: (value > 0) - (value < 0),
    "minimum": min,
    "maximum": max,
    "pow": pow,
}
_CONSTANTS: dict[str, float] = {"pi": math.pi, "e": math.e}
_BINOPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.Pow: operator.pow,
}
_UNARYOPS = {ast.UAdd: operator.pos, ast.USub: operator.neg}

Env = Mapping[str, float]
Closure = Callable[[Env], float]


class ModelCompilationError(ValueError):
    """A specification that cannot be compiled into a safe executable model."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        diagnostics: Sequence[Diagnostic] = (),
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.diagnostics = tuple(diagnostics)


class _UnsupportedConstruct(ValueError):
    """A single expression node outside the whitelist."""


def supported_subset() -> str:
    """A human-readable description of what the compiler can compile."""
    return (
        "kind='ode' with one rate equation per state variable (relationship "
        "'rate_of' naming a state); expressions over declared states/parameters, "
        "'t' and the constants pi/e using + - * / **, unary +/-, parentheses and "
        f"these functions: {', '.join(sorted(_MATH_FUNCTIONS))}."
    )


# ---------------------------------------------------------------------------
# Expression compilation (bounded; no eval of arbitrary code).
# ---------------------------------------------------------------------------


def _build_expr(node: ast.AST, allowed_names: frozenset[str]) -> Closure:
    if isinstance(node, ast.Expression):
        return _build_expr(node.body, allowed_names)
    if isinstance(node, ast.Constant):
        if isinstance(node.value, bool) or not isinstance(node.value, (int, float)):
            raise _UnsupportedConstruct("only numeric literals are allowed")
        value = float(node.value)
        return lambda env: value
    if isinstance(node, ast.Name):
        name = node.id
        if name in allowed_names:
            return lambda env: env[name]
        if name in _CONSTANTS:
            constant = _CONSTANTS[name]
            return lambda env: constant
        raise _UnsupportedConstruct(f"unknown symbol {name!r}")
    if isinstance(node, ast.UnaryOp):
        unary = _UNARYOPS.get(type(node.op))
        if unary is None:
            raise _UnsupportedConstruct(
                f"unary operator {type(node.op).__name__} is not allowed"
            )
        operand = _build_expr(node.operand, allowed_names)
        return lambda env: unary(operand(env))
    if isinstance(node, ast.BinOp):
        binary = _BINOPS.get(type(node.op))
        if binary is None:
            raise _UnsupportedConstruct(
                f"operator {type(node.op).__name__} is not allowed"
            )
        left = _build_expr(node.left, allowed_names)
        right = _build_expr(node.right, allowed_names)
        return lambda env: binary(left(env), right(env))
    if isinstance(node, ast.Call):
        if not isinstance(node.func, ast.Name) or node.func.id not in _MATH_FUNCTIONS:
            raise _UnsupportedConstruct(
                "only calls to whitelisted math functions are allowed"
            )
        if node.keywords:
            raise _UnsupportedConstruct("keyword arguments are not allowed")
        function = _MATH_FUNCTIONS[node.func.id]
        arguments = [_build_expr(arg, allowed_names) for arg in node.args]
        return lambda env: float(function(*(arg(env) for arg in arguments)))
    raise _UnsupportedConstruct(f"{type(node).__name__} is not allowed")


def _compile_expression(expression: str, allowed_names: frozenset[str]) -> Closure:
    try:
        tree = ast.parse(expression, mode="eval")
    except SyntaxError as exc:
        raise _UnsupportedConstruct(
            f"could not parse the expression: {exc.msg}"
        ) from exc
    return _build_expr(tree, allowed_names)


# ---------------------------------------------------------------------------
# Compiled model.
# ---------------------------------------------------------------------------


def compute_compile_hash(
    *,
    spec_hash: str,
    declared_model_id: str,
    version: str,
    state_names: Sequence[str],
    parameter_names: Sequence[str],
    rate_expressions: Mapping[str, str],
    t_span: Sequence[float],
    n_points: int,
    solver: str,
    time_unit: str,
) -> str:
    """Deterministic content identity of a compiled model.

    Depends on the source specification hash, the compiler identity, the resolved
    state/parameter order, the rate expressions and the execution window - so a
    changed specification (or compiler) yields a different identity.
    """
    payload = {
        "compiler": {"id": COMPILER_ID, "version": COMPILER_VERSION},
        "spec_hash": spec_hash,
        "declared_model_id": declared_model_id,
        "version": version,
        "state_names": list(state_names),
        "parameter_names": list(parameter_names),
        "rate_expressions": dict(rate_expressions),
        "t_span": [float(t_span[0]), float(t_span[1])],
        "n_points": int(n_points),
        "solver": solver,
        "time_unit": time_unit,
    }
    return content_hash(payload)


def _execution_config(
    spec: ModelSpecification,
) -> tuple[tuple[float, float], int, str, str]:
    raw = spec.execution or {}
    if not isinstance(raw, dict):  # pragma: no cover - pydantic enforces the type
        raise ModelCompilationError(
            "invalid_execution_config", "spec.execution must be an object"
        )
    span = raw.get("t_span", _DEFAULT_T_SPAN)
    if (
        not isinstance(span, (list, tuple))
        or len(span) != 2
        or any(isinstance(v, bool) or not isinstance(v, (int, float)) for v in span)
    ):
        raise ModelCompilationError(
            "invalid_execution_config",
            "execution.t_span must be a pair of numbers, e.g. [0, 10]",
        )
    t0, t1 = float(span[0]), float(span[1])
    if not (math.isfinite(t0) and math.isfinite(t1)) or t1 <= t0:
        raise ModelCompilationError(
            "invalid_execution_config", "execution.t_span must be finite and increasing"
        )
    n_points = raw.get("n_points", _DEFAULT_N_POINTS)
    if isinstance(n_points, bool) or not isinstance(n_points, int) or n_points < 2:
        raise ModelCompilationError(
            "invalid_execution_config", "execution.n_points must be an integer >= 2"
        )
    solver = raw.get("solver", "auto")
    if solver not in _SOLVERS:
        raise ModelCompilationError(
            "invalid_execution_config",
            f"execution.solver must be one of {list(_SOLVERS)}",
        )
    time_unit = raw.get("time_unit", _DEFAULT_TIME_UNIT)
    if not isinstance(time_unit, str) or not time_unit:
        raise ModelCompilationError(
            "invalid_execution_config", "execution.time_unit must be a non-empty string"
        )
    return (t0, t1), n_points, solver, time_unit


@dataclass(slots=True)
class CompiledModel:
    """A validated, executable model derived from a specification.

    Holds only serializable data (the specification, the projected schema, the rate
    expressions and the execution window); closures are rebuilt on demand so the
    artifact stays inspectable and is never arbitrary code.
    """

    model_id: str
    version: str
    spec: ModelSpecification
    spec_hash: str
    compile_hash: str
    schema: ModelSchema
    state_names: tuple[str, ...]
    parameter_names: tuple[str, ...]
    rate_expressions: dict[str, str]
    t_span: tuple[float, float]
    n_points: int
    solver: str
    time_unit: str
    compiler_id: str = COMPILER_ID
    compiler_version: str = COMPILER_VERSION
    diagnostics: tuple[Diagnostic, ...] = field(default_factory=tuple)

    def descriptor(self) -> dict[str, Any]:
        """The serializable executable descriptor (no spec/schema duplication)."""
        return {
            "schema_version": "1.0.0",
            "model_id": self.model_id,
            "version": self.version,
            "compiler_id": self.compiler_id,
            "compiler_version": self.compiler_version,
            "spec_hash": self.spec_hash,
            "compile_hash": self.compile_hash,
            "state_names": list(self.state_names),
            "parameter_names": list(self.parameter_names),
            "rate_expressions": dict(self.rate_expressions),
            "t_span": [self.t_span[0], self.t_span[1]],
            "n_points": self.n_points,
            "solver": self.solver,
            "time_unit": self.time_unit,
        }

    def build_adapter(
        self, *, solver: str | None = None, rtol: float = 1e-9, atol: float = 1e-12
    ) -> Any:
        """Build the engine model adapter (an :class:`~drw.numerics.ode.OdeModel`)."""
        from drw.numerics.ode import OdeModel

        allowed = frozenset(self.state_names) | frozenset(self.parameter_names) | {"t"}
        closures = [
            _compile_expression(self.rate_expressions[name], allowed)
            for name in self.state_names
        ]

        def rhs(
            t: float, y: Sequence[float], params: Mapping[str, float]
        ) -> list[float]:
            env: dict[str, float] = dict(params)
            env["t"] = float(t)
            for index, name in enumerate(self.state_names):
                env[name] = float(y[index])
            return [float(closure(env)) for closure in closures]

        return OdeModel(
            self.schema,
            rhs,
            t_span=self.t_span,
            n_points=self.n_points,
            output_names=self.state_names,
            solver=solver or self.solver,
            rtol=rtol,
            atol=atol,
            time_unit=self.time_unit,
        )


def compile_model_spec(spec: ModelSpecification) -> CompiledModel:
    """Compile ``spec`` into an executable model, or fail closed.

    Raises :class:`ModelCompilationError` with a stable ``code`` for an invalid
    specification or an unsupported construct. Never approximates.
    """
    structural = validate_model_specification(spec)
    errors = [d for d in structural if d.level == "error"]
    if errors:
        raise ModelCompilationError(
            "invalid_model_spec",
            "the model specification has errors and cannot be compiled",
            diagnostics=errors,
        )

    if spec.kind != "ode":
        raise ModelCompilationError(
            "unsupported_model_kind",
            f"only 'ode' specifications are compilable; got {spec.kind!r}",
        )

    derived = [v.name for v in spec.variables if v.kind != "state"]
    if derived:
        raise ModelCompilationError(
            "unsupported_variable_kind",
            f"derived variables are not supported by the compiler: {derived}",
        )

    state_names = tuple(v.name for v in spec.variables if v.kind == "state")
    parameter_names = tuple(p.name for p in spec.parameters)

    rate_expressions: dict[str, str] = {}
    for relationship in spec.relationships:
        if relationship.rate_of is None:
            raise ModelCompilationError(
                "unsupported_relationship",
                f"relationship {relationship.name!r} is not a rate equation "
                "(set 'rate_of' to the state variable it differentiates)",
            )
        if relationship.rate_of in rate_expressions:
            raise ModelCompilationError(
                "duplicate_rate_equation",
                f"state {relationship.rate_of!r} has more than one rate equation",
            )
        rate_expressions[relationship.rate_of] = relationship.expression

    missing = [name for name in state_names if name not in rate_expressions]
    if missing:
        raise ModelCompilationError(
            "missing_rate_equation",
            f"state variable(s) {missing} have no rate equation",
        )

    allowed = frozenset(state_names) | frozenset(parameter_names) | {"t"}
    for name in state_names:
        try:
            _compile_expression(rate_expressions[name], allowed)
        except _UnsupportedConstruct as exc:
            raise ModelCompilationError(
                "unsupported_expression",
                f"the rate equation for {name!r} is not supported: {exc}",
            ) from exc

    t_span, n_points, solver, time_unit = _execution_config(spec)
    spec_hash = spec.content_hash()
    compile_hash = compute_compile_hash(
        spec_hash=spec_hash,
        declared_model_id=spec.model_id,
        version=spec.version,
        state_names=state_names,
        parameter_names=parameter_names,
        rate_expressions=rate_expressions,
        t_span=t_span,
        n_points=n_points,
        solver=solver,
        time_unit=time_unit,
    )
    model_id = "mdl-" + compile_hash[:12]

    declared = specification_to_schema(spec)
    schema = declared.model_copy(
        update={
            "model_id": model_id,
            "version": spec.version,
            "runtime": "drw/compiled-ode",
            "metadata": {
                **dict(declared.metadata),
                "compiled": True,
                "compiler_id": COMPILER_ID,
                "compiler_version": COMPILER_VERSION,
                "spec_hash": spec_hash,
                "spec_model_id": spec.model_id,
                "domain": spec.domain,
                "kind": spec.kind,
                "t_span": [t_span[0], t_span[1]],
                "n_points": n_points,
                "time_unit": time_unit,
            },
        }
    )

    return CompiledModel(
        model_id=model_id,
        version=spec.version,
        spec=spec,
        spec_hash=spec_hash,
        compile_hash=compile_hash,
        schema=schema,
        state_names=state_names,
        parameter_names=parameter_names,
        rate_expressions=rate_expressions,
        t_span=t_span,
        n_points=n_points,
        solver=solver,
        time_unit=time_unit,
        diagnostics=tuple(structural),
    )
