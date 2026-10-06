# ADR-0021: Evaluation alignment & datetime bridge

**Status:** Accepted

## Context

M11 alignment (`drw.observations.align`) is an exact numeric matcher; M11
`ObservationMapping` fixes `alignment.strategy = "exact"`. Model `OutputValue`
axes are numeric (`axis`, `axis_unit`); M11 datetime observations are ISO-8601
strings. Evaluation therefore needs (a) a slightly wider alignment vocabulary and
(b) an explicit bridge from datetime coordinates to the model's numeric axis.

## Decision

* **Alignment lives in `EvaluationConfig`, not the mapping.** The M11 mapping
  contract is unchanged.
* **Supported M12A strategies:**
  * `exact` (default) - match observation coordinates to the model axis within an
    explicit tolerance; unmatched observations are reported (never dropped
    silently; a warning while other comparisons remain, `ok=false` if none remain).
  * `interpolate` (**opt-in**) - **linear** interpolation of the model output onto
    the observation coordinates; always emits a warning and sets
    `interpolated=true`; coordinates outside the model axis range are unmatched
    (no extrapolation).
* **Not supported:** resample, nearest-neighbour, aggregation, binning, windowing
  (deferred; they can silently change scientific meaning).
* **Datetime bridge:** for a datetime coordinate, `time_origin` **must** be
  supplied in `EvaluationConfig`. Observation datetimes are converted to elapsed
  **seconds** relative to that origin; the model axis must declare a time unit
  (`axis_unit` compatible with `"s"`) and is converted to seconds. Naive and
  aware datetimes must not be mixed; mixed rows are excluded with an explicit
  warning. No JD/MJD/TAI/TT/GPS or other astronomy-specific time systems.
* **Coordinate-unit handling (numeric):** the observation coordinate unit and the
  model `axis_unit` must both be absent, or present and compatible; a compatible
  difference is converted (disclosed as an info diagnostic). Otherwise
  `coordinate_axis_mismatch`.
* **Value units** are handled separately by the mapping's explicit
  `unit_conversion` (ADR-0018); conversion happens on values, alignment on
  coordinates.

## Consequences

* Model-vs-observation comparison is well-defined for scalar, numeric-time and
  datetime-time series without any domain-specific time system.
* Interpolation is never implicit: it is opt-in, disclosed and flagged, so it
  cannot silently change a conclusion.
* Resampling/aggregation remain future work and must not be added implicitly.
