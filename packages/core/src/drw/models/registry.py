"""Registry of built-in reference models.

The MVP ships three golden models (specification section 11.1). The registry maps
a stable ``model_id`` to a builder and its declared schema; experiments reference
models by id, never by import path.
"""

from __future__ import annotations

from collections.abc import Callable

from drw.models import lorenz, oscillator, predator_prey
from drw.numerics.ode import OdeModel
from drw.schema.model import ModelSchema

__all__ = ["build_model", "describe_model", "list_models", "model_schemas", "registry"]

registry: dict[str, Callable[..., OdeModel]] = {
    oscillator.MODEL_ID: oscillator.build,
    predator_prey.MODEL_ID: predator_prey.build,
    lorenz.MODEL_ID: lorenz.build,
}


def list_models() -> list[str]:
    """Return the registered model ids, sorted for stable output."""
    return sorted(registry)


def build_model(model_id: str, **kwargs) -> OdeModel:
    """Instantiate a registered model adapter."""
    try:
        builder = registry[model_id]
    except KeyError as exc:
        raise KeyError(f"unknown model {model_id!r}; available: {list_models()}") from exc
    return builder(**kwargs)


def model_schemas() -> dict[str, ModelSchema]:
    """Return every registered model's schema keyed by model id."""
    return {model_id: builder().describe() for model_id, builder in registry.items()}


def describe_model(model_id: str) -> ModelSchema:
    return build_model(model_id).describe()
