"""Golden model: mass-spring-damper oscillator.

The linear damped oscillator has a closed-form solution, which makes it the
reference for numerical correctness: the ODE integration is compared against the
analytic trajectory in ``tests/scientific``.

    m x'' + c x' + k x = 0
    x' = v
    v' = -(k/m) x - (c/m) v
"""

from __future__ import annotations

import numpy as np

from drw.numerics.ode import OdeModel
from drw.schema.model import ModelSchema, OutputSpec, ParameterSpec

MODEL_ID = "oscillator"

SCHEMA = ModelSchema(
    model_id=MODEL_ID,
    version="1.0.0",
    description="Linear mass-spring-damper oscillator with a closed-form reference solution.",
    runtime="python/scipy.solve_ivp",
    parameters=(
        ParameterSpec(
            name="m",
            type="float",
            unit="kg",
            description="Mass.",
            nominal=1.0,
            lower=0.1,
            upper=10.0,
            role="input",
            differentiable=True,
        ),
        ParameterSpec(
            name="k",
            type="float",
            unit="N/m",
            description="Spring stiffness.",
            nominal=4.0,
            lower=0.1,
            upper=100.0,
            role="input",
            differentiable=True,
        ),
        ParameterSpec(
            name="c",
            type="float",
            unit="N*s/m",
            description="Viscous damping coefficient.",
            nominal=0.2,
            lower=0.0,
            upper=5.0,
            role="input",
            differentiable=True,
        ),
        ParameterSpec(
            name="x0",
            type="float",
            unit="m",
            description="Initial displacement.",
            nominal=1.0,
            lower=-5.0,
            upper=5.0,
            role="state",
        ),
        ParameterSpec(
            name="v0",
            type="float",
            unit="m/s",
            description="Initial velocity.",
            nominal=0.0,
            lower=-5.0,
            upper=5.0,
            role="state",
        ),
    ),
    outputs=(
        OutputSpec(name="x", kind="timeseries", unit="m", description="Displacement.", axis_unit="s"),
        OutputSpec(name="v", kind="timeseries", unit="m/s", description="Velocity.", axis_unit="s"),
        OutputSpec(name="peak_displacement", kind="scalar", unit="m", description="max |x|."),
    ),
    metadata={
        "reference": "analytic underdamped solution",
        "closed_form": "x(t)=exp(-zeta*omega0*t)*(x0*cos(wd*t)+((v0+zeta*omega0*x0)/wd)*sin(wd*t))",
    },
)


def rhs(t: float, y: np.ndarray, params: dict[str, float]) -> list[float]:
    x, v = y
    m = params["m"]
    return [v, -(params["k"] / m) * x - (params["c"] / m) * v]


def _derived(t: np.ndarray, y: np.ndarray, params: dict[str, float]) -> dict[str, float]:
    return {"peak_displacement": float(np.max(np.abs(y[0])))}


def build(*, solver: str = "auto", rtol: float = 1e-9, atol: float = 1e-12) -> OdeModel:
    return OdeModel(
        SCHEMA,
        rhs,
        t_span=(0.0, 10.0),
        n_points=201,
        output_fn=_derived,
        output_names=("x", "v"),
        solver=solver,
        rtol=rtol,
        atol=atol,
        time_unit="s",
    )


def analytic_displacement(
    t: np.ndarray, *, m: float, k: float, c: float, x0: float, v0: float
) -> np.ndarray:
    """Closed-form displacement for the underdamped/undamped oscillator."""
    omega0 = np.sqrt(k / m)
    zeta = c / (2.0 * np.sqrt(k * m))
    if zeta < 1.0:
        omega_d = omega0 * np.sqrt(1.0 - zeta**2)
        return np.exp(-zeta * omega0 * t) * (
            x0 * np.cos(omega_d * t) + ((v0 + zeta * omega0 * x0) / omega_d) * np.sin(omega_d * t)
        )
    raise ValueError("analytic_displacement only covers the underdamped case (zeta < 1)")
