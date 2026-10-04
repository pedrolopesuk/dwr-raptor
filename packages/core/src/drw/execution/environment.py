"""Environment fingerprinting for reproducibility (specification section 10.6).

A reproducible run records the versions it was produced with. This fingerprint is
embedded in every run and in the evidence manifest so two researchers can compare
environments directly.
"""

from __future__ import annotations

import platform
import sys
from importlib import metadata
from typing import Any

import numpy
import pydantic
import scipy

from drw.schema.serialization import content_hash

__all__ = ["environment_fingerprint", "fingerprint_hash"]


def _distribution_version(name: str) -> str:
    try:
        return metadata.version(name)
    except metadata.PackageNotFoundError:  # pragma: no cover - editable/source installs
        return "unknown"


def environment_fingerprint() -> dict[str, Any]:
    """Return a deterministic description of the execution environment."""
    return {
        "platform": platform.platform(),
        "machine": platform.machine(),
        "processor": platform.processor() or "unknown",
        "python_version": platform.python_version(),
        "python_implementation": platform.python_implementation(),
        "python_executable": sys.executable.replace("\\", "/"),
        "numpy": numpy.__version__,
        "scipy": scipy.__version__,
        "pydantic": pydantic.VERSION,
        "drw_core": _distribution_version("drw-core"),
    }


#: Keys that describe *where* the interpreter lives rather than *what* is
#: installed. They are kept in the fingerprint for diagnosis but excluded from
#: the hash, so two machines with identical package versions agree.
_HASH_EXCLUDED = frozenset({"python_executable"})


def fingerprint_hash(fingerprint: dict[str, Any]) -> str:
    """Stable hash of the *semantic* environment (versions, platform, CPU)."""
    semantic = {key: value for key, value in fingerprint.items() if key not in _HASH_EXCLUDED}
    return content_hash(semantic)
