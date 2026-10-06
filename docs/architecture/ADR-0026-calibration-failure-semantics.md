# ADR-0026: Calibration failure semantics

**Status:** Accepted

## Context

Model evaluations can fail, time out, or produce no usable comparison, and an
optimizer needs a finite scalar. Turning a scientific failure into an arbitrary
numeric penalty would silently fabricate an objective value and bias the search.

## Decision

* **Reject and record (default).** A candidate is **invalid** if any of: the
  parameter vector is non-finite or out of bounds; the candidate spec fails
  validation; the run `FAILED`/timed out; the evaluation fails closed
  (`ok=False`, including incompatible units, invalid mapping, missing output,
  `no_usable_observations`); or the selected metric is `null`/non-finite.
* An invalid candidate **stores `objective = null`** with an explicit `failure`
  code (`invalid_parameter_state`, `validation_error`, `run_failed`,
  `run_timed_out`, `output_missing`, `evaluation_failed`, `no_usable_observations`,
  `incompatible_units`, `invalid_mapping`, `objective_undefined`,
  `non_finite_objective`, `pair_not_found`). Every candidate remains visible in the
  bounded history.
* **`+inf` is an interface sentinel only.** When a scipy optimizer requires a
  finite scalar, `None → +inf` **inside the optimizer adapter** only. The stored
  and displayed objective is always `null`; the sentinel is disclosed as
  `objective.invalid_objective_sentinel = "+inf"`. It is never a scientific value.
* **No numeric penalty mode** in v1. If ever added it must use an explicit,
  user-supplied constant with documented semantics.
* **No fabricated best.** If every candidate is invalid → `status="failed"`,
  `best=null`.
* **Budget exhaustion with a valid candidate** → `status="budget_exhausted"`,
  `converged=false`, `best=best-so-far`, with the caveat that it is not converged.
* **Optimizer convergence** → `status="converged"`, `stop_reason="optimizer_converged"`,
  `converged=true` — and this is **not** statistical certainty (ADR-0027).
* A scipy call that raises → `optimizer_failure`; a scipy non-convergence →
  `max_iterations`; either yields `status="not_converged"` when a valid candidate
  exists, or `"failed"` when none does.

## Consequences

Failures stay scientifically honest and are auditable per candidate; the search is
never silently steered by invented penalty values.
