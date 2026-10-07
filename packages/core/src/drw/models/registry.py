"""Registry of built-in reference models and compiled (generated) models.

The registry maps a stable ``model_id`` to a builder and its declared schema.
Experiments reference models by id, never by import path. Two sources are merged:

* the **built-in** golden models (specification section 11.1), built from code; and
* **compiled** models produced by :mod:`drw.model_compiler` and stored by
  :mod:`drw.model_store` under the workspace (``DRW_WORKSPACE``), so a model SI
  created is executable by the existing :class:`~drw.execution.runner.Runner`.

A built-in id always wins; a compiled model can never shadow a reference model.
"""

from __future__ import annotations

from collections.abc import Callable

from drw.models import lorenz, oscillator, predator_prey
from drw.numerics.ode import OdeModel
from drw.schema.model import ModelSchema

__all__ = [
    "build_model",
    "compiled_model_schemas",
    "describe_model",
    "is_registered",
    "list_models",
    "model_schemas",
    "registry",
]

registry: dict[str, Callable[..., OdeModel]] = {
    oscillator.MODEL_ID: oscillator.build,
    predator_prey.MODEL_ID: predator_prey.build,
    lorenz.MODEL_ID: lorenz.build,
}


def _compiled_store():
    # Imported lazily so the registry stays importable without a workspace.
    from drw.model_store import default_model_store

    return default_model_store()


def compiled_model_schemas() -> dict[str, ModelSchema]:
    """Schemas of every compiled model in the workspace (best-effort, never raises)."""
    try:
        store = _compiled_store()
        references = store.list()
    except Exception:  # pragma: no cover - a broken workspace must not break listing
        return {}
    schemas: dict[str, ModelSchema] = {}
    for reference in references:
        try:
            schemas[reference.model_id] = store.schema(reference.model_id)
        except Exception:  # pragma: no cover - skip an individual corrupt entry
            continue
    return schemas


def is_registered(model_id: str) -> bool:
    """Whether ``model_id`` resolves to a built-in or a compiled model."""
    if model_id in registry:
        return True
    try:
        return _compiled_store().exists(model_id)
    except Exception:  # pragma: no cover - defensive
        return False


def list_models() -> list[str]:
    """Return every resolvable model id, sorted for stable output."""
    ids = set(registry) | set(compiled_model_schemas())
    return sorted(ids)


def build_model(model_id: str, **kwargs) -> OdeModel:
    """Instantiate a registered or compiled model adapter."""
    builder = registry.get(model_id)
    if builder is not None:
        return builder(**kwargs)
    try:
        store = _compiled_store()
        if store.exists(model_id):
            return store.build(model_id)
    except Exception:  # pragma: no cover - defensive
        pass
    raise KeyError(f"unknown model {model_id!r}; available: {list_models()}")


def model_schemas() -> dict[str, ModelSchema]:
    """Return every resolvable model's schema keyed by model id."""
    schemas = {model_id: builder().describe() for model_id, builder in registry.items()}
    for model_id, schema in compiled_model_schemas().items():
        schemas.setdefault(model_id, schema)
    return schemas


def describe_model(model_id: str) -> ModelSchema:
    return build_model(model_id).describe()
