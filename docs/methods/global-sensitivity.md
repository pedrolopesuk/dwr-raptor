# Method note: global variance-based sensitivity (Sobol' indices)

**Implementation:** `drw.global_sensitivity` (`sobol_indices`,
`sobol_indices_for_experiment`). On-demand; reuses `Runner` and the seeded
Sobol' quasi-Monte Carlo sampler (`scipy.stats.qmc.Sobol`).

## Estimand

For independent inputs `X_1..X_d` and a scalar output `Y = f(X)`:

```
S_i   = Var_{X_i}( E[Y | X_i] ) / Var(Y)            first order
S_Ti  = 1 - Var_{X_-i}( E[Y | X_-i] ) / Var(Y)      total order
```

`S_i` is the share of output variance explained by `X_i` alone; `S_Ti` includes
its interactions with the other factors, so `S_Ti - S_i` is the interaction share.
These are **variance attribution**, not causal effects.

## Sampling design (Saltelli coupled design)

A single `2d`-dimensional, N-point scrambled Sobol' sample is split into two
`d`-column matrices `A` and `B`; `AB_i` replaces column `i` of `A` with `B[:, i]`.
Using two halves of one `2d` sample (rather than two consecutive blocks of a
`d`-dimensional sequence) keeps `A` and `B` mutually independent. The unit-cube
points are scaled to each factor's declared `[lower, upper]` bounds.

* Evaluations = `N * (d + 2)` (N for `A`, N for `B`, N per `AB_i`).
* Power-of-two `N` is recommended for Sobol' balance but is **not enforced**. A
  non-power-of-two `N` is allowed with weaker balance properties; the report
  records an explicit note saying so, and the web panel flags it before the study
  runs. This application-level note is the authoritative, dependency-independent
  diagnostic; SciPy may *additionally* emit its own balance warning on stderr.
* A fixed `seed` makes the design and the estimates reproducible.

## Estimators (fixed and recorded)

```
V      = var([f(A), f(B)], ddof=1)
V_i    = (1/N)  * sum_j f(B)_j (f(AB_i)_j - f(A)_j)     # Saltelli et al. 2010
S_i    = V_i / V
V_Ti   = (1/2N) * sum_j (f(A)_j - f(AB_i)_j)**2          # Jansen 1999
S_Ti   = V_Ti / V
```

The report records the estimator string
`saltelli2010_first_order+jansen1999_total_order`.

## Uncertainty and convergence

A percentile bootstrap over the N rows (joint resampling of `A`/`B`/`AB_i`) gives a
diagnostic 95% interval for each index. It is **not** proof of convergence; no
single sample size establishes convergence, and the estimates are finite-sample.

## Finite-sample correctness

**Estimates are not clipped.** `S_i` may be slightly negative or exceed 1, and
`S_i` may exceed `S_Ti`, because of sampling/numerical error; the theoretical
relationships `0 <= S_i <= S_Ti`, `sum S_i <= 1` hold only in the limit. The raw
estimates are reported, with the relationships documented here separately.

## Failure semantics (fail-closed)

The estimators require complete paired `A`/`B`/`AB_i` rows, so any evaluation that
fails, times out, is missing the output, or is non-finite makes the whole study
`inconclusive`: indices are `null` and the reasons/counts are reported. Zero or
non-finite output variance is `inconclusive` (indices are undefined, never zero).
Invalid factors/outputs/bounds, too-small `N`, duplicate factors, and studies
exceeding the evaluation cap are rejected.

## Assumptions and limitations

* **Independent inputs.** Correlated real-world inputs invalidate these indices;
  this is not a correlated-input method.
* **Scalar outputs only** in this version (time-series outputs are out of scope).
* Not causal; not scientific validation; not a probability statement.
* Single-environment: the estimates are reproducible from the recorded seed on the
  same model/environment, subject to the project's reproducibility limits.

## Interfaces

* Core: `sobol_indices` / `sobol_indices_for_experiment`.
* CLI: `drw sobol <experiment_id> [--output O] [--factors a,b] [--n N] [--seed S] [--bootstrap B]`.
* Bridge: `global_sensitivity` (read-only w.r.t. the store; runs model evaluations
  in isolated subprocesses; optional `job_id` writes measured progress).
* Web: "Global sensitivity (Sobol)" panel.

## What this is not

Not calibration, optimization, global sensitivity for time-series, correlated-input
sensitivity, or a persistent evidence artifact (the result is computed on demand).

References: Sobol' (2001); Saltelli et al. (2010), Comput. Phys. Commun. 181:259;
Jansen (1999).
