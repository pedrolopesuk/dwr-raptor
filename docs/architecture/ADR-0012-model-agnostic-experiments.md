# ADR-0012: Model-agnostic experiment creation reuses the demo builder

**Status:** Accepted

## Context

Milestone 5 generalizes the researcher workspace from a sample-centred flow to a
model-agnostic one. The Python core already registers three models
(`oscillator`, `predator-prey`, `lorenz`) and already exposes
`sample_experiment(model_id)`, which builds a baseline-vs-+10% spec for any
registered model via `drw.demo.build_demo_experiment`. What was missing was a UI
affordance: `Workspace.openSample()` hardcoded `"predator-prey"` and the model
list was used only for a count (recorded as milestone-4.5 risk #7).

The question is how to let a user start a new experiment from any supported model
without inventing new science, new bridge operations, or new numerical code.

## Decision

* The UI lists **every registered model** (`list_models`) in a picker and creates
  a new experiment by calling the **existing** `sample_experiment(model_id)` plus
  `describe_model(model_id)`; the returned spec and authoritative schema populate
  the editor. **No new bridge operation is added.**
* The seeded configuration is a **demonstration**: a +10% intervention on the
  model's first input. The UI labels it as such and states it is not a
  scientifically justified experiment. The seeded spec keeps its existing name
  (`"DRW killer demo"`); changing it would change spec hashes and is deferred.
* **Eligibility is technical, not scientific.** The picker derives eligibility
  from `capabilities` alone (`modelViability`): at least one numeric parameter
  that can be varied and at least one comparable output. A model that fails is
  disabled with the reason; if creation still fails, the authoritative Python
  error is surfaced verbatim. Eligibility is explicitly described as not a claim
  of scientific validity.
* **Identity and persistence are unchanged.** `Runner.run` still derives
  `exp-<hash12>` from the spec content hash and `ExperimentStore.save` still
  overwrites an identical spec's record. This milestone documents that behaviour
  rather than redefining identity or migrating data.
* Parameter metadata shown in the UI comes only from the model's `ModelSchema`
  (including `description`); nothing is inferred or fabricated.

## Consequences

* Every registered model can now start, validate and run an experiment, and the
  boundary stays exactly where it was: Python is authoritative, TypeScript
  orchestrates.
* The seeded experiment's name/hypothesis still read as "demo"; a neutral seed
  builder is future work if the copy matters. This is cosmetic and does not
  change numerics or identity.
* The picker is only as broad as the registry (three models); it is **not** a
  model-registration or upload UI, which remains out of scope.
* Repeatedly starting the same model yields the same demonstration spec, so
  re-running an unchanged identical spec overwrites its stored record - a
  pre-existing, documented property (see the milestone-4.5 report, risk #4).

## Alternatives considered

* **A new `new_experiment` bridge op / seed builder.** Rejected for this
  milestone: it adds surface without removing any limitation, since
  `build_demo_experiment` is already generic. Can be added later if the demo
  naming needs to change.
* **Client-side assembly of the seed spec.** Rejected: it would duplicate
  scientific/contract logic in TypeScript, violating ADR-0002 and ADR-0008.
* **Changing deterministic ids or overwrite semantics.** Rejected: identity and
  migration behaviour must not be redefined silently.
