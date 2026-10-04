# Specification ambiguities and contradictions

The specification (`Differential_Research_Workbench_Complete_Spec.docx`) is the
source of truth for *intent*. Where it was silent, ambiguous, or self-contradictory
for the MVP, the resolution is recorded here rather than silently invented. Each
item names the decision and where it is implemented.

## A1. Repository root and Python package location

* **Spec:** section 8.4 lists `drw/` as an outer directory and puts only
  TypeScript-sounding packages under `packages/`. The Python core is never placed.
* **Resolution:** this repository root plays the role of `drw/`; the Python core
  is `packages/core` (import `drw`). See ADR-0001.

## A2. Duplicated schema packages

* **Spec:** lists both `packages/schemas` and `packages/experiment-spec`, and
  allows "JSON Schema or Zod/Pydantic".
* **Resolution:** Pydantic is authoritative; `packages/experiment-spec` holds the
  TS mirror and generated JSON Schema; `packages/schemas` is not created. See
  ADR-0002.

## A3. Model contract: class methods vs Protocol

* **Spec:** section 4.2 shows `Model.describe() / Model.run() / Model.validate()`
  as methods of a model class; section 10.1 defines a separate `ModelAdapter`
  Protocol with `describe/validate/run`.
* **Resolution:** implemented as a single instance-based `drw.adapter.ModelAdapter`
  Protocol (section 10.1 wins). `OdeModel` implements it. Helpers that need to
  build a model from an id go through `drw.models.registry`.

## A4. Units: no library named

* **Spec:** requires unit safety but does not name a units library.
* **Resolution:** minimal unit registry with opaque fallback; `pint` deferred. See
  ADR-0003.

## A5. `ExperimentSpec` field naming - RESOLVED

* **Spec:** section 7.3 names the field `analysis[]` (singular list).
* **Resolution (Milestone 2):** the canonical field is `analyses` (plural), and
  the singular `analysis` is accepted as an **input alias**, so a spec written
  using the specification's own field name validates. Supplying both is an error.
  The JSON Schema property is `analyses`. See ADR-0007.

## A6. No simulation-time controls in `ExperimentSpec`

* **Spec:** the `ExperimentSpec` sketch has no `t_span` / `n_points` / output grid.
* **Resolution:** simulation domain is a **model-level** property, fixed in each
  model's `build()` (for example oscillator `(0, 10)` with 201 points). An
  experiment varies *parameters*, not the integration window. This is a real MVP
  limitation: per-experiment time controls are not yet expressible.

## A7. Baseline accounting in the run count

* **Spec:** says the engine must "predict the number of runs", but does not say
  whether the baseline is part of the design matrix.
* **Resolution:** the baseline is always run exactly once (index 0) and is the
  frozen reference; total runs = `1 + variant_runs`. Consequence: a grid that
  contains the baseline point produces an extra run whose delta is exactly zero
  (observable in `models/examples/lorenz`, where `rho = 28` is both baseline and a
  grid node).

## A8. Garbled run-state machine

* **Spec:** section 8.3 renders as
  `DRAFT -> VALIDATED -> QUEUED -> RUNNING -> SUCCEEDED |-> FAILEDSUCCEEDED ->
  ANALYZED -> VERIFIED -> EXPORTED` (the `FAILED`/`SUCCEEDED` boundary is run
  together).
* **Resolution:** two chains are implemented:
  `DRAFT -> VALIDATED -> QUEUED -> RUNNING -> {SUCCEEDED, FAILED}`, and
  `SUCCEEDED -> ANALYZED -> VERIFIED -> EXPORTED`. `FAILED` and `EXPORTED` are
  terminal. See `drw.schema.result`.

## A9. Timeout enforcement - RESOLVED

* **Spec:** requires timeouts for local execution.
* **Resolution (Milestone 2):** `execution.isolation` defaults to `"subprocess"`,
  which runs each model in a child process and hard-kills the process tree at
  `timeout_s` (`timeout` diagnostic). `"in_process"` remains the fast path and
  does **not** enforce the timeout. A caller-supplied adapter instance (which
  cannot be rebuilt in a child) downgrades to in-process with an
  `isolation_downgraded` warning. See ADR-0005.

## A10. Solver names

* **Spec:** asks the UI to expose "Auto / explicit / stiff" and recommends "an
  explicit adaptive method" and "an implicit method", without naming them.
* **Resolution:** `auto` and `explicit` → `RK45`, `stiff` → `BDF`
  (`drw.numerics.ode.SOLVER_METHODS`). The actual method and tolerances are always
  recorded on the run.

## A11. Analysis methods beyond delta

* **Spec:** lists delta, relative delta, sensitivity, uncertainty, optimization,
  Jacobian, etc.
* **Resolution:** the runner implements `delta` and `relative_delta` (a single
  comparison artifact carries both). `sensitivity` is demonstrated as an
  **out-of-runner** one-at-a-time (OAT) ranking in the demo (`drw.demo`). Sobol /
  uncertainty / optimization are P1/P2 and are **not** implemented; the literal
  values are accepted by the schema but the runner emits no artifact for them.

## A12. Non-finite numbers in JSON

* **Spec:** requires machine-readable, reproducible artifacts.
* **Resolution:** `NaN`/`±Inf` are serialized as the strings `"NaN"` /
  `"Infinity"` / `"-Infinity"` so evidence files are always strict, valid JSON
  (strict JSON has no NaN literal). Relative-change points over a near-zero
  denominator are reported as `NaN` and flagged in diagnostics.

## A13. Environment fingerprint is machine-specific - REFINED

* **Spec:** requires an environment fingerprint and a reproducibility audit.
* **Resolution:** the fingerprint still records platform, CPU description and
  interpreter path for diagnosis. **Milestone 2 refinement:** `environment_hash`
  now hashes only the *semantic* environment (versions/platform/CPU) and excludes
  `python_executable`, so two machines with identical package versions but
  different venv locations agree. Reproducibility means "same spec, same code,
  same environment, same result" - not a globally identical hash.

## A14. Missing licence and budget scope

* **Spec:** the budget (`< R$5,000`) and pricing are hypotheses; no software
  licence is chosen for the project.
* **Resolution:** no `LICENSE` file is added (marking the choice explicitly
  deferred in the README) rather than picking one on the author's behalf.
