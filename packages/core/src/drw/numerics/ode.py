"""SCI-001: deterministic ODE model adapter built on ``scipy.integrate.solve_ivp``.

Models are systems of first-order ODEs ``dy/dt = f(y, t; p)``. The adapter
records the *actual* solver and tolerances used on every run so the trajectory is
reproducible (specification sections 5.1 and 5.7).
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from typing import Any

import numpy as np
from scipy.integrate import solve_ivp

from drw.execution.context import RunContext
from drw.schema.model import ModelSchema
from drw.schema.result import (
    Diagnostic,
    ModelResult,
    OutputValue,
    RunStatus,
    ValidationReport,
)

__all__ = ["SOLVER_METHODS", "OdeModel", "RhsFunction"]

RhsFunction = Callable[[float, np.ndarray, Mapping[str, float]], Sequence[float]]

#: Maps the user-facing solver choice to a concrete SciPy method. "auto" and
#: "explicit" both select an explicit adaptive Runge-Kutta integrator, which is
#: the safe default for non-stiff systems; "stiff" selects an implicit method.
SOLVER_METHODS: dict[str, str] = {
    "auto": "RK45",
    "explicit": "RK45",
    "stiff": "BDF",
}


class OdeModel:
    """An ODE model adapter.

    Parameters
    ----------
    schema:
        Declared contract. Parameters with ``role="state"`` are the initial
        conditions, ordered exactly as the components of ``y``.
    rhs:
        Right-hand side ``f(t, y, params) -> dy/dt``.
    t_span:
        ``(t0, t1)`` integration interval (must be increasing).
    n_points:
        Number of equally spaced points in the evaluation grid.
    output_fn:
        Optional ``f(t, y, params) -> dict[str, float]`` producing additional
        scalar outputs (for example ``peak`` or ``final``).
    output_names:
        Declared output name for each state component, aligned with
        ``schema.state_parameters()``. Defaults to the state parameter names.
    """

    def __init__(
        self,
        schema: ModelSchema,
        rhs: RhsFunction,
        *,
        t_span: tuple[float, float],
        n_points: int = 200,
        output_fn: Callable[[np.ndarray, np.ndarray, Mapping[str, float]], dict[str, float]]
        | None = None,
        output_names: Sequence[str] | None = None,
        solver: str = "auto",
        rtol: float = 1e-8,
        atol: float = 1e-10,
        time_unit: str = "s",
    ) -> None:
        if solver not in SOLVER_METHODS:
            raise ValueError(f"unknown solver {solver!r}; expected one of {sorted(SOLVER_METHODS)}")
        if n_points < 2:
            raise ValueError("n_points must be >= 2")
        t0, t1 = t_span
        if t1 <= t0:
            raise ValueError(f"t_span must be increasing, got {t_span!r}")
        states = schema.state_parameters()
        if not states:
            raise ValueError(
                f"model {schema.model_id!r} declares no state parameters; an ODE needs "
                "initial conditions with role='state'"
            )

        names = tuple(output_names) if output_names is not None else tuple(p.name for p in states)
        if len(names) != len(states):
            raise ValueError(
                f"output_names has {len(names)} entries but the model has {len(states)} "
                "state parameters"
            )
        declared = {output.name for output in schema.outputs}
        missing = [name for name in names if name not in declared]
        if missing:
            raise ValueError(
                f"output_names {missing} are not declared as model outputs for "
                f"{schema.model_id!r}"
            )

        self._schema = schema
        self._rhs = rhs
        self._t_span = (float(t0), float(t1))
        self._n_points = int(n_points)
        self._output_fn = output_fn
        self._output_names = names
        self._solver = solver
        self._rtol = float(rtol)
        self._atol = float(atol)
        self._time_unit = time_unit

    # -- ModelAdapter protocol ---------------------------------------------

    def describe(self) -> ModelSchema:
        return self._schema

    @property
    def time_unit(self) -> str:
        return self._time_unit

    def evaluation_grid(self) -> np.ndarray:
        return np.linspace(self._t_span[0], self._t_span[1], self._n_points)

    def validate(self, inputs: Mapping[str, Any]) -> ValidationReport:
        diagnostics: list[Diagnostic] = []
        for param in self._schema.parameters:
            if param.name not in inputs:
                if param.nominal is None:
                    diagnostics.append(
                        Diagnostic(
                            level="error",
                            code="missing_parameter",
                            message=f"required parameter {param.name!r} was not provided",
                        )
                    )
                continue
            value = inputs[param.name]
            if param.type == "categorical":
                if str(value) not in param.options:
                    diagnostics.append(
                        Diagnostic(
                            level="error",
                            code="invalid_categorical",
                            message=f"{param.name}={value!r} is not one of {param.options}",
                        )
                    )
            elif param.type == "bool":
                if not isinstance(value, bool):
                    diagnostics.append(
                        Diagnostic(
                            level="error",
                            code="invalid_type",
                            message=f"{param.name} expects a boolean, got {type(value).__name__}",
                        )
                    )
            else:
                if isinstance(value, bool) or not isinstance(value, (int, float)):
                    diagnostics.append(
                        Diagnostic(
                            level="error",
                            code="invalid_type",
                            message=f"{param.name} expects a number, got {type(value).__name__}",
                        )
                    )
                    continue
                numeric = float(value)
                if not np.isfinite(numeric):
                    diagnostics.append(
                        Diagnostic(
                            level="error",
                            code="non_finite_input",
                            message=f"{param.name}={value!r} is not finite",
                        )
                    )
                if param.lower is not None and numeric < param.lower:
                    diagnostics.append(
                        Diagnostic(
                            level="error",
                            code="below_lower_bound",
                            message=f"{param.name}={numeric} is below lower bound {param.lower}",
                        )
                    )
                if param.upper is not None and numeric > param.upper:
                    diagnostics.append(
                        Diagnostic(
                            level="error",
                            code="above_upper_bound",
                            message=f"{param.name}={numeric} is above upper bound {param.upper}",
                        )
                    )
        known = set(self._schema.parameter_names())
        for name in inputs:
            if name not in known:
                diagnostics.append(
                    Diagnostic(
                        level="warning",
                        code="unknown_parameter",
                        message=f"input {name!r} is not declared by the model and was ignored",
                    )
                )
        ok = not any(d.level == "error" for d in diagnostics)
        return ValidationReport(ok=ok, diagnostics=tuple(diagnostics))

    def run(self, inputs: Mapping[str, Any], context: RunContext) -> ModelResult:
        report = self.validate(inputs)
        if not report.ok:
            return ModelResult(
                status=RunStatus.FAILED,
                outputs={},
                diagnostics=report.diagnostics,
            )

        numeric_inputs: dict[str, float] = {}
        for param in self._schema.parameters:
            value = inputs.get(param.name, param.nominal)
            numeric_inputs[param.name] = float(value)  # type: ignore[arg-type]

        initial_state = np.array(
            [float(inputs[p.name]) for p in self._schema.state_parameters()], dtype=float
        )
        if not np.all(np.isfinite(initial_state)):
            return ModelResult(
                status=RunStatus.FAILED,
                outputs={},
                diagnostics=(
                    Diagnostic(
                        level="error",
                        code="non_finite_initial_state",
                        message="initial state contains non-finite values",
                    ),
                ),
            )
        t_eval = self.evaluation_grid()
        choice = context.solver or self._solver
        method = SOLVER_METHODS.get(choice, SOLVER_METHODS["auto"])
        rtol = context.rtol or self._rtol
        atol = context.atol or self._atol

        def fun(t: float, y: np.ndarray) -> np.ndarray:
            return np.asarray(self._rhs(t, y, numeric_inputs), dtype=float)

        diagnostics: list[Diagnostic] = []
        try:
            solution = solve_ivp(
                fun,
                self._t_span,
                initial_state,
                method=method,
                t_eval=t_eval,
                rtol=rtol,
                atol=atol,
            )
        except Exception as exc:
            return ModelResult(
                status=RunStatus.FAILED,
                outputs={},
                diagnostics=(
                    Diagnostic(
                        level="error",
                        code="solver_exception",
                        message=f"{type(exc).__name__}: {exc}",
                    ),
                ),
            )

        diagnostics.append(
            Diagnostic(
                level="info",
                code="solver",
                message=(
                    f"method={method} rtol={rtol:g} atol={atol:g} "
                    f"nfev={getattr(solution, 'nfev', 'n/a')}"
                ),
            )
        )

        if not solution.success:
            diagnostics.append(
                Diagnostic(
                    level="error",
                    code="solver_failed",
                    message=str(solution.message),
                )
            )
            return ModelResult(
                status=RunStatus.FAILED,
                outputs={},
                diagnostics=tuple(diagnostics),
            )

        # A "successful" solve can still carry NaN/Inf (for example an overflow
        # the error controller did not reject). A run is SUCCEEDED only when
        # every value is finite; otherwise it is a deterministic failure.
        non_finite = ~np.isfinite(solution.y)
        if np.any(non_finite):
            state_index, step_index = (int(v) for v in np.argwhere(non_finite)[0])
            diagnostics.append(
                Diagnostic(
                    level="error",
                    code="non_finite_output",
                    message=(
                        "integration produced non-finite values "
                        f"(state index {state_index} at grid step {step_index})"
                    ),
                )
            )
            return ModelResult(
                status=RunStatus.FAILED,
                outputs={},
                diagnostics=tuple(diagnostics),
            )

        outputs: dict[str, OutputValue] = {}
        axis = tuple(float(v) for v in solution.t)
        for index, param in enumerate(self._schema.state_parameters()):
            name = self._output_names[index]
            values = tuple(float(v) for v in solution.y[index])
            outputs[name] = OutputValue(
                name=name,
                kind="timeseries",
                unit=param.unit,
                values=list(values),
                shape=(len(values),),
                labels=(name,),
                axis=list(axis),
                axis_unit=self._time_unit,
                dtype="float64",
            )

        if self._output_fn is not None:
            try:
                derived = self._output_fn(solution.t, solution.y, numeric_inputs)
            except Exception as exc:
                diagnostics.append(
                    Diagnostic(
                        level="warning",
                        code="output_fn_failed",
                        message=f"derived outputs skipped: {type(exc).__name__}: {exc}",
                    )
                )
            else:
                for name, value in derived.items():
                    if not np.isfinite(value):
                        diagnostics.append(
                            Diagnostic(
                                level="warning",
                                code="non_finite_derived_output",
                                message=f"derived output {name!r} is non-finite and was dropped",
                            )
                        )
                        continue
                    output_spec = next(
                        (o for o in self._schema.outputs if o.name == name), None
                    )
                    outputs[name] = OutputValue(
                        name=name,
                        kind="scalar",
                        unit=output_spec.unit if output_spec else "dimensionless",
                        values=float(value),
                        shape=(),
                        labels=(name,),
                        dtype="float64",
                    )

        return ModelResult(
            status=RunStatus.SUCCEEDED, outputs=outputs, diagnostics=tuple(diagnostics)
        )
