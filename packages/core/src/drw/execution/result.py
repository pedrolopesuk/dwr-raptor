"""Container for the outcome of a whole experiment."""

from __future__ import annotations

from dataclasses import dataclass, field

from drw.numerics.delta import Comparison
from drw.schema.experiment import ExperimentSpec, RunEstimate
from drw.schema.model import ModelRef, ModelSchema
from drw.schema.result import Diagnostic, RunRecord
from drw.uncertainty import UncertaintySummary

__all__ = ["ExperimentResult"]


@dataclass(slots=True)
class ExperimentResult:
    """Every run and comparison produced by one experiment execution."""

    experiment_id: str
    spec: ExperimentSpec
    schema: ModelSchema
    model_ref: ModelRef
    estimate: RunEstimate
    spec_hash: str
    model_hash: str
    isolation: str = "in_process"
    environment: dict[str, object] = field(default_factory=dict)
    runs: list[RunRecord] = field(default_factory=list)
    comparisons: list[Comparison] = field(default_factory=list)
    warnings: tuple[Diagnostic, ...] = ()
    started_at: str | None = None
    finished_at: str | None = None
    uncertainty: UncertaintySummary | None = None

    @property
    def baseline(self) -> RunRecord:
        return self.runs[0]

    @property
    def variants(self) -> list[RunRecord]:
        return self.runs[1:]

    @property
    def succeeded_runs(self) -> list[RunRecord]:
        return [run for run in self.runs if run.succeeded]

    @property
    def failed_runs(self) -> list[RunRecord]:
        return [run for run in self.runs if run.failed]

    def run(self, run_id: str) -> RunRecord:
        for record in self.runs:
            if record.run_id == run_id:
                return record
        raise KeyError(f"no run {run_id!r} in experiment {self.experiment_id!r}")

    def comparisons_for(self, output: str) -> list[Comparison]:
        return [c for c in self.comparisons if c.output == output]
