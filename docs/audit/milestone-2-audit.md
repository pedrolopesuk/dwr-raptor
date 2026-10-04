# Milestone 2 audit: scientific trust and execution hardening

Scope: the Milestone 1 scientific core (`packages/core`), its tests, the
TypeScript contract package, and the docs. Date: 2026-10-03.

Method: read the specification, all ADRs, schemas, implementation and tests; then
probe the running system for each suspected weakness before changing code. No
finding below is asserted without a concrete reproduction.

## 1. Requirement -> code -> test map (implemented surface)

| Requirement (spec) | Code | Tests |
| --- | --- | --- |
| Typed model contract (§4.2) | `schema/model.py` | `unit/test_model_schema.py` |
| ExperimentSpec (§7.3) | `schema/experiment.py` | `unit/test_experiment_schema.py`, `integration/test_schema_contract.py` |
| Deterministic serialization/hashing (§9.3) | `schema/serialization.py` | `unit/test_serialization.py`, `unit/test_reproducibility.py` |
| Run state machine (§8.3) | `schema/result.py`, `execution/runner.py` | `unit/test_run_state.py` |
| ODE integration (§5.1) | `numerics/ode.py` | `unit/test_ode_adapter.py`, `unit/test_ode_nonfinite.py`, `scientific/*` |
| Sampling (§5.4) | `numerics/sampling.py` | `unit/test_sampling.py` |
| Delta analysis + metrics (§4.3, §10.5) | `numerics/delta.py`, `numerics/metrics.py` | `unit/test_delta.py`, `unit/test_delta_nonfinite.py`, `unit/test_metrics.py` |
| Time alignment (§10.4) | `numerics/alignment.py` | `unit/test_alignment.py` |
| Golden models (§11.1) | `models/*` | `scientific/*` |
| Local execution + evidence (§8, §11) | `execution/*` | `integration/test_end_to_end.py`, `integration/test_retry.py`, `integration/test_isolation_runner.py` |
| Isolation + timeout (§14) | `execution/isolation.py`, `execution/worker.py` | `unit/test_isolation.py`, `integration/test_isolation_runner.py` |
| CLI (§11) | `cli.py` | `integration/test_cli.py` |

## 2. Findings

Severity is `Critical` (unsafe to run) / `High` (wrong or misleading results, or
process loss) / `Medium` (misleading under specific inputs) / `Low`
(maintainability/consistency).

### SC-1 · High · Non-finite solver output could be reported as SUCCEEDED

* **Impact:** a diverged/overflowing run could enter comparisons as valid data.
* **Repro:** integrate `y' = y^2` on `[0, 10]`; inspect `status` and output
  finiteness.
* **Acceptance:** a run is `SUCCEEDED` only if every output value is finite; a
  non-finite solve produces a `non_finite_output` failure.
* **Status:** FIXED (`numerics/ode.py`; `unit/test_ode_nonfinite.py`).

### SC-2 · High · Missing data silently corrupted comparison metrics

* **Impact:** a series containing `NaN` yielded `mae`/`max_abs_delta` of `NaN`
  with no explanation and no point count.
* **Repro:** compare `[0,1,NaN,3]` with `[0,2,2,3]`; observe metrics.
* **Acceptance:** non-finite pairs are masked, `non_finite_series` is warned,
  `valid_points`/`non_finite_points` are recorded, and metrics stay finite when
  any finite pair exists.
* **Status:** FIXED (`numerics/delta.py`; `unit/test_delta_nonfinite.py`).

### EX-1 · Critical · `timeout_s` was not enforced

* **Impact:** an infinite loop or unbounded integration hangs the runner forever.
* **Repro:** run any slow model with `timeout_s=0.6` under Milestone 1; it is not
  interrupted.
* **Acceptance:** the process tree is killed at the deadline and the run is
  `FAILED` with a `timeout` diagnostic within a bounded time.
* **Status:** FIXED (`execution/isolation.py`; `unit/test_isolation.py`,
  `integration/test_isolation_runner.py`). See ADR-0005.

### EX-2 · High · No process boundary

* **Impact:** a model that segfaults, calls `sys.exit`, or exhausts memory takes
  the runner (and a future web process) down with it.
* **Acceptance:** model execution happens in a separate interpreter; a crashing
  worker yields a deterministic `FAILED` record, not a parent crash.
* **Status:** FIXED. Note: a caller-supplied adapter instance downgrades to
  in-process with an `isolation_downgraded` warning (cannot be rebuilt in a child).

### EX-3 · Medium · No cancellation mechanism

* **Status:** FIXED. `Runner.run(..., cancel_event=...)` kills a running child and
  marks not-yet-started runs `FAILED`/`cancelled`. Tests:
  `unit/test_isolation.py`, `integration/test_isolation_runner.py`.

### EX-4 · Medium · Artifact/path handling not contained

* **Status:** ADDRESSED. The worker writes only inside a private `mkdtemp` dir,
  is launched with `cwd` set there, and the dir is always removed; a test asserts
  no files are written into the caller's directory. Zip paths use
  `relative_to(root)`. (Full sandboxing remains out of scope - ADR-0005.)

