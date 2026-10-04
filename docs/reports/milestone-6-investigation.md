# Milestone 6 - investigation: scientific trust and reproducibility

Investigation only. **No production code was changed for this milestone.** This
document records what the current code and tests actually guarantee, what they
only describe, and the smallest evidence-backed improvements. Implementation is
gated on founder approval (Section 8).

Method: read the ADRs, runner, store, evidence, comparison/metrics, sensitivity,
serialization, sampling and solver code plus the relevant tests; ran the full
suites; and traced one experiment end to end (Section 2). Commands were run in
this session and the results below are as observed.

Environment: Windows 11, Python 3.14.6 (`.venv`), numpy 2.5.3, scipy 1.18.1,
pydantic 2.13.5; Node v24.17.0 / pnpm 11.9.0. **Not a git repository** (no VCS
state to preserve).

---

## 1. Baseline (commands actually run)

| Command | Result |
| --- | --- |
| `.venv\Scripts\python.exe -m ruff check packages/core/src tests scripts` | All checks passed |
| `.venv\Scripts\python.exe -m pytest -q` | **166 passed** in 63.22s |
| `pnpm -r typecheck` | exit 0 |
| `pnpm --filter @drw/experiment-spec test` | 5 pass / 0 fail |
| `pnpm --filter @drw/web test` | **44 passed** (6 files) in 64.71s |
| `pnpm --filter @drw/web build` | Compiled successfully; `/` 56.9 kB / 160 kB |

No flake was observed in this session. (The Milestone 5 subprocess-startup flake in
`Workspace.e2e.test.tsx` was recorded and fixed in M5; it did not recur here.)
`ruff format --check` is not a CI gate; see M5 report. Playwright/Chromium was not
run in this investigation (the M5 browser runs are the latest browser evidence).

---

## 2. End-to-end trace (one experiment)

Trace of `models/examples/predator-prey/experiment.yaml` through the CLI:

* **Spec → validate:** `.venv\Scripts\python.exe -m drw validate models/examples/predator-prey/experiment.yaml`
  → `estimated runs: 2 (method=grid)`, `no diagnostics: spec is valid`.
* **Run → evidence:** `.venv\Scripts\python.exe -m drw run … --out <tmp>`
  → `experiment: exp-1d700f7ad478`, `isolation: subprocess`, `runs: 2 (2 succeeded, 0 failed)`,
  `comparisons: 2` (`prey max_abs_delta=5.66464`, `predator max_abs_delta=2.20611`),
  manifest written.
* **Package contents & independent hash check:** `manifest.json` lists 4 hashed
  artifacts - `experiment-spec.json`, `model-schema.json`, `results.json`,
  `report.md`. Recomputing SHA-256 with a hand-written 6-line script: **all 4 OK**
  (hash and size). Manifest also carries `spec_hash 1d700f7ad478…`,
  `model_hash cf6031c2b0a9d180…`, `environment_hash 703a19c9ad79f154…`,
  `n_runs 2`, `counts {succeeded: 2}`, `run_ids [exp-1d700f7ad478-r0000, -r0001]`,
  `analyses [delta, relative_delta]`.
* **Tamper behaviour:** appending one byte to `results.json` → recomputed hash
  **mismatch** (and size mismatch); restoring → match. Detection is possible only
  by the manual recompute - no product code performs it.
* **Persistence / overwrite:** through `ExperimentStore`, running the identical
  spec twice produced the **same** id `exp-ddbd2c05f2d2`, and the store contains a
  **single** experiment directory (list count 1). Reopened spec equals the stored
  spec byte-for-byte (JSON-equal). Evidence package + `evidence.zip` produced.
* **What a persisted run records:** `inputs` (full resolved baseline), `seed`,
  `environment` (versions/platform/CPU), `isolation`, `status`, `timed_out`,
  `attempt`, `parent_run_id`, `started_at`/`finished_at`, `duration_s`, `metrics`,
  and `result` (outputs + axis + diagnostics). The **solver is recorded only as a
  free-text info diagnostic** (`method=RK45 rtol=1e-09 atol=1e-12 nfev=1088`).
  `t_span` (the integration window) is **not recorded anywhere**; grid size is only
  inferable from the output axis / comparison `n_points`.

