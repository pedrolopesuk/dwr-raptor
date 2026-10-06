# ADR-0022: Calibration architecture

**Status:** Accepted

## Context

M12A gives DRW an execution-free comparison of a completed run to a dataset
(`evaluate`/`evaluate_run`). M12B answers the next question: *how should DRW
calibrate model parameters against real observations in a scientifically
explicit, reproducible, domain-neutral and fail-closed way?* Calibration is a
search: it must generate candidate parameters, execute a model, compare it to
data, and iterate. The engine already has exactly one execution path (the
`Runner`) and exactly one comparison path (M12A).

## Decision

* **Calibration is a thin orchestration layer**, not a new engine:
  `CalibrationConfig → parameter resolution → optimizer → candidate θ →
  single-run ExperimentSpec → Runner → RunRecord → M12A evaluate_run →
  EvaluationResult → objective oracle → optimizer ↺ → CalibrationResult`.
* **One execution path.** Calibration builds a throwaway single-run
  `ExperimentSpec` per candidate (baseline = θ ∪ fixed, no factors, no analyses)
  and calls `Runner.run`. It never executes a model directly and never creates a
  second subprocess mechanism.
* **One comparison path.** The objective is read **only** from an M12A
  `EvaluationResult` via the objective oracle; residuals, alignment, units,
  uncertainty and metrics are never recomputed.
* **`CalibrationConfig` is separate from `ExperimentSpec`.** Calibration state is
  not embedded into `ExperimentSpec`/`ModelSchema`; the candidate spec is a pure
  execution vehicle.
* **Strictly serial in v1.** Parallel candidate execution is deferred.
* **Bounded and deterministic.** A mandatory `max_evaluations` hard cap and
  `max_wall_seconds`, a per-run timeout from the execution template, and a
  mandatory seed. The loop owns the evaluation counter; a library optimizer cannot
  exceed it.
* **Point estimate only.** No parameter uncertainty, no posteriors, no validation.

## Consequences

* M12B reuses every existing contract and boundary; it adds a new caller of the
  `Runner` and of M12A rather than modifying them.
* The optimizer is decoupled from execution (it sees only a scalar objective),
  so alternative optimizers can be added without touching the engine.
* The result is a reproducible scientific artifact with an explicit scientific
  claim (ADR-0025, ADR-0026).

## Alternatives rejected

A. Embedding calibration in `ExperimentSpec` — mixes a deterministic batch with an
iterative search and breaks the "do not modify `ExperimentSpec`" boundary.
B. A `CalibrationSpec` that is itself a spec — still needs execution; duplicates
execution config. D. Optimizer directly coupled to the `Runner` — bypasses M12A
and forces a second comparison implementation.
