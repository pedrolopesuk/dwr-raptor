# ADR-0027: Calibration boundaries — validation & parameter uncertainty

**Status:** Accepted

## Context

A converged optimizer can tempt a user to read the fitted parameters as "the
true parameters", or the fit as a validated model. DRW must not conflate fitting
with validation or with parameter uncertainty.

## Decision

* **Calibration ≠ validation.** M12B fits using exactly one designated dataset
  (`CalibrationConfig.data_role = "calibration"`; the `"validation"` value is
  reserved and rejected). It never holds out data and never claims generalisation.
  M12C will evaluate the fitted parameters against **independent** observations and
  must assert `validation.dataset.content_hash ≠ calibration.dataset.content_hash`.
* **Calibration ≠ Bayesian inference.** No likelihood, no prior, no posterior, no
  marginalisation. The objective is a descriptive error metric, explicitly **not**
  a likelihood.
* **Point estimate ≠ parameter uncertainty.** M12B reports **no** confidence
  intervals, standard errors, covariance or error bars. Those belong to a future
  milestone (profile likelihood, bootstrap, or a Bayesian treatment).
* **Convergence ≠ certainty.** A converged point estimate suggests, at most, a
  fitted value within the searched domain; it says nothing about uniqueness.
* **Identifiability is advisory.** M10 is used only to *warn* (`warn`, default) or
  to *refuse* (`require`, opt-in) — never as an optimizer constraint. When the
  pre-check flags rank deficiency / ill-conditioning / inconclusiveness, the
  result carries the caveat and the mandatory disclosure, so DRW never emits a bare
  "best-fit parameters found".
* **Mandatory disclosure.** Every result carries a `note` stating the limited
  scientific claim: *within the searched bounds, seed, objective, dataset/mapping
  and budget, the lowest objective found was attained at the reported parameter
  vector — not a statement of uncertainty, significance or truth.*

## Consequences

Calibration produces a traceable, bounded point estimate plus explicit caveats;
validation, parameter uncertainty and Bayesian inference remain future work.
