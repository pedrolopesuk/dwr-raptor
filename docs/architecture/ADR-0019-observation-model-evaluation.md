# ADR-0019: Observation ↔ model evaluation

**Status:** Accepted

## Context

M11 gives DRW a universal observation contract, an immutable content-addressed
dataset store, an `ObservationMapping`, explicit units/uncertainty and CSV import.
M1–M10 give typed models, a deterministic `Runner`, and run records carrying full
`OutputValue`s. The next question is: *given an already-produced run and a
dataset, how well does the model reproduce the observations?*

## Decision

* **Canonical path = a completed run (execution-free).** `evaluate_run` reads
  `RunRecord.result.outputs` and never launches the `Runner`; the core `evaluate`
  is a pure function over model `OutputValue`s, a `Dataset`, an
  `ObservationMapping` and an `EvaluationConfig`. M12B (calibration) will execute
  the runner and call the same core.
* **Mapping is reused.** M11 `ObservationMapping` is the foundation and is not
  duplicated; `validate_mapping` provides the cross-artifact checks. M12A adds no
  new mapping type.
* **Evaluation behaviour lives in `EvaluationConfig`** (not in the mapping):
  requested metrics, residual modes, alignment, tolerance, relative epsilon,
  datetime origin, degrees of freedom. M12A supports `exact` and **opt-in linear
  interpolation** only; resampling/nearest/aggregation/binning/windowing are out.
* **One comparison abstraction.** A pair reduces to aligned points
  `(coordinate, observed, predicted, residual, ±sigma)`; scalar = 1 point,
  timeseries = N points, a vector = several pairs. `matrix`/`categorical` outputs
  fail `output_kind_unsupported`.
* **Residuals:** raw (default) `r = y_model − y_obs`; relative (opt-in) only where
  `|y_obs| > relative_epsilon` (never divided by zero); normalized (opt-in)
  `r/σ` only for `std`/`precision` with finite `σ > 0`. No fabrication.
* **Metrics:** `n_used`, `n_excluded`, `mean_residual`, `mae`, `rmse`,
  `max_abs_error`; optional `relative_*`, `weighted_rmse`, `chi_square`,
  `reduced_chi_square` (which requires an explicit `degrees_of_freedom` — never
  estimated).
* **Uncertainty** is *reported* for all types and used for weighting only when
  explicitly requested and only for `std`/`precision`. `stderr`, `asymmetric`
  and `interval` are never silently collapsed into a symmetric σ.
* **Missing/quality** reuse `summarize_usability`/`classify_value`: exclusions
  carry reasons and observation indices; nothing is dropped silently; zero usable
  comparisons → `ok=false`, no metrics.
* **Fail-closed** on any invalid comparison (unknown variable/output, non-numeric
  observation, unsupported kind, shape/unit problems, alignment failure, non-finite
  model output, invalid uncertainty, no usable observations); `ok=false`, no
  metrics, no partial conclusion.
* **`EvaluationResult` is content-addressed** (`evaluation_hash`, canonical
  serialization) but **on-demand only** — no persistence, no `EvaluationStore`,
  no `EvidenceManifest` change.
* **No inference.** No likelihood, no posterior, no parameter estimation, no
  objective optimisation.

## Consequences

* Researchers can judge how well a model reproduces data without any execution or
  fitting; the result carries the exact run/dataset/mapping/model hashes.
* The evaluator is a stable interface for M12B: it exposes residuals and named
  scalars (including `chi_square`) that an optimizer can consume, without M12A
  knowing anything about optimisation.
* Importing/evaluating proves **model agreement with these data only** — never
  validity, calibration or generalisation (see ADR-0019 boundary and M12C).

## Boundary

M12A owns comparison. **M12B** owns calibration (execution in a loop, objective,
optimiser, parameter updates). **M12C** owns validation (independent data,
splits, generalisation claims). M12A must not do any of those.
