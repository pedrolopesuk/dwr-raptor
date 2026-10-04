"""Run context handed to a model adapter for every execution.

Mirrors specification section 10.2. The context carries everything the adapter
needs to be reproducible (identity, seed, workdir) plus the execution controls
that come from the :class:`~drw.schema.experiment.ExecutionSpec` (solver choice,
tolerances, timeout).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

__all__ = ["RunContext"]


@dataclass(slots=True)
class RunContext:
    """Per-run execution context."""

    run_id: str
    experiment_id: str
    seed: int | None = None
    workdir: Path | None = None
    timeout_s: float = 60.0
    solver: Literal["auto", "explicit", "stiff"] = "auto"
    rtol: float = 1e-8
    atol: float = 1e-10
    environment_fingerprint: dict[str, Any] = field(default_factory=dict)

    def child(self, **overrides: Any) -> RunContext:
        """Return a copy of this context with selected fields replaced."""
        data = {
            "run_id": self.run_id,
            "experiment_id": self.experiment_id,
            "seed": self.seed,
            "workdir": self.workdir,
            "timeout_s": self.timeout_s,
            "solver": self.solver,
            "rtol": self.rtol,
            "atol": self.atol,
            "environment_fingerprint": self.environment_fingerprint,
        }
        data.update(overrides)
        return RunContext(**data)
