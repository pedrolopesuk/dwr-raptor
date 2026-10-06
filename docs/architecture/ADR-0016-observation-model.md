# ADR-0016: Universal observation/data model

**Status:** Accepted

## Context

M1–M10 give DRW typed models, deterministic experiments, differential analysis,
uncertainty, sensitivity, Sobol' sensitivity and local parameter identifiability.
There is, however, **no way to represent measured data**: every "run" is a forward
simulation. Calibration and empirical validation (future milestones) require a
general, domain-agnostic contract for observations. This ADR (M11A) establishes
that contract. It is a *contract only* - no storage, import adapters, or CLI/web.

The contract must represent astrophysics light curves, spacecraft trajectories,
physics response curves, biology replicate series and climate point observations
through the **same** structure, with no domain-specific field anywhere.

## Decision

* **Hierarchy.** `Dataset` (immutable identity + provenance; the unit of
  reference) contains one `ObservationSet` (the scientific payload: a table). A
  `Variable` is a column; the coordinates are named independent axes. The
  **Observation is a semantic row** - deliberately not a stored class.
* **No domain types.** There is no `AstrophysicsObservation`/`SpaceObservation`/
  `ClimateObservation`; `flux`, `wavelength`, `latitude`, `concentration`, … are
  ordinary `Variable`s (name + kind + role + unit).
* **Repeated coordinates are allowed.** Coordinates do **not** uniquely identify
  rows: `time=1, replicate=1` and `time=1, replicate=2` coexist.
* **Roles are explicit:** `coordinate | measurement | derived | uncertainty |
  quality | metadata`. Derived values stay distinguishable from measured values.
* **Units.** `drw.schema.units` is reused. `unit=None` means **unspecified**,
  distinct from `"dimensionless"`; units are never inferred and not globally
  required. Compatibility becomes **mandatory** when an `ObservationMapping` pairs
  a variable with a model output; a conversion is applied only when explicitly
  declared, and incompatible units hard-fail.
* **Uncertainty is tagged, never collapsed:** `none | std | stderr | asymmetric |
  interval | precision`, inline or via a companion column. Covariance/correlation
  are **deferred (M12)**; the types are never equated.
* **Missing/quality.** `None` is an explicit *missing* value; `non_finite` and
  type-`invalid` cells are rejected at construction. Quality flags map to
  `missing/invalid/censored/rejected` (unusable) or `flagged` (usable but
  noteworthy) and **never delete rows**; usability is reported with reasons.
* **Time.** An absolute ISO-8601 `datetime` coordinate or an elapsed numeric
  coordinate with an explicit unit. No JD/MJD/astronomical time system (adapters).
* **Multi-coordinate tabular** data (time/wavelength, x/y/z, lat/lon/alt) is
  supported; **N-dimensional array storage is deferred (M12)**.
* **Integrity.** The full `content_hash` (canonical serialization) is
  authoritative and `dataset_id = "ds-" + content_hash[:12]`. `DatasetRef` carries
  both; `resolve_dataset_id`/`assert_same_dataset` refuse to let two distinct full
  hashes silently resolve to the same short id (hash-prefix ambiguity).
* **Mapping is standalone.** `ObservationMapping` (dataset ref + model ref +
  pairs + alignment + notes) is separate from both `Dataset` (which stays
  model-agnostic) and any future calibration spec. M11 supports **only**
  `alignment.strategy = "exact"` with an explicit tolerance; interpolation,
  resampling, nearest-neighbour and aggregation are M12.

## Consequences

* Domain neutrality is structural: adding astrophysics/space/etc. requires no core
  change - only variables, units and (later) adapters.
* The existing `ModelSchema`/`ExperimentSpec`/`Runner`/evidence/identifiability
  behaviour is untouched; the observation contract is purely additive.
* Calibration/validation is unblocked without being implemented: a future
  CalibrationSpec consumes a `DatasetRef` + `ObservationMapping`, so overwriting a
  file can never silently change an old experiment's meaning.
* Passing this contract proves **observation integrity only** - never model
  validity, calibration or scientific conclusion.
* Storage (`datasets/`, hashing on disk, verification) is M11B; the first import
  adapter (CSV) and the import UX are M11C; FITS/Parquet/HDF5/NetCDF adapters are
  later and optional.

## Boundary

M11A owns representation, units, uncertainty *representation*, provenance schema,
missing/quality semantics, integrity/identity, and mapping/alignment **primitives**.
Concrete storage, import adapters, and any residual/objective/fitting logic are
out of scope (M11B/C and M12 respectively).
