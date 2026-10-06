# ADR-0023: Objective semantics

**Status:** Accepted

## Context

Calibration minimises a single scalar derived from M12A. The choice of objective
is a scientific decision; it must be explicit and must never be a hidden default.

## Decision

* **The objective is an M12A metric**, selected by name and read from the
  `EvaluationResult`. Exactly one metric:
  `rmse` (default), `mae`, `max_abs_error`, `mean_residual`, `relative_rmse`,
  `relative_mae`, `max_abs_relative_error`, `weighted_rmse`, `chi_square`.
* **Minimise only.** All supported metrics are error magnitudes; there is no
  maximisation and no "fit score".
* **One pair.** The objective scores exactly one `MappingPair`. When the mapping
  declares more than one pair, the pair (`observation`, `output`) must be selected
  explicitly. Multi-pair aggregation is deferred.
* **The metric must be requested in the `EvaluationConfig`** (validated at config
  time) so the objective is read from M12A and never recomputed.
* **Weighted metrics are opt-in** and require the mapping's uncertainty to be
  `std`/`precision`; M12A's fail-closed rules govern σ (no fabricated uncertainty,
  no `stderr`/`asymmetric`/`interval` collapsed into a symmetric σ).
* **No arbitrary objective weights**, no metric combination, no cross-unit
  combination, no multi-dataset aggregation, no likelihood/robust losses.

## Rationale

* RMSE is a *convention* (output units, large-error penalty), explicitly not a
  statistical claim.
* Restricting to one pair sidesteps the scientifically dubious combination of
  metrics with different units. Weights, when needed later, must be explicit.
* Reading only M12A metrics guarantees the objective and the reported evaluation
  are the same computation.

## Consequences

Multiple pairs/datasets, explicit weights, multi-objective scalarisation,
least-squares/likelihood objectives and robust losses are explicitly deferred.
