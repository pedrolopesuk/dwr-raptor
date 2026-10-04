# Method note: parameter sampling

**Implementation:** `drw.numerics.sampling.expand_design`.

## Designs

| Method | Construction | Determinism |
| --- | --- | --- |
| `grid` | Cartesian product of declared factor values (last factor varies fastest). Explicit `values` or `linspace(lower, upper, steps)`. | Fully deterministic, no seed. |
| `random` | `numpy.random.default_rng(seed).random((n, d))` mapped to bounds. | Deterministic for a fixed seed. |
| `latin_hypercube` | `scipy.stats.qmc.LatinHypercube(d, seed)`. | Deterministic for a fixed seed. |
| `sobol` | `scipy.stats.qmc.Sobol(d, scramble=True, seed)`. | Deterministic for a fixed seed. |

Factor bounds fall back to the model parameter's declared bounds when the factor
does not narrow them. Every sampled value is coerced to the parameter's type (for
example `int` parameters are rounded).

## Run count

`grid` → product of factor cardinalities; stochastic designs → `n_samples`.
Total runs = `1 (baseline) + variants`. See ambiguity A7 in
`docs/architecture/ambiguities.md`.

## Verification

* The same seed produces the same design; different seeds differ
  (`tests/unit/test_sampling.py`).
* All samples lie within the declared bounds.
* Grid order is fixed and asserted (cartesian, declared factor order).

## Notes and caveats

* An **empty factor list** yields an empty design: only the baseline runs. This is
  reported as a `no_factors` warning, not an error.
* **Sobol** balance properties require a power-of-two `n_samples`; a
  non-power-of-two count raises a `sobol_non_power_of_two` warning (the SciPy
  `UserWarning` is suppressed in favour of this structured diagnostic).
* A `bounds`-only factor (`lower`/`upper` without `steps`) is valid for stochastic
  designs but **invalid for `grid`** (recorded as `factor_requires_steps`).
