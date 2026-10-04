"""Golden model: Lotka-Volterra predator-prey system.

The dimensionless quantity

    V = delta*x - gamma*ln(x) + beta*y - alpha*ln(y)

is conserved along every trajectory, which provides an analytic invariant for the
numerical correctness tests (the integrator must preserve it to tolerance).

    x' = alpha*x - beta*x*y
    y' = delta*x*y - gamma*y
"""

from __future__ import annotations

import numpy as np

from drw.numerics.ode import OdeModel
from drw.schema.model import ModelSchema, OutputSpec, ParameterSpec

MODEL_ID = "predator-prey"

SCHEMA = ModelSchema(
    model_id=MODEL_ID,
    version="1.0.0",
    description="Lotka-Volterra predator-prey dynamics with a conserved quantity.",
    runtime="python/scipy.solve_ivp",
    parameters=(
        ParameterSpec(
            name="alpha",
            type="float",
            unit="1/s",
            description="Prey intrinsic growth rate.",
            nominal=1.1,
            lower=0.1,
            upper=3.0,
            role="input",
            differentiable=True,
        ),
        ParameterSpec(
            name="beta",
            type="float",
            unit="1/(count*s)",
            description="Predation rate.",
            nominal=0.4,
            lower=0.05,
            upper=2.0,
            role="input",
            differentiable=True,
        ),
        ParameterSpec(
            name="delta",
            type="float",
            unit="1/(count*s)",
            description="Predator reproduction per prey consumed.",
            nominal=0.1,
            lower=0.01,
            upper=1.0,
            role="input",
            differentiable=True,
        ),
        ParameterSpec(
            name="gamma",
            type="float",
            unit="1/s",
            description="Predator death rate.",
            nominal=0.4,
            lower=0.05,
            upper=2.0,
            role="input",
            differentiable=True,
        ),
        ParameterSpec(
            name="prey0",
            type="float",
            unit="count",
            description="Initial prey population.",
            nominal=10.0,
            lower=0.1,
            upper=100.0,
            role="state",
        ),
        ParameterSpec(
            name="predator0",
            type="float",
            unit="count",
            description="Initial predator population.",
            nominal=5.0,
            lower=0.1,
            upper=100.0,
            role="state",
        ),
    ),
    outputs=(
        OutputSpec(
            name="prey", kind="timeseries", unit="count", description="Prey population.", axis_unit="s"
        ),
        OutputSpec(
            name="predator",
            kind="timeseries",
            unit="count",
            description="Predator population.",
            axis_unit="s",
        ),
        OutputSpec(name="peak_prey", kind="scalar", unit="count", description="max prey."),
    ),
    metadata={
        "invariant": "V = delta*x - gamma*ln(x) + beta*y - alpha*ln(y)",
        "conserved_quantity": True,
    },
)


def rhs(t: float, y: np.ndarray, params: dict[str, float]) -> list[float]:
    prey, predator = y
    alpha = params["alpha"]
    beta = params["beta"]
    delta = params["delta"]
    gamma = params["gamma"]
    return [alpha * prey - beta * prey * predator, delta * prey * predator - gamma * predator]


def conserved_quantity(y: np.ndarray, params: dict[str, float]) -> float:
    """The Lotka-Volterra first integral, constant along a trajectory."""
    prey, predator = float(y[0]), float(y[1])
    alpha = params["alpha"]
    beta = params["beta"]
    delta = params["delta"]
    gamma = params["gamma"]
    return delta * prey - gamma * np.log(prey) + beta * predator - alpha * np.log(predator)


def _derived(t: np.ndarray, y: np.ndarray, params: dict[str, float]) -> dict[str, float]:
    return {"peak_prey": float(np.max(y[0]))}


def build(*, solver: str = "auto", rtol: float = 1e-9, atol: float = 1e-12) -> OdeModel:
    return OdeModel(
        SCHEMA,
        rhs,
        t_span=(0.0, 15.0),
        n_points=301,
        output_fn=_derived,
        output_names=("prey", "predator"),
        solver=solver,
        rtol=rtol,
        atol=atol,
        time_unit="s",
    )
