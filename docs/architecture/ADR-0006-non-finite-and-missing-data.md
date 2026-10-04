# ADR-0006: Non-finite values and missing data are explicit, never silent

**Status:** Accepted

## Context

`scipy.integrate.solve_ivp` can return `success=True` while carrying `NaN`/`Inf`
in the solution (for example after an overflow the error controller did not
reject). Milestone 1 wrote those values into outputs and reported the run as
`SUCCEEDED`. Comparisons then propagated `NaN` into `mae`, `max_abs_delta`,
`correlation`, etc., producing metrics that were silently `NaN` with no warning
about *why*.

The specification requires the opposite: "Never compute a relative delta against
a denominator close to zero without flagging it" (section 5.7), and the numerical
checklist explicitly calls out NaN/Inf (section 10.6).

## Decision

**Runs.** After integration, if any solution value is non-finite, the run is
`FAILED` with a `non_finite_output` diagnostic naming the state index and grid
step, and **no outputs are returned**. Invariant: *a run is `SUCCEEDED` only when
every output value is finite.* Non-finite initial states are rejected
(`non_finite_initial_state`), and non-finite derived scalar outputs are dropped
with a `non_finite_derived_output` warning.

**Comparisons.** `compare_outputs` masks non-finite pairs before computing
metrics:

* a `non_finite_series` warning reports how many points were excluded;
* metrics are computed over the finite pairs only and are therefore finite
  whenever at least one pair is finite;
* `valid_points` and `non_finite_points` are recorded in every comparison;
* if **no** pair is finite, metrics are `NaN` and a `no_finite_pairs` error
  diagnostic is emitted.

Relative change keeps its existing treatment: undefined where
`|reference| <= relative_epsilon`, reported as `NaN` and counted in
`relative_delta_flagged_points` with an `unsafe_relative_denominator` warning.

## Consequences

* A partially-NaN series yields honest, finite metrics plus a disclosure, rather
  than a metric that is `NaN` for unexplained reasons.
* A metric computed over a masked subset can be misleading if the masked points
  were important; this risk is disclosed by `non_finite_points` and the warning,
  which is the best a general-purpose engine can do without domain knowledge.
* The `non_finite_output` guard is defence-in-depth: SciPy usually reports
  `solver_failed` first. It is exercised directly by a test that injects a
  fake "successful" solve containing `NaN`.