### EX-5 · Medium · One incompatible output aborted the whole analysis

* **Impact:** a single shape mismatch raised `AlignmentError` out of
  `Runner._analyse`, losing all comparisons for the experiment.
* **Acceptance:** an incompatible output is skipped with a `comparison_failed`
  diagnostic; other outputs and other variants still compare.
* **Status:** FIXED (`execution/runner.py`; `unit/test_analysis_robustness.py`).

### EX-6 · Low · Runner bypassed the run state machine

* **Status:** FIXED. Runs now move `QUEUED → RUNNING → SUCCEEDED|FAILED` through
  `Runner._advance`, which enforces `allowed_run_transition`.

### SC-3 · Medium · OAT sensitivity was scale-dependent and clamp-distorted

* **Impact:** ranking by absolute delta favours large-magnitude parameters, and a
  perturbation clipped to a bound was reported as if it were the requested +10%.
* **Repro:** the Milestone 1 demo ranked `beta` (order 0.1) alongside `predator0`
  (order 1) by raw absolute delta.
* **Acceptance:** the artifact reports `elasticity` (relative response / relative
  input change), flags `clamped`, and documents that OAT cannot detect
  interactions.
* **Status:** FIXED (`demo.py`; `integration/test_cli.py` exercises the artifact).

### SC-4 · Medium · Only self-consistency and one analytic reference

* **Status:** ADDRESSED. Added an analytic oscillator error-vs-tolerance
  convergence test, a cross-method agreement test (RK45 vs BDF), and an analytic
  Lotka-Volterra equilibrium stationarity test
  (`scientific/test_convergence.py`).

### SC-5 · Low · Sampling semantics silently ignored

* **Status:** FIXED. `grid` + `n_samples` warns `n_samples_ignored`; stochastic
  sampling with a `steps` factor warns `factor_steps_ignored`
  (`numerics/sampling.py`; `unit/test_sampling.py`).

### SC-6 · Low · Duplicate Sobol warning

* **Repro:** `validate_experiment` and `estimate_run_count` both emitted the
  warning; the runner appended both lists.
* **Status:** FIXED via `dedupe_diagnostics` (`schema/experiment.py`), used by the
  runner, and the raw SciPy `UserWarning` is suppressed in favour of the
  structured diagnostic.

### SC-7 · Low · Parameter nominal/bounds not finite-checked

* **Status:** FIXED (`schema/model.py`; `unit/test_model_schema.py`).

### SC-8 · Low · Dead code (`_TERMINAL`)

* **Status:** FIXED. Replaced with exported `TERMINAL_STATES` and `is_terminal`.

### RP-1 · Medium · Environment hash included the interpreter path

* **Impact:** two machines with identical versions but different venv paths had
  different `environment_hash`, weakening reproducibility comparison.
* **Status:** FIXED. `fingerprint_hash` hashes the semantic environment and
  excludes `python_executable` (`execution/environment.py`;
  `unit/test_reproducibility.py`).

### RP-2 · Low · No cross-process hash test

* **Status:** FIXED (`unit/test_reproducibility.py` computes a hash in a child
  interpreter and compares).

### RP-3 · Low · Manifests are not byte-reproducible

* **Finding, not a defect:** `generated_at`/`started_at`/`duration_s` differ
  between runs, so `manifest.json` bytes differ even though the science is
  identical. Spec/model/environment hashes and comparison metrics are stable.
* **Status:** DOCUMENTED.

### CT-1 · Medium · `analysis[]` vs `analyses` unresolved

* **Status:** FIXED (`schema/experiment.py` accepts `analysis` as an input alias;
  canonical output remains `analyses`). See ADR-0007.

### CT-2 · Medium · No schema drift/parity test

* **Status:** FIXED (`integration/test_schema_contract.py`; TS test in
  `packages/experiment-spec/src/index.test.ts`).

### CT-3 · Low · `schema_version` never checked

* **Status:** FIXED. `schema_version_mismatch` warning. See ADR-0007.

### CT-4 · Low · TypeScript mirror lacked the new fields

* **Status:** FIXED. `ExecutionSpec.isolation` and `IsolationMode` added; the TS
  parity test asserts the contract's load-bearing fields.

## 3. Residual risks (not fixed in this milestone)

1. **Isolation is not a sandbox.** No filesystem or network restriction
   (ADR-0005). Do not run genuinely untrusted code.
2. **Timeout not enforced for caller-supplied adapter instances** (downgrade
   warning). Only registered models get hard timeouts.
3. **Sequential execution.** No parallelism; a large sweep is slow by design.
4. **OAT sensitivity only.** No variance-based global sensitivity; interactions
   and non-identifiability are not detected (SC-3 note).
5. **`pint`-grade units not implemented.** Compound units are opaque labels
   (ADR-0003).
6. **No per-experiment integration window.** `t_span`/`n_points` remain
   model-level (ambiguity A6).
