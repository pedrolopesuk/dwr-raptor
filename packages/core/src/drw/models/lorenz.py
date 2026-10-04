"""Golden model: Lorenz system.

A chaotic system used to demonstrate two properties that matter for
reproducibility:

* for a fixed configuration the integration is deterministic, and
* two nearby initial conditions diverge (perturbation growth).
"""

from __future__ import annotations

import numpy as np

from drw.numerics.ode import OdeModel
from drw.schema.model import ModelSchema, OutputSpec, ParameterSpec

MODEL_ID = "lorenz"

SCHEMA = ModelSchema(
    model_id=MODEL_ID,
    version="1.0.0",
    description="Lorenz (1963) chaotic attractor, dimensionless.",
    runtime="python/scipy.solve_ivp",
    parameters=(
        ParameterSpec(
            name="sigma",
            type="float",
            unit="dimensionless",
            description="Prandtl number.",
            nominal=10.0,
            lower=1.0,
            upper=20.0,
            role="input",
            differentiable=True,
        ),
        ParameterSpec(
            name="rho",
            type="float",
            unit="dimensionless",
            description="Rayleigh number.",
            nominal=28.0,
            lower=5.0,
            upper=50.0,
            role="input",
            differentiable=True,
        ),
        ParameterSpec(
            name="beta",
            type="float",
            unit="dimensionless",
            description="Geometric factor.",
            nominal=8.0 / 3.0,
            lower=0.5,
            upper=6.0,
            role="input",
            differentiable=True,
        ),
        ParameterSpec(
            name="x0",
            type="float",
            unit="dimensionless",
            description="Initial x.",
            nominal=1.0,
            lower=-20.0,
            upper=20.0,
            role="state",
        ),
        ParameterSpec(
            name="y0",
            type="float",
            unit="dimensionless",
            description="Initial y.",
            nominal=1.0,
            lower=-20.0,
            upper=20.0,
            role="state",
        ),
        ParameterSpec(
            name="z0",
            type="float",
            unit="dimensionless",
            description="Initial z.",
            nominal=1.0,
            lower=-20.0,
            upper=20.0,
            role="state",
        ),
    ),
    outputs=(
        OutputSpec(name="x", kind="timeseries", unit="dimensionless", description="State x.", axis_unit="s"),
        OutputSpec(name="y", kind="timeseries", unit="dimensionless", description="State y.", axis_unit="s"),
        OutputSpec(name="z", kind="timeseries", unit="dimensionless", description="State z.", axis_unit="s"),
        OutputSpec(name="max_abs_x", kind="scalar", unit="dimensionless", description="max |x|."),
    ),
    metadata={"chaotic": True, "classic_parameters": {"sigma": 10.0, "rho": 28.0, "beta": 8.0 / 3.0}},
)


def rhs(t: float, y: np.ndarray, params: dict[str, float]) -> list[float]:
    x, yy, z = y
    sigma = params["sigma"]
    rho = params["rho"]
    beta = params["beta"]
    return [sigma * (yy - x), x * (rho - z) - yy, x * yy - beta * z]


def _derived(t: np.ndarray, y: np.ndarray, params: dict[str, float]) -> dict[str, float]:
    return {"max_abs_x": float(np.max(np.abs(y[0])))}


def build(*, solver: str = "auto", rtol: float = 1e-9, atol: float = 1e-12) -> OdeModel:
    return OdeModel(
        SCHEMA,
        rhs,
        t_span=(0.0, 20.0),
        n_points=401,
        output_fn=_derived,
        output_names=("x", "y", "z"),
        solver=solver,
        rtol=rtol,
        atol=atol,
        time_unit="s",
    )
