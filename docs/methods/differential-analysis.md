# Method note: differential analysis

**Implementation:** `drw.numerics.delta.compare_run` /
`compare_outputs`, metrics in `drw.numerics.metrics`, alignment in
`drw.numerics.alignment`.

## What is computed

For each selected output, the variant is aligned to the reference and these are
recorded:

* **Absolute delta** `Δy = y_variant - y_reference`.
* **Relative change** `r = Δy / max(|y_reference|, ε)`. Points where
  `|y_reference| <= ε` are **undefined**; they are reported as `NaN` and counted
  in `relative_delta_flagged_points`, with an `unsafe_relative_denominator`
  warning. They are never silently divided through.

## Summary metrics (specification section 10.5)

`mae`, `rmse`, `max_abs_delta`, `area_delta` (`∫(variant - reference) dt`),
`peak_shift` (argmax location shift), `correlation` (Pearson; `NaN` for
zero-variance inputs), `distribution_distance` (Wasserstein).

## Alignment

`exact` requires identical coordinate axes. If axes differ and the caller
requested `exact`, the comparison falls back to `interpolate` and records an
`alignment_fallback` warning plus the `interpolated_alignment` disclosure.
`resample` interpolates both series onto a supplied common grid.

## Verification

* **Invariant:** comparing a series with itself yields `max_abs_delta == 0`,
  `mae == 0`, `rmse == 0` (property test).
* **Sign:** `area_delta(a, b) == -area_delta(b, a)`.
* **Synthetic references:** metrics are checked against hand-computed values
  (`tests/unit/test_metrics.py`).

## Missing / non-finite data

Non-finite pairs (`NaN`/`Inf` in either series) are **masked** before metrics are
computed. Every comparison records `valid_points` and `non_finite_points`, emits a
`non_finite_series` warning when points were excluded, and emits a `no_finite_pairs`
error when nothing is left to compare (metrics then `NaN`). Metrics are finite
whenever at least one finite pair exists. See ADR-0006.

## When the result is not expected to match / to be meaningful

* **Interpolated alignment** can change conclusions; it is always disclosed and
  flagged.
* A metric computed over a masked subset can be misleading if the excluded points
  were important; the disclosure (`non_finite_points`) is the engine's signal that
  the metric may not be representative.
* **Chaotic outputs** decorrelate over time; a large `max_abs_delta` there is
  expected and is *not* evidence of a bug.
* **Correlation** measures shape similarity, not magnitude equivalence.
