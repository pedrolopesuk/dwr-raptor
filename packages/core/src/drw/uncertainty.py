"""Descriptive uncertainty summary over an experiment's sampled variant runs.

This activates the ``uncertainty`` analysis method. It aggregates the scalar
outputs that the experiment's **existing** sampling design already produced into
descriptive statistics; it performs **no additional executions** and assumes no
probabilistic model.

What it is: a description of how a scalar output varies across the sampled factor
design (mean, sample standard deviation, min, max and fixed percentiles).

What it is **not**: a probability distribution, a confidence interval, a Bayesian
posterior, or evidence of scientific validity. The parameters are sampled exactly
as the sampler draws them (independently and uniformly over the declared factor
bounds) - no prior is defined.

Quantiles use ``numpy.percentile(..., method="linear")`` (the library default:
linear interpolation between the two nearest order statistics). The method is
recorded in the summary so the numbers can be reproduced.

Exclusions are explicit and counted per output and per reason
(``run_failed`` / ``run_timed_out`` / ``output_missing`` / ``non_finite``); the
summaries never substitute zero for a missing or failed value.

Count semantics: ``requested_variants`` is a per-run count; the summary-level
``valid_output_samples`` / ``excluded_output_samples`` are totals across the
declared scalar outputs (output-samples) and may exceed ``requested_variants`` when
a model declares more than one scalar output - the per-output counts are
authoritative. A model with no scalar outputs yields an empty summary with an
explicit note.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import numpy as np
from pydantic import BaseModel, ConfigDict, Field

from drw.schema.experiment import ExperimentSpec
from drw.schema.model import ModelSchema
from drw.schema.result import RunRecord

__all__ = [
    "GRID_NOTE",
    "NO_SCALAR_NOTE",
    "QUANTILES",
    "QUANTILE_METHOD",
    "OutputUncertainty",
    "UncertaintyError",
    "UncertaintySummary",
    "compute_uncertainty",
    "uncertainty_for_experiment",
]

UNCERTAINTY_SCHEMA_VERSION = "1.0.0"

#: Fixed percentiles reported for every scalar output (5th, 50th, 95th).
QUANTILES: tuple[float, ...] = (5.0, 50.0, 95.0)

#: The quantile algorithm, recorded so the numbers are reproducible.
QUANTILE_METHOD = "linear"

GRID_NOTE = (
    "grid design: these are descriptive summaries over the grid nodes, not a "
    "sampling distribution"
)

NO_SCALAR_NOTE = "no scalar outputs are declared: there is nothing to summarize"

#: ``requested_variants`` is a per-run count; ``valid_output_samples`` /
#: ``excluded_output_samples`` are totals summed across the declared scalar
#: outputs ("output-samples") and can exceed ``requested_variants`` when a model
#: declares more than one scalar output. The per-output counts are authoritative.


class UncertaintyError(ValueError):
    """Raised when an uncertainty summary cannot be produced for an experiment."""


class OutputUncertainty(BaseModel):
    """Descriptive statistics for one scalar output over the sampled variants.

    Counts are per output: ``requested_variants`` is the number of variant runs,
    ``valid_samples`` the number of finite values used for *this* output, and
    ``excluded_samples`` the rest (broken down in ``exclusions``).
    """

    model_config = ConfigDict(extra="forbid")

    output: str
    unit: str
    requested_variants: int
    valid_samples: int
    excluded_samples: int
    exclusions: dict[str, int] = Field(default_factory=dict)
    sufficient: bool
    mean: float | None = None
    std: float | None = None
    minimum: float | None = None
    maximum: float | None = None
    p05: float | None = None
    p50: float | None = None
    p95: float | None = None
    note: str | None = None


class UncertaintySummary(BaseModel):
    """A descriptive-only summary of the sampled design's scalar outputs.

    ``requested_variants`` counts the sampled variant runs (a per-run quantity).
    ``valid_output_samples`` and ``excluded_output_samples`` are **totals summed
    across the declared scalar outputs** (i.e. across output-samples), so with more
    than one scalar output they can exceed ``requested_variants``; the per-output
    ``valid_samples`` / ``excluded_samples`` are authoritative.
    """

    model_config = ConfigDict(extra="forbid")

    schema_version: str = UNCERTAINTY_SCHEMA_VERSION
    sampling_method: str
    seed: int
    requested_variants: int
    valid_output_samples: int
    excluded_output_samples: int
    quantiles: list[float] = Field(default_factory=lambda: list(QUANTILES))
    quantile_method: str = QUANTILE_METHOD
    outputs: list[OutputUncertainty]
    note: str | None = None
    descriptive_only: bool = True


def _summarise_output(
    name: str, unit: str, requested: int, values: list[float], exclusions: dict[str, int]
) -> OutputUncertainty:
    count = len(values)
    excluded = requested - count
    if count == 0:
        return OutputUncertainty(
            output=name,
            unit=unit,
            requested_variants=requested,
            valid_samples=0,
            excluded_samples=excluded,
            exclusions=exclusions,
            sufficient=False,
            note="no valid samples: statistics are undefined",
        )

    array = np.asarray(values, dtype=float)
    percentiles = np.percentile(array, QUANTILES, method=QUANTILE_METHOD)
    std = float(np.std(array, ddof=1)) if count >= 2 else None
    note = None if count >= 2 else "fewer than two valid samples: standard deviation is undefined"
    return OutputUncertainty(
        output=name,
        unit=unit,
        requested_variants=requested,
        valid_samples=count,
        excluded_samples=excluded,
        exclusions=exclusions,
        sufficient=count >= 2,
        mean=float(array.mean()),
        std=std,
        minimum=float(array.min()),
        maximum=float(array.max()),
        p05=float(percentiles[0]),
        p50=float(percentiles[1]),
        p95=float(percentiles[2]),
        note=note,
    )


def compute_uncertainty(
    schema: ModelSchema,
    spec: ExperimentSpec,
    variant_runs: Sequence[RunRecord],
) -> UncertaintySummary:
    """Aggregate the scalar outputs of ``variant_runs`` into descriptive statistics.

    ``variant_runs`` are the sampled runs (the baseline reference is excluded).
    Failed runs, missing outputs and non-finite values are excluded and counted;
    nothing is fabricated.
    """
    requested = len(variant_runs)
    scalar_outputs = [output for output in schema.outputs if output.kind == "scalar"]
    outputs: list[OutputUncertainty] = []
    for output in scalar_outputs:
        values: list[float] = []
        exclusions: dict[str, int] = {}
        for run in variant_runs:
            if not run.succeeded:
                reason = "run_timed_out" if run.timed_out else "run_failed"
                exclusions[reason] = exclusions.get(reason, 0) + 1
                continue
            if output.name not in run.metrics:
                exclusions["output_missing"] = exclusions.get("output_missing", 0) + 1
                continue
            value = float(run.metrics[output.name])
            if not np.isfinite(value):
                exclusions["non_finite"] = exclusions.get("non_finite", 0) + 1
                continue
            values.append(value)
        outputs.append(_summarise_output(output.name, output.unit, requested, values, exclusions))

    notes: list[str] = []
    if not scalar_outputs:
        notes.append(NO_SCALAR_NOTE)
    if spec.sampling.method == "grid":
        notes.append(GRID_NOTE)

    return UncertaintySummary(
        sampling_method=spec.sampling.method,
        seed=spec.sampling.seed,
        requested_variants=requested,
        valid_output_samples=sum(output.valid_samples for output in outputs),
        excluded_output_samples=sum(output.excluded_samples for output in outputs),
        quantiles=list(QUANTILES),
        quantile_method=QUANTILE_METHOD,
        outputs=outputs,
        note="; ".join(notes) or None,
    )


def uncertainty_for_experiment(experiment_id: str, store: Any) -> UncertaintySummary:
    """Compute the uncertainty summary for a stored experiment (read-only).

    Works from the stored runs without re-executing anything, so it is available
    for any experiment whose sampling design produced variant runs.
    """
    from drw.models.registry import build_model
    from drw.schema.experiment import ExperimentSpec as _ExperimentSpec
    from drw.schema.result import RunRecord as _RunRecord

    loaded = store.load(experiment_id)
    spec = _ExperimentSpec.model_validate(loaded["spec"])
    schema = build_model(spec.model_ref.model_id).describe()
    runs_raw = loaded["results"].get("runs") or []
    if not runs_raw:
        raise UncertaintyError("experiment has no runs to summarize")
    runs = [_RunRecord.model_validate(run) for run in runs_raw]
    return compute_uncertainty(schema, spec, runs[1:])