---

## 3. A. Evidence integrity

**A1. Which artifacts are hashed; what is covered - STRENGTH.**
`build_evidence_package` (`packages/core/src/drw/execution/evidence.py`) writes and
SHA-256-hashes exactly four files: the spec, the model schema, the results
(`experiment_id`, `runs`, `comparisons`) and the Markdown report. Each entry
records `path`, `kind`, `sha256`, `size_bytes`. Directly tested by
`tests/integration/test_end_to_end.py::test_evidence_package_manifest_hashes_are_correct`
and confirmed by my independent recompute. The manifest also carries `spec_hash`,
`model_hash`, `environment_hash`, counts, run ids and analyses.

**A2. The exported package CAN be independently verified, but only by hand - CONFIRMED GAP.**
Evidence: `python -m drw -h` lists subcommands `{list-models, describe, validate,
run, demo, export-schemas}` - **no `verify`**. `drw.api` exposes no `verify_evidence`
op. `ExperimentStore.evidence()` reads `manifest.json` and `report.md` but
**recomputes no hashes** (`packages/core/src/drw/store.py`). Prior milestone reports
claim "0 hash mismatches" via an ad-hoc script that is **not in the repository**
(`scripts/` contains only `export_schemas.py` and `start-local.ps1`).
Why it matters: the manifest exists precisely so a third party can check a package;
today that check is manual and easy to skip.
Severity: **Medium** (trust feature). Classification: confirmed capability gap.
Smallest correction: add `verify_evidence(manifest_path) -> EvidenceVerification`
in `drw.execution.evidence` that recomputes every listed hash and reports
`ok / missing / modified / size_mismatch / extra_files`; expose it as a `verify`
CLI subcommand and a `verify_evidence` bridge op (read-only). Acceptance test:
build a package, verify → ok; mutate one byte / delete a file / add an unlisted
file → each reported with a stable code. **No evidence-format or stored-data change.**

**A3. Missing/modified/mismatched files are not detected by any code path - CONFIRMED GAP (same root as A2).**
Evidence: `store.evidence()` returns the manifest's `files` list without touching
the files; nothing in the runner, store or bridge compares hashes. Consequence:
today a deleted or edited artifact is silently ignored; only a manual recheck
finds it. Corrected by A2.

**A4. `manifest.json` is not self-hashed and there is no signature - LIMITATION (acceptable).**
Evidence: only the four artifacts appear in `files`; the manifest that contains the
hashes is not itself covered, and there is no HMAC/signature. Consequence: the
package detects accidental corruption/inconsistency, not a determined forger who
rewrites a file and the manifest. This is a consistency check, not tamper-proofing.
Document as such; do **not** add crypto/signing infrastructure in this milestone.

**A5. Failures not clearly reported - CONFIRMED GAP (same root).**
There is no verifier, so there is no "verification failed" message. A2 supplies the
first clear reporting.

---

## 4. B. Reproducibility

**B1. What is recorded - STRENGTH.** The spec records hypothesis, `model_ref` with
version, baseline, factors, outputs, `sampling.method/n_samples/seed`, constraints,
`analyses`, `execution` (solver, `timeout_s`, `max_runs`, isolation, workdir) and
`verification` (rtol/atol/relative_epsilon/checks). Each run records resolved
`inputs`, `seed`, `environment`, `isolation`. The environment fingerprint records
platform/machine/CPU, Python version+implementation, numpy/scipy/pydantic versions
and the `drw_core` distribution version; `environment_hash` excludes only the
interpreter path (`tests/unit/test_reproducibility.py`). Comparisons record the
alignment strategy, interpolated flag, axis, series and metrics.

**B2. Solver settings are recorded only as free text - LIMITATION.**
Requested `solver`/`rtol`/`atol` are structured in the spec; the **actual** method
and tolerances are an info diagnostic string (`code="solver"`), not structured
fields on the run. Reproducible, but not machine-queryable and not asserted by any
test. A structured change alters the results/evidence schema → **approval required**
(see S1). Recommended now: document only.

