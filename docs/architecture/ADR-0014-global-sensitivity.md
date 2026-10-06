# ADR-0014: Global sensitivity via a Saltelli coupled design and Jansen/Saltelli estimators

**Status:** Accepted

## Context

Milestone 9 adds global, variance-based sensitivity (Sobol' indices) to close the
documented limitation that the one-at-a-time (OAT) ranking is local and cannot
detect interactions (`drw/sensitivity.py`; `README.md`). The study is on-demand and
must reuse the existing execution engine and seeded sampler, preserve all existing
contracts, and not fabricate precision.

## Decision

* **Estimand:** `S_i = Var_{X_i}(E[Y|X_i])/Var(Y)` and
  `S_Ti = 1 - Var_{X_-i}(E[Y|X_-i])/Var(Y)` for independent inputs and a scalar
  output.
* **Design:** the Saltelli coupled design built from one `2d`-dimensional,
  N-point scrambled Sobol' sample split into matrices `A` and `B`, with
  `AB_i = A` with column `i` replaced by `B[:, i]`. Splitting a single `d`-dimensional
  sequence into two consecutive blocks is **rejected**: it makes `A` and `B` nearly
  collinear (measured correlation ~0.9999 in an early prototype) and biases the
  estimators. Evaluations = `N*(d+2)`.
* **Estimators (fixed, recorded):** first order = Saltelli et al. (2010)
  `V_i = (1/N) Σ f(B)_j (f(AB_i)_j − f(A)_j)`; total order = Jansen (1999)
  `V_Ti = (1/(2N)) Σ (f(A)_j − f(AB_i)_j)²`; denominator
  `V = var([f(A), f(B)], ddof=1)`.
* **Uncertainty:** a percentile bootstrap (joint row resampling) is reported as a
  **diagnostic only**; the milestone states plainly that it is not proof of
  convergence.
* **No clipping:** finite-sample estimates are preserved even when slightly
  negative, > 1, or `S_i > S_Ti`; the theoretical bounds are documented separately
  and are not imposed.
* **Fail-closed:** because the estimators require complete paired rows, any failed,
  timed-out, missing-output or non-finite evaluation makes the study
  `inconclusive` with counts and reasons; zero variance is `inconclusive`
  (undefined, never zero).
* **On-demand and additive:** a new module plus CLI/bridge/UI surfaces; no
  `ExperimentSpec`/`ModelSchema` change, no persistence, no evidence-format change,
  no new dependency, no parallelism.

## Consequences

* Researchers get a defensible variance decomposition that detects interactions,
  while the existing delta/OAT/uncertainty/reproduce/evidence behaviour is
  unchanged.
* Cost grows as `N*(d+2)` sequential model evaluations; a bounded default (N=32)
  and an evaluation cap (4096, overridable by explicit configuration) protect
  against accidental large studies, and the estimate is surfaced to the user.
* The independent-input assumption is stated explicitly; correlated-input
  sensitivity remains a separate, unimplemented methodology.
* A persistent evidence artifact was deliberately **not** added (the study is
  computed on demand); persisting it would be an additive artifact requiring
  separate approval.
