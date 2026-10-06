# ADR-0024: Optimizer selection

**Status:** Accepted

## Context

DRW models are deterministic, bounded, domain-neutral, black-box (often ODEs),
potentially non-smooth, and can fail or time out. Evaluations may be expensive.
Calibration must be deterministic and auditable, and the whole search is bounded
by `max_evaluations`. `scipy` is already a core dependency (`numerics/sampling`
uses `scipy.stats.qmc`), so `scipy.optimize` adds no new dependency.

## Decision

Ship three strategies in v1:

* **Powell** (`scipy.optimize.minimize(method="Powell")`) — the **default**:
  bounded, derivative-free, deterministic, robust for black-box objectives.
* **Differential Evolution** (`scipy.optimize.differential_evolution`) — **opt-in**
  global search, seeded (`seed`), single-worker and `polish=False` (no hidden
  L-BFGS-B), for multi-modal objectives.
* **Random Search** — a deterministic, seeded **baseline/reference** optimizer
  (uniform over the box, exactly `max_evaluations` proposals). Not the default.

The **loop owns the hard evaluation budget**: the objective function raises a
`CalibrationBudgetExceeded` at the cap, so no scipy optimizer can exceed
`max_evaluations`. Optimizer iteration counts are secondary metadata.

Deferred: L-BFGS-B (assumes smoothness), Nelder-Mead (bounds via penalty),
`least_squares` (needs a residual vector — a second objective shape), multi-start
orchestration, grid search (already provided by `ExperimentSpec` factor grids),
surrogate/Bayesian optimisation.

## Consequences

* A failing scipy call is caught and mapped to `optimizer_failure`; a scipy
  non-convergence is reported as `max_iterations`. Neither is a scientific result.
* Deterministic given a seed and the recorded configuration; the SciPy version is
  recorded in provenance.