**B3. Integration window (`t_span`) is not recorded - LIMITATION (documented ambiguity A6).**
`OdeModel` fixes `t_span`/`n_points` in `build()` and neither is in the
`ModelSchema`, the spec, or the manifest. My trace confirms `t_span` appears
nowhere in `results.json`; `n_points`/axis length is the only hint. Consequence: the
declared contract alone cannot reconstruct the simulation domain; the results axis
can. Adding it changes `model_hash`/evidence → **approval required** (S2).

**B4. Sampling determinism - STRENGTH with a test gap.**
`sampling.py` is deterministic: grid is a fixed Cartesian product; random/LHS/Sobol
are seeded (`numpy.default_rng(seed)`, `scipy.stats.qmc` with `seed`).
`tests/unit/test_sampling.py` proves **grid order** and **random same-seed
determinism** and that stochastic designs stay in bounds. **LHS and Sobol
same-seed determinism is not asserted** (only bounds) - see D-gaps. scipy's qmc
algorithms may change across scipy versions; cross-version determinism is not
guaranteed.

**B5. Repeated run: OVERWRITE, not a new record - documented behaviour.**
`Runner.run` derives `experiment_id = f"exp-{spec_hash[:12]}"`; `ExperimentStore.save`
uses `mkdir(exist_ok=True)` and rewrites. My trace: two identical runs → one id, one
directory. This is intentional and documented (M4.5 report risk #4, ADR-0012);
preserve it. Consequence: two identical runs are not retained as separate history.

**B6. Legitimate guarantees.**
* *Identical inputs:* yes - identical spec ⇒ identical `spec_hash`; identical model
  ⇒ identical `model_hash` (same code/version). Proven by
  `test_repeated_execution_is_reproducible`.
* *Numerically equivalent outputs:* yes for the same spec + code + environment +
  seed; the test asserts exact equality of the delta tuples and `max_abs_delta` to
  `rel=1e-12` for a fixed environment. Cross-machine/BLAS bit-equality is **not**
  guaranteed.
* *Byte-identical artifacts:* **no.** `report.md`, `results.json` and the manifest
  contain `started_at`/`finished_at`/`duration_s`/`generated_at`, which vary per
  run. Do not claim byte-identical packages.

**B7. Identity safety - STRENGTH.** `experiment_id`/`run_id` patterns are strict and
path-contained; the id is a pure function of the spec content (not the clock).

---

## 5. C. Numerical and scientific interpretation

**C1. Failure representation - STRENGTH.**
* Solver reports `success=False` → `FAILED` + `solver_failed`, no outputs.
* Non-finite solution → `FAILED` + `non_finite_output` (state index + grid step),
  no outputs (ADR-0006); non-finite initial state → `non_finite_initial_state`;
  non-finite derived scalar dropped with a warning.
* Solver raised → `solver_exception` → `FAILED`.
* Timeout → `FAILED`, `timed_out=True`, diagnostic `timeout` (process tree killed,
  ADR-0005). Cancellation → `cancelled`; crash/malformed response →
  `worker_crash` / `invalid_worker_response` / `worker_model_error`. All tested in
  `tests/unit/test_isolation.py`.
* Invariant *"SUCCEEDED only when every output value is finite"* holds.

**C2. Non-finite / incomplete data in comparisons - STRENGTH.** Non-finite pairs are
masked and counted (`valid_points`, `non_finite_points`); relative change is NaN
where `|reference| <= relative_epsilon` plus an `unsafe_relative_denominator`
warning; no finite pairs → all-NaN metrics + `no_finite_pairs` error. A missing
output → `output_missing_for_comparison` and the other outputs still compare; a
mismatched grid → `comparison_failed` but the rest continue
(`test_delta_nonfinite.py`, `test_analysis_robustness.py`).

**C3. Metrics are mathematically defined and tested - STRENGTH.**
MAE, RMSE, max-abs-delta, signed area delta, peak shift, Pearson correlation, and
Wasserstein distribution distance (`metrics.py`), with known-value tests
(`test_metrics.py`) including shape-mismatch rejection and NaN correlation for
constant series.

**C4. Relative-change formula drift - CONFIRMED DOCUMENTATION DEFECT.**
`delta.py`'s module docstring (line 6) and `docs/testing/acceptance-matrix.md` row
13 state `r = Δy / max(|y_ref|, ε)`, but the code and ADR-0006 use "NaN where
`|reference| <= relative_epsilon`, else `Δy / y_ref`". The two differ where
`|y_ref| <= ε`: the documented formula yields `Δy/ε` (a finite but meaningless
number); the code yields NaN + warning. The code matches ADR-0006 and is safer.
Severity: **Low** (documentation only). Classification: confirmed defect (docs).
Smallest correction: fix the two doc locations to describe the masking behaviour.
Acceptance test: none required (behaviour is already pinned by
`test_delta_nonfinite.py`); a reviewer checks the wording.

**C5. Sensitivity assumptions documented - STRENGTH, one test gap.**
`drw/sensitivity.py` documents `PERTURBATION=1.10`, bound clamping (with `clamped`
flag and actual `perturbed_value`), the zero-nominal additive fallback, elasticity
normalization, and that OAT is local and cannot detect interactions. Surfaces in
the CLI, bridge and UI. **No dedicated unit test** exists for `perturbed_value` /
`elasticity` / ordering (covered indirectly by `test_projects_and_api_m4` and the
live browser run) - see D-gaps.

**C6. Numerical verification vs scientific validity - mostly clear, one ambiguity.**
The UI distinguishes observations from conclusions (M5) and OAT caveats are stated.
But `RunStatus` defines `ANALYZED → VERIFIED → EXPORTED`, and `verification.checks`
is accepted, yet **neither is ever applied to a real run**: grep shows
`ANALYZED`/`VERIFIED`/`EXPORTED` referenced only in `schema/result.py` and
`tests/unit/test_run_state.py`; `verification.checks` is never read. `run-lifecycle.md`
states the tail is "for later milestones", so this is documented - but the words
"VERIFIED"/"checks" could be misread as scientific validation. Classification:
documented limitation + transparency risk. Recommend a one-line clarification in
the lifecycle doc (docs only).

**C7. Units - LIMITATION (documented, ADR-0003).** Compound units are opaque labels
(`N/m` and `kg*m/s**2` are not equated). Comparison units come from the schema and
are recorded, but no dimensional conversion is attempted.

---

## 6. D. Existing test coverage

**Guarantees with direct automated tests**

| Guarantee | Test |
| --- | --- |
| Canonical hashing stable across processes; env hash ignores interpreter path | `unit/test_reproducibility.py` |
| Evidence manifest hashes/sizes correct | `integration/test_end_to_end.py` |
| Repeat run ⇒ identical id/spec_hash and equal deltas | `integration/test_end_to_end.py` |
| Comparison metric definitions | `unit/test_metrics.py` |
| Non-finite masking/counting; undefined relative change | `unit/test_delta_nonfinite.py` |
| Alignment exact/interpolate/resample disclosure | `unit/test_alignment.py` |
| One bad output doesn't abort analysis | `unit/test_analysis_robustness.py` |
| Timeout/cancel/crash/malformed-worker codes | `unit/test_isolation.py` |
| Run state-machine legality + terminal states | `unit/test_run_state.py` |
| Grid order + random seeded determinism; bounds | `unit/test_sampling.py` |
| Schema drift vs committed JSON Schema + TS mirror | `integration/test_schema_contract.py`, `experiment-spec` test |
| Scientific golden values (analytic oscillator, LV invariant, Lorenz) | `tests/scientific/*` |
| Sensitivity ranking (integration/live) | `integration/test_projects_and_api_m4.py`, live browser |

**Tests that assert implementation detail rather than the scientific property.**
* `unit/test_run_state.py` asserts transition edges only; the `ANALYZED/VERIFIED/
  EXPORTED` tail is never exercised on a real run, so it proves the table, not
  that runs are ever verified/exported.
* `test_enforced_limits_are_reported_honestly` asserts the honest-limits dict, not
  enforcement - appropriate, but it is a contract test, not a scientific one.

**Important failure cases that remain untested**
1. **Tamper / missing / mismatched evidence file** - not tested because no verifier
   exists to test (A2/A3).
2. **LHS and Sobol same-seed determinism** - only bounds are asserted.
3. **Sensitivity math** (`perturbed_value`, `elasticity`, ordering, zero-nominal
   fallback) - no unit tests.
4. **Solver info persistence** - nothing asserts the solver string survives into
   the stored `results.json`.
5. **Store-level overwrite of an identical spec** - I verified it manually
   (trace), but no test pins it.
6. **Cross-run byte-difference vs numerical-equality** - the *correct* distinction
   is implied but not asserted.

---

## 7. Confirmed defects vs speculative improvements vs limitations

**Confirmed defects / gaps**
* **D1 (Medium, implementation gap):** no first-party evidence verifier; missing/
  modified files are undetected by code (A2, A3, A5).
* **D2 (Low, documentation defect):** relative-change formula documented as
  `Δy/max(|y_ref|,ε)` in `delta.py` and the acceptance matrix, contradicting the
  code and ADR-0006 (C4).

**Documented limitations / acceptable behaviour (document now, change only with approval)**
* `manifest.json` not self-hashed, no signature (A4).
* Solver settings only free-text (B2); `t_span`/`n_points` not in the contract (B3).
* `verification.checks` inert; `ANALYZED/VERIFIED/EXPORTED` unused (C6).
* Identical-spec overwrite (B5); byte-identical artifacts not guaranteed (B6).
* Cross-platform/BLAS bit-determinism not guaranteed (B6, B4).
* Isolation is not a sandbox; units are opaque (C7).

**Speculative improvements (NOT defects; only if requested)**
* S1 structured solver/rtol/atol on the run record (changes evidence format).
* S2 record `t_span`/`n_points` in model metadata (changes `model_hash`).
* S3 extra tests: sensitivity unit tests, LHS/Sobol determinism, solver-string
  persistence, store-overwrite.
* S4 a package-level status/signature (new infrastructure - out of scope).

---

## 8. Recommended smallest scope (for approval)

Implement **D1 + D2 only** - both are additive and do **not** change stored-data
semantics, experiment identity, scientific methodology, or compatibility, so they
do not trigger the stop-and-ask condition:

1. **Evidence verifier (D1).** `verify_evidence(manifest_path)` in
   `drw.execution.evidence` + `verify` CLI subcommand + `verify_evidence` bridge
   op + a UI "Verify package" action is optional. Tests: ok / modified / missing /
   size-mismatch / extra-file, plus a round-trip against a freshly built package.
   *Acceptance:* a tampered artifact is reported by code with a stable code, and an
   untouched package verifies OK.
2. **Docs correction (D2).** Align `delta.py`'s docstring and the acceptance matrix
   with the implemented masking behaviour.
3. **Documentation of the limitations** above in the milestone report and, where
   relevant, the ADRs/acceptance matrix (no code change).

**Explicitly out of scope unless separately approved:** any change to the evidence
format, `RunRecord`/`ModelSchema`, deterministic ids, overwrite behaviour, or
`model_hash` (S1, S2, S4).

**Decisions requiring founder sign-off before implementation:**
* Approve D1 as in-scope (it adds a new bridge op and CLI subcommand).
* Confirm S1/S2 remain deferred (they change stored-data format / model identity).
* Confirm no change to overwrite semantics.

If the founder prefers zero new surface, the fallback is D2 + documentation only,
with a repo-local verification *script* (not a product op) as the minimal D1
alternative - still no format change.

---

## 9. Checks not run / inconclusive

* Playwright/Chromium browser suites were not re-run in this investigation (M5 is
  the latest browser evidence); whether the M5 UI changes interact with anything
  here is **not re-verified** in a browser this session.
* Cross-machine / cross-OS reproducibility was **not** tested (single Windows host).
* `ruff format --check` is not clean repo-wide (pre-existing; not a CI gate).
* No security/tamper-proofing evaluation (explicitly out of scope).
