# ADR-0013: The reproduction check requires explicit tolerances

**Status:** Accepted

## Context

Milestone 7 adds a reproduction check: re-execute a stored experiment's saved
specification and compare the fresh run to the stored reference. This needs a
numerical-equivalence policy ("how close is close enough?"). The first question is
whether the existing `verification.rtol` / `verification.atol` fields can be
reused.

What those fields actually do today:

* `verification.rtol` / `verification.atol` are **integration tolerances**. The
  runner copies them into `RunContext`, and `OdeModel.run` passes them to
  `scipy.integrate.solve_ivp` (`runner.py` → `RunContext` → `ode.py`). They govern
  the accuracy of one numerical solve; they are not a statement about the
  agreement between two separate solves.
* `verification.relative_epsilon` is the denominator-safety threshold for the
  relative-change metric (`delta.py`); it is not an equivalence threshold either.
* There is no existing run-to-run equivalence check anywhere in the code
  (`compare_outputs` computes deltas/metrics; it makes no pass/fail judgement).

So the declared tolerances have a **different purpose**. A user's solver rtol of
`1e-9` is a property of how a trajectory is integrated, not a claim that two runs
should agree to `1e-9`.

## Decision

* The reproduction check **requires the caller to supply `rtol` and `atol`
  explicitly**. No default is invented and no value is silently derived from
  `verification.rtol/atol`.
* The pass criterion is the standard, documented element-wise test:

  ```
  |fresh - reference| <= atol + rtol * |reference|
  ```

  applied to the aligned, finite pairs of each output. This is the same
  convention as `numpy.isclose`, chosen because it is the ubiquitous, well-defined
  meaning of `rtol`/`atol`.
* Both values are validated: they must be finite and `>= 0`. `rtol` must also be
  `< 1` (a relative tolerance at or above 100% is meaningless).
* Numerical **identity** (exact element-wise equality) is reported separately from
  **equivalence within tolerance**. A tiny floating-point difference is reported
  as "equivalent" (or "different"), never automatically as a scientifically
  meaningful difference.
* If there are non-finite pairs, or the arrays/axes cannot be aligned under the
  existing exact rule, the output is reported **incomparable** and the overall
  check is `inconclusive` rather than a false pass/fail.

## Consequences

* The reproduction check does not become a hidden source of a scientific
  threshold: the tolerance is an explicit, auditable input on every call (CLI
  flags, bridge parameters, UI fields).
* Callers who want exactness pass `rtol=0, atol=0`; the identity check is still
  reported independently.
* This decision is about *numerical* reproducibility only. Matching hashes and
  matching numbers do not establish scientific validity, and the report says so.
* Reusing `verification.rtol/atol` as an equivalence policy would be a semantic
  change to solver behaviour and is **not** done here.
