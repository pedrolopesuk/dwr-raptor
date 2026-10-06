# ADR-0015: Local parameter identifiability via a normalized finite-difference sensitivity

**Status:** Accepted

## Context

The OAT ranking and the Sobol' study describe how strongly parameters influence an
output, but neither answers a prior question: *could the declared outputs
distinguish the parameters at all?* `drw/sensitivity.py` states explicitly that
OAT "cannot detect interactions or non-identifiability", and the product roadmap
places calibration/validation after the simulation and analysis foundation. This
milestone (M10) adds a domain-agnostic **local identifiability** study, the bridge
between the existing forward-simulation engine and a future
observations/calibration workflow. It is on-demand and must reuse the existing
execution engine, preserve all existing contracts, and never fabricate a rank or a
conclusion.

This ADR records the method and its boundaries. It does not implement calibration,
data ingestion or any observational/practical-identifiability machinery.

## Decision

* **Question.** For a baseline `theta_0` and a set of selected scalar target
  features, can the outputs *locally* distinguish the parameters, and which
  parameter combinations are effectively indistinguishable?
* **Method.** Estimate the Jacobian `J_ij = d y_i / d theta_j` by **central finite
  differences** through the existing `Runner`:
  `J_ij = (y_i(theta_j + h_j) - y_i(theta_j - h_j)) / (2 h_j)` with
  `h_j = max(step_scale * |theta_j|, absolute_step)`.
  Normalize it into a sensitivity matrix `S_ij = J_ij * range_j / s_i`, where
  `range_j = upper_j - lower_j` and `s_i` is the output scale `max(|y_i(theta_0)|,
  observed central variation, floor)`. Then take the SVD of `S`.
* **Diagnostics reported:** singular values, numerical rank (relative tolerance),
  condition number, right-singular directions with dominant parameter weights
  (including the null space when there are fewer informative targets than
  parameters), and the strongest parameter-pair correlations.
* **Verdicts (with disclosed thresholds):** `well-conditioned`,
  `ill-conditioned` (condition number above the threshold), `rank-deficient`
  (numerical rank below the number of parameters) or `inconclusive`. The rank
  tolerance is raised to at least the central-difference noise floor
  (`FD_NOISE_FACTOR * max_step^2`), so a direction weaker than the finite-difference
  accuracy is not claimed as identifiable.
* **Targets.** Declared **scalar** outputs use their value; declared
  **time-series** outputs use a fixed, explicitly disclosed feature set
  (`max, min, mean, final, argmax_t`). No user-supplied feature code. A
  constant/zero-scale target is excluded as uninformative (never fabricated).
* **Parameters.** Only continuous (`float`) parameters that declare bounds are
  valid; integers, booleans and categoricals are rejected. Bounds are never
  invented.
* **Cost.** `2 * p + 1` model evaluations (a central pair per parameter plus a
  baseline). A single evaluation produces *every* selected target feature, so the
  count does not multiply by the number of targets. A hard cap (4096) bounds the
  study and the estimate is surfaced to the user before execution; an over-cap
  request is rejected before execution.
* **Fail-closed.** A parameter at (or too close to) a bound for a valid central
  perturbation, a failed/timed-out/missing/non-finite evaluation, or a matrix with
  no measurable magnitude makes the study `inconclusive` with reasons; rank, the
  condition number and conclusions are never fabricated.
* **On-demand and additive:** a new module plus CLI/bridge/UI surfaces, and an
  additive `capabilities.identifiability` block; no `ExperimentSpec`/`ModelSchema`
  change, no persistence, no evidence-format change, no new dependency, no
  parallelism. The study is read-only with respect to the experiment store.

## Boundary: what this is not

* **Not global identifiability.** It is a linearised, local statement at one
  baseline and one target set.
* **Not practical identifiability.** It uses no observations, noise model or
  experimental design. Those, and calibration fitting, belong to a future
  milestone.
* **Not model validity, causal, or parameter correctness.** Passing the analysis
  does **not** establish that the model is scientifically valid.

## Consequences

* Researchers can tell whether a proposed parameter set is even distinguishable
  from the chosen outputs, which explains OAT/Sobol anomalies (for example a
  parameter that only appears as a ratio or product) and de-risks future
  calibration.
* Cost is small and bounded (`2p+1` sequential evaluations); the default factor
  and target selection reuses the model's own contract, and the UI holds no
  duplicate configuration (limits come from `capabilities`).
* A user-specific feature language and a persistent evidence artifact were
  deliberately **not** added; both would be additive changes requiring separate
  approval.
