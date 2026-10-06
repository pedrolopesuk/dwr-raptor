# Method: local parameter identifiability

## What question it answers

For a model and a baseline `theta_0`, and a set of selected output targets:

> Could the declared outputs **locally** distinguish these parameters, and which
> parameter combinations are effectively indistinguishable near this baseline?

This is the bridge between the forward-simulation engine and a future
observations/calibration workflow. It is **local, linearised structural**
identifiability only.

## Method

Central finite differences estimate the Jacobian of the targets with respect to
the parameters, using the existing execution engine (no engine is duplicated):

```
J_ij = ( y_i(theta_j + h_j) - y_i(theta_j - h_j) ) / (2 h_j)
h_j  = max(step_scale * |theta_j|, absolute_step)
```

The normalized sensitivity matrix removes parameter units and output scales:

```
S_ij    = J_ij * range_j / s_i
range_j = upper_j - lower_j                       (declared parameter range)
s_i     = max(|y_i(theta_0)|, central variation, ROW_SCALE_FLOOR)
```

`ROW_SCALE_FLOOR = 1e-12`. If the baseline magnitude is at the floor (for example
an `argmax_t` that sits at the start of the window), the observed central
variation provides the scale, so a legitimate zero baseline does not blow up the
matrix. A target with neither a baseline magnitude nor any variation is excluded
as uninformative.

## SVD diagnostics

`S = U Σ Vᵀ` is computed with the full right-singular vectors, so when there are
fewer informative targets than parameters the null space is exposed rather than
hidden. The report contains:

* **singular values** (`σ_0 ≥ σ_1 ≥ …`);
* **numerical rank**: the count of `σ_k > rank_tolerance * σ_0`;
* **condition number**: `σ_0 / σ_min` when `σ_min` is above the tolerance, else
  `null` (rank-deficient);
* **directions**: for each right-singular vector, the condition index and the
  `|V_kj|` weights, with the dominant parameters flagged;
* **parameter-pair correlations**: the strongest `|correlation|` of the normalized
  sensitivity columns, reported only when there are at least four informative
  targets (with fewer points `|correlation|` is trivially 1).

### Thresholds (disclosed, never hidden)

| Quantity | Default | Meaning |
| --- | --- | --- |
| `DEFAULT_STEP_SCALE` | `1e-3` | relative finite-difference step |
| `ABSOLUTE_STEP` | `1e-6` | absolute step floor (handles a zero baseline) |
| `DEFAULT_RANK_TOLERANCE` | `1e-12` | relative singular-value nullity threshold |
| `FD_NOISE_FACTOR` | `10` | rank tolerance is raised to at least `10 * max_step^2` |
| `CONDITION_THRESHOLD` | `1e6` | above this the study is "ill-conditioned" |
| `CORRELATION_THRESHOLD` | `0.9` | pairs at or above this are reported |

The verdict is `rank-deficient` when the numerical rank is below the number of
parameters (including the inherently under-determined case of more parameters than
informative targets), `ill-conditioned` when the condition number exceeds the
threshold, otherwise `well-conditioned`; any fail-closed condition yields
`inconclusive`.

The finite-difference noise floor matters: a central-difference Jacobian cannot
resolve a direction weaker than its own truncation/round-off error (~`h²`), so a
true degeneracy appears with a small but non-zero smallest singular value. Raising
the rank tolerance to `FD_NOISE_FACTOR * max_step^2` prevents such a direction
from being misreported as identifiable.

## Targets

* A **scalar** output contributes one target: its value.
* A **time-series** output contributes a fixed, explicitly disclosed feature set:
  `max`, `min`, `mean`, `final`, `argmax_t`. No arbitrary user-provided feature
  code is accepted.
* `--outputs` selects *outputs*; each selected output expands to its scalar value
  or its five features.
* A feature that cannot be computed safely (empty/non-finite values, an `argmax_t`
  whose axis is missing) fails the evaluation closed.

## Parameters

Only continuous (`float`) parameters that declare bounds are valid identifiability
targets. Integers, booleans and categoricals are rejected; parameters without
bounds are rejected; bounds are never invented.

## Cost

`2 * p + 1` model evaluations: a central pair per parameter plus one baseline.
Because a single model evaluation produces **every** selected target feature, the
count does **not** multiply by the number of targets. A hard cap
(`MAX_EVALUATIONS = 4096`) bounds the study; a request above the cap is rejected
before execution, and the estimate is surfaced in the CLI, bridge and UI. The
study-size limits are single-sourced in `drw.identifiability` and exposed to the UI
through `capabilities.identifiability`.

## Failure semantics (fail-closed)

The study is `inconclusive` (no rank, no condition number, no conclusion) when:

* a parameter is at or too close to a bound for a valid central perturbation
  (one-sided differences are **not** substituted);
* any evaluation fails, times out, is missing an output, or is non-finite;
* the normalized matrix has no measurable magnitude, or no target is informative.

Nothing is fabricated. Reasons are reported explicitly.

## Interpretation

* A **`rank-deficient`** or **`ill-conditioned`** verdict means the selected
  outputs cannot (locally) separate some parameter combination. The report names
  the dominant parameters of the offending direction.
* A **`well-conditioned`** verdict means the selected outputs do separate the
  parameters *locally*; it is a statement about the chosen outputs and baseline,
  not proof of global identifiability.

## What this is not

It is **not** global identifiability, **not** practical identifiability from noisy
observations, **not** a calibration or fit, **not** causal, and **not** a statement
that the model is scientifically valid. Practical identifiability requires
observations, a noise model and an experimental design, and belongs to a future
calibration/validation milestone.

## Examples

```
# Are mass and stiffness distinguishable from the displacement trajectory?
drw identifiability exp-1d700f7ad478 --factors m,k --outputs x --workspace .drw/web-workspace

# The documented beta / predator0 relationship on the early prey peak:
drw identifiability exp-1d700f7ad478 --factors beta,predator0 --outputs prey
```

For an undamped oscillator (`c = 0`) with `v0 != 0`, the displacement is a function
of `sqrt(k/m)` alone, so `m` and `k` are reported as `rank-deficient`. For the
predator-prey early prey peak, `beta` and `predator0` are reported as a poorly
distinguishable combination. Both are verified in
`tests/scientific/test_identifiability_ground_truth.py`.

## References

Standard central-difference Jacobian estimation and scaled-sensitivity
conditioning; Belsley, Kuh & Welsch (1980) collinearity diagnostics.
