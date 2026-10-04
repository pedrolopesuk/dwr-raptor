"""Loading and saving DRW documents (YAML or JSON).

YAML is the human-authored format for experiment specifications; JSON is the
machine format used inside evidence packages. Both round-trip through the same
Pydantic models, so a file that loads is guaranteed to satisfy the schema.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml

from drw.schema.experiment import ExperimentSpec
from drw.schema.serialization import dumps_pretty

__all__ = [
    "dump_experiment_spec",
    "load_document",
    "load_experiment_spec",
    "write_json",
]


def load_document(path: str | Path) -> Any:
    """Load a YAML or JSON document from ``path``."""
    text = Path(path).read_text(encoding="utf-8")
    suffix = Path(path).suffix.lower()
    if suffix == ".json":
        return json.loads(text)
    # .yaml / .yml / anything else is treated as YAML (a superset of JSON).
    return yaml.safe_load(text)


def load_experiment_spec(path: str | Path) -> ExperimentSpec:
    """Load and validate an :class:`ExperimentSpec` from disk."""
    return ExperimentSpec.model_validate(load_document(path))


def dump_experiment_spec(spec: ExperimentSpec, path: str | Path) -> Path:
    """Write ``spec`` to ``path`` as YAML or JSON based on the file suffix."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.suffix.lower() == ".json":
        target.write_text(dumps_pretty(spec) + "\n", encoding="utf-8")
    else:
        target.write_text(
            yaml.safe_dump(json.loads(dumps_pretty(spec)), sort_keys=False),
            encoding="utf-8",
        )
    return target


def write_json(obj: Any, path: str | Path) -> Path:
    """Write ``obj`` as canonical, pretty JSON and return the path."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(dumps_pretty(obj) + "\n", encoding="utf-8")
    return target
