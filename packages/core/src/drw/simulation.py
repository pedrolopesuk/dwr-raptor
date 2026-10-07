"""Simulate observations from a model and mark them explicitly synthetic.

Simulation executes the **existing** :class:`~drw.execution.runner.Runner` with a
single deterministic run (no factors, no comparisons) built from a
:class:`~drw.schema.simulation.SimulationSpec`, then turns the run's time-series
outputs into an :class:`~drw.schema.observation.ObservationSet` and a
content-addressed dataset whose provenance is ``source_kind="synthetic"``.

This module performs no empirical claim: the result is a consequence of a model and
its assumptions. The dataset it produces is refused by the empirical guards used in
evaluation, calibration and validation (:func:`drw.schema.simulation.assert_empirical`).
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from drw.observations import build_dataset
from drw.schema.experiment import ExecutionSpec, ExperimentSpec, SamplingSpec
from drw.schema.model import ModelRef, ModelSchema
from drw.schema.observation import Dataset, DatasetRef, ObservationSet, Variable
from drw.schema.result import Diagnostic, RunRecord
from drw.schema.simulation import (
    SimulationProvenance,
    SimulationResult,
    SimulationSpec,
    synthetic_provenance,
)

__all__ = [
    "PreparedSimulation",
    "SimulationError",
    "SimulationOutcome",
    "default_simulation_config",
    "prepare_simulation",
    "simulate",
    "validate_simulation",
]


class SimulationError(ValueError):
    """A simulation request that cannot be executed as specified."""

    def __init__(
        self, code: str, message: str, *, diagnostics: Sequence[Diagnostic] = ()
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.diagnostics = tuple(diagnostics)


@dataclass(slots=True)
class PreparedSimulation:
    """A validated simulation ready to run (no execution performed yet)."""

    model_id: str
    schema: ModelSchema
    adapter: Any
    inputs: dict[str, float]
    outputs: tuple[str, ...]
    experiment: ExperimentSpec
    diagnostics: tuple[Diagnostic, ...] = ()


@dataclass(slots=True)
class SimulationOutcome:
    """The result of a simulation, its synthetic dataset and the underlying run."""

    result: SimulationResult
    dataset: Dataset
    dataset_ref: DatasetRef
    run: RunRecord


def _now() -> str:
    return datetime.now(UTC).isoformat()


def default_simulation_config(model_id: str) -> Any:
    """A :class:`SimulationConfig` matching a model's own integration window.

    The compiler bakes the integration window into the model, so a simulation must
    use the same window (a mismatch fails closed). This helper reads the window from
    the model so a caller can build a valid specification without guessing.
    """
    from drw.models.registry import build_model
    from drw.schema.simulation import SimulationConfig

    grid = build_model(model_id).evaluation_grid()
    return SimulationConfig(
        t_span=(float(grid[0]), float(grid[-1])), n_points=len(grid)
    )


def _model_window(adapter: Any) -> tuple[tuple[float, float], int]:
    grid = adapter.evaluation_grid()
    return (float(grid[0]), float(grid[-1])), len(grid)


def _resolve_inputs(spec: SimulationSpec, schema: ModelSchema) -> dict[str, float]:
    known = {p.name for p in schema.parameters}
    for name in (*spec.parameters, *spec.initial_conditions):
        if name not in known:
            raise SimulationError(
                "unknown_parameter",
                f"model {schema.model_id!r} has no parameter {name!r}",
            )
    inputs: dict[str, float] = {}
    for param in schema.parameters:
        if param.role == "state":
            value = spec.initial_conditions.get(param.name, param.nominal)
            source = "initial condition"
        else:
            value = spec.parameters.get(param.name, param.nominal)
            source = "parameter"
        if value is None:
            raise SimulationError(
                "missing_parameter",
                f"no value for {param.name!r}: provide it in the simulation "
                f"{'initial_conditions' if param.role == 'state' else 'parameters'} "
                "or declare a nominal value",
            )
        numeric = float(value)
        if not math.isfinite(numeric):
            raise SimulationError(
                "non_finite_value", f"{param.name!r} ({source}) must be finite"
            )
        if param.lower is not None and numeric < param.lower:
            raise SimulationError(
                "value_out_of_bounds",
                f"{param.name!r}={numeric} is below the declared lower bound {param.lower}",
            )
        if param.upper is not None and numeric > param.upper:
            raise SimulationError(
                "value_out_of_bounds",
                f"{param.name!r}={numeric} is above the declared upper bound {param.upper}",
            )
        inputs[param.name] = numeric
    return inputs


def _select_outputs(
    spec: SimulationSpec, schema: ModelSchema
) -> tuple[tuple[str, ...], tuple[Diagnostic, ...]]:
    by_name = {output.name: output for output in schema.outputs}
    diagnostics: list[Diagnostic] = []
    if spec.outputs:
        selected: list[str] = []
        for name in spec.outputs:
            output = by_name.get(name)
            if output is None:
                raise SimulationError(
                    "unknown_output",
                    f"model {schema.model_id!r} has no output {name!r}",
                )
            if output.kind != "timeseries":
                raise SimulationError(
                    "unsupported_output_kind",
                    f"output {name!r} is {output.kind!r}; only time-series outputs can be "
                    "stored as a synthetic dataset",
                )
            selected.append(name)
        return tuple(selected), tuple(diagnostics)

    timeseries = tuple(o.name for o in schema.outputs if o.kind == "timeseries")
    if not timeseries:
        raise SimulationError(
            "no_observable_outputs",
            "the model declares no time-series output, so no synthetic dataset can be built",
        )
    scalars = [o.name for o in schema.outputs if o.kind == "scalar"]
    if scalars:
        diagnostics.append(
            Diagnostic(
                level="warning",
                code="scalar_outputs_excluded",
                message=(
                    f"scalar output(s) {scalars} are not included in the synthetic dataset; "
                    "list 'outputs' explicitly to select observable time-series outputs"
                ),
            )
        )
    return timeseries, tuple(diagnostics)


def _observation_set(
    run: RunRecord, outputs: Sequence[str], schema: ModelSchema
) -> ObservationSet:
    if run.result is None:  # pragma: no cover - guarded by the caller
        raise SimulationError("simulation_failed", "the simulation produced no result")
    first = run.result.output(outputs[0])
    axis = list(first.axis or [])
    if len(axis) < 2:
        raise SimulationError(
            "no_observation_axis", f"output {outputs[0]!r} has no usable time axis"
        )
    axis_unit = first.axis_unit or "s"
    variables: list[Variable] = [
        Variable(
            name="time",
            kind="float",
            role="coordinate",
            unit=axis_unit,
            description="Simulation time coordinate.",
        )
    ]
    columns: dict[str, list[Any]] = {"time": [float(value) for value in axis]}
    for name in outputs:
        output = run.result.output(name)
        values = [float(value) for value in output.values]
        if len(values) != len(axis):
            raise SimulationError(
                "shape_mismatch",
                f"output {name!r} has {len(values)} points but the axis has {len(axis)}",
            )
        if any(not math.isfinite(value) for value in values):
            raise SimulationError(
                "non_finite_output", f"output {name!r} produced non-finite values"
            )
        variables.append(
            Variable(
                name=name,
                kind="float",
                role="measurement",
                unit=output.unit or "dimensionless",
                depends_on=("time",),
                description=f"Simulated {name} for model {schema.model_id!r}.",
            )
        )
        columns[name] = values
    return ObservationSet(
        coordinates=("time",), variables=tuple(variables), columns=columns
    )


def prepare_simulation(
    spec: SimulationSpec, *, model_id: str | None = None
) -> PreparedSimulation:
    """Validate a simulation and build its single-run experiment. Does not execute.

    Fails closed for an unknown model, a hash mismatch, a window mismatch, a missing
    or out-of-bounds parameter, or a non-time-series output.
    """
    from drw.models.registry import build_model

    resolved_id = model_id or spec.model_ref.model_id
    if spec.model_ref.model_id != resolved_id:
        raise SimulationError(
            "model_mismatch",
            f"simulation references {spec.model_ref.model_id!r} but the model is "
            f"{resolved_id!r}",
        )
    try:
        adapter = build_model(resolved_id)
    except KeyError as exc:
        raise SimulationError("unknown_model", str(exc).strip("'")) from exc
    schema = adapter.describe()

    if spec.model_hash and spec.model_hash != schema.content_hash():
        raise SimulationError(
            "model_hash_mismatch",
            f"the model hash {spec.model_hash[:12]} does not match the current model "
            f"{schema.content_hash()[:12]}; the model changed since the simulation was "
            "specified",
        )

    model_window, model_points = _model_window(adapter)
    requested = (float(spec.config.t_span[0]), float(spec.config.t_span[1]))
    if not (
        math.isclose(requested[0], model_window[0], rel_tol=0.0, abs_tol=1e-12)
        and math.isclose(requested[1], model_window[1], rel_tol=0.0, abs_tol=1e-12)
        and spec.config.n_points == model_points
    ):
        raise SimulationError(
            "simulation_window_mismatch",
            f"the simulation window {list(requested)}/{spec.config.n_points} does not match "
            f"the model's integration window {list(model_window)}/{model_points}; the model "
            "defines its own window",
        )

    inputs = _resolve_inputs(spec, schema)
    outputs, output_diagnostics = _select_outputs(spec, schema)

    experiment = ExperimentSpec(
        name=f"simulation:{resolved_id}",
        hypothesis=(
            f"Simulate {resolved_id} under the specified parameters and assumptions."
        ),
        model_ref=ModelRef(model_id=resolved_id, version=schema.version),
        baseline=inputs,
        factors=(),
        outputs=outputs,
        sampling=SamplingSpec(method="grid"),
        analyses=(),
        execution=ExecutionSpec(
            solver=spec.config.solver, timeout_s=spec.config.timeout_s
        ),
    )
    return PreparedSimulation(
        model_id=resolved_id,
        schema=schema,
        adapter=adapter,
        inputs=inputs,
        outputs=outputs,
        experiment=experiment,
        diagnostics=output_diagnostics,
    )


def validate_simulation(
    spec: SimulationSpec, *, model_id: str | None = None
) -> tuple[Diagnostic, ...]:
    """Validate a simulation without executing it (structured diagnostics)."""
    try:
        prepare_simulation(spec, model_id=model_id)
    except SimulationError as exc:
        return (Diagnostic(level="error", code=exc.code, message=exc.message),)
    return ()


def simulate(
    spec: SimulationSpec,
    *,
    runner: Any | None = None,
    model_id: str | None = None,
    generated_at: str | None = None,
) -> SimulationOutcome:
    """Run a simulation through the Runner and build an explicitly synthetic dataset.

    The observation values and the ``simulation_hash`` (the specification identity)
    are deterministic for a deterministic model and identical specification. Pass
    ``generated_at`` to make the dataset artifact itself fully reproducible (the
    provenance timestamp is otherwise the wall clock, matching DRW's identity model
    where the scientific identity excludes provenance).
    """
    from drw.execution.runner import Runner

    prepared = prepare_simulation(spec, model_id=model_id)
    active_runner = runner if runner is not None else Runner()
    experiment_result = active_runner.run(prepared.experiment)
    run = experiment_result.baseline
    if not run.succeeded or run.result is None:
        raise SimulationError(
            "simulation_failed",
            run.error or "the simulation run did not succeed",
            diagnostics=tuple(run.diagnostics),
        )

    observation_set = _observation_set(run, prepared.outputs, prepared.schema)
    imported_at = generated_at or _now()
    simulation_hash = spec.content_hash()
    provenance = synthetic_provenance(
        source_model_id=prepared.model_id,
        source_model_hash=prepared.schema.content_hash(),
        imported_at=imported_at,
        parameters=dict(spec.parameters),
        seed=spec.config.seed,
        scenario=spec.scenario,
        simulation_hash=simulation_hash,
        notes=spec.notes
        or "Simulated observations: consequences of a model and its assumptions.",
    )
    dataset = build_dataset(
        name=spec.scenario or f"simulation of {prepared.model_id}",
        observation_set=observation_set,
        provenance=provenance,
        description=(
            f"Synthetic observations generated by simulating {prepared.model_id}. "
            "Not empirical."
        ),
        labels={"synthetic": "true", "model_id": prepared.model_id},
    )

    diagnostics = (*prepared.diagnostics, *run.diagnostics)
    result = SimulationResult(
        simulation_hash=simulation_hash,
        spec=spec,
        run_id=run.run_id,
        observation_set=observation_set,
        dataset_ref=dataset.ref(),
        provenance=SimulationProvenance(
            source_model_id=prepared.model_id,
            source_model_hash=prepared.schema.content_hash(),
            parameters=dict(spec.parameters),
            initial_conditions=dict(spec.initial_conditions),
            scenario=spec.scenario,
            seed=spec.config.seed,
            generated_at=imported_at,
            notes="Consequences of a model under the specified assumptions; not empirical.",
        ),
        diagnostics=tuple(diagnostics),
    )
    return SimulationOutcome(
        result=result, dataset=dataset, dataset_ref=dataset.ref(), run=run
    )
