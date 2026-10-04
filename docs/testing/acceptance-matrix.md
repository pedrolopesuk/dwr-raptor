# DRW acceptance matrix

Every user-facing capability, the test that covers it, and the **actual** result
observed in this milestone. Where a capability is not implemented it is marked
**UNSUPPORTED**; where it could not be exercised **NOT VERIFIED**; where only part
is covered **PARTIAL**.

Test names: `PY` = Python suite (`tests/**`), `WEB` = Vitest (`apps/web/src/**/*.test.tsx`),
`ISO` = isolated Playwright (`apps/web/e2e/workspace.spec.ts`),
`LIVE` = live Playwright (`e2e/local-acceptance.spec.ts`, `e2e/accessibility.spec.ts`).

| # | Feature / scenario | Expected behaviour | Test(s) | Scientific criteria | Result | Limitations |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | App startup & model discovery | 3 registered models listed; page renders; picker lists all three | WEB `handlers.test` lists models, `Workspace.m5` picker; ISO step 1-2; LIVE step 1-2 | — | **PASS** | — |
| 2 | Projects: list / create / select | Projects listed; creation persists; selection filters | PY `test_projects_and_api_m4`; WEB `Workspace.m4` projects | — | **PASS** | No rename/delete/ownership |
| 3 | Experiment ↔ project association | `project_id` stored in meta; filter works | PY `test_projects_and_api_m4` | — | **PASS** | Legacy rows read as `default`, never rewritten |
| 4 | Model & experiment configuration | Baseline + intervention assemble a valid `ExperimentSpec`, for any selected model | WEB `Workspace.m4`, `Workspace.m5` (model-specific); LIVE step 3 | — | **PASS** | Single factor row per intervention in the UI |
| 5 | Input validation & errors | Engine diagnostics surfaced; Run stays disabled | PY `test_experiment_schema`; WEB `handlers.test`, `Workspace.test` (invalid); LIVE step 2 | Bounds/units enforced | **PASS** | — |
| 6 | Baseline vs intervention association | Baseline is run 0; comparisons reference it | PY `test_end_to_end`, `test_api_bridge`; LIVE step 4 | Δy = variant − reference | **PASS** | — |
| 7 | Sampling methods | grid/random/LHS/Sobol deterministic, in-bounds, correct counts | PY `test_sampling` | Same seed ⇒ same design; samples within bounds | **PASS** | UI offers grid only (single value / range); stochastic methods available via spec/CLI |
| 8 | Execution & persistence | Runs execute in isolation; results + evidence persisted | PY `test_end_to_end`, `test_api_bridge`; LIVE step 4 | — | **PASS** | Sequential; one process per run |
| 9 | Job progress | Journal events; "k of n runs completed" | PY `test_jobs`, `test_projects_and_api_m4`; WEB `Workspace.m4` progress | Progress is measured, not estimated | **PASS** | Poll-based (~0.7 s), coarse |
| 10 | Timeout | Hard kill; `timed_out`, code `timeout`, no outputs | PY `test_isolation`, `test_isolation_runner`; LIVE step 9; verification script | No non-finite output escapes | **PASS** | — |
| 11 | Cancellation | Abort kills the child; records `cancelled` | PY `test_isolation`; WEB `Workspace.test` cancellation | — | **PARTIAL** | Not browser-tested (no deterministic long-running model) |
| 12 | Failure propagation | Solver/non-finite/budget failures become `FAILED` with diagnostics | PY `test_ode_nonfinite`, `test_isolation_runner`; WEB `Workspace.test` never-success | Succeeded only when all outputs finite | **PASS** | — |
| 13 | Differential comparison | Absolute + relative delta, metrics, alignment recorded | PY `test_delta`, `test_metrics`, `test_alignment`, `test_golden_values` | Δy = variant − reference; r = Δy/y_ref where \|y_ref\| > ε else NaN (flagged); MAE/RMSE/max/area/peak/corr/Wasserstein | **PASS** | — |
| 14 | Missing values / NaNs / mismatched grids / zero denominators | Masked, counted, flagged; analysis never aborts | PY `test_delta_nonfinite`, `test_analysis_robustness` | Finite metrics over finite pairs; NaN where undefined | **PASS** | Masked metrics may be unrepresentative — disclosed |
| 15 | Sensitivity analysis | OAT +10% (bounds-clamped), peak metric, elasticity, sorted ranking | PY `test_projects_and_api_m4`; LIVE step 8 (β > α > 0) | Local one-at-a-time, **not** global/variance-based | **PASS** | Cannot detect interactions; `β·predator0` non-identifiability documented |
| 16 | Planner proposal → review → apply → validate → run | Proposal only; never bypasses validation or approval | PY `test_planner`, `test_projects_and_api_m4`; WEB `Workspace.m4` planner; LIVE step 13 | Spec must pass `validate_experiment` | **PASS** | LLM provider path **NOT VERIFIED** (no key); rule-based planner verified |
| 17 | Refresh / reload persistence | Stored spec returned unchanged | PY `test_api_bridge`; LIVE step 14b | — | **PASS** | Identical spec re-run overwrites its record (deterministic ids; preserved and documented, ADR-0012) |
| 18 | Evidence export & integrity | Manifest + SHA-256 per artifact; zip export | PY `test_end_to_end` hashes; LIVE step 14; verification script | 4 files, 0 hash mismatches | **PASS** | — |
| 19 | Offline operation (no LLM) | Rule-based planner; nothing leaves the machine | PY `test_planner` offline; LIVE planner note | — | **PASS** | — |
| 20 | Optional LLM configuration | Provider built from env; key never returned | PY `test_planner` `provider_status_never_exposes_a_key` | Key stays server-side | **PARTIAL** | HTTP client untested without a key |
| 21 | Invalid ids / malformed payloads / path containment | Rejected with stable codes; no escape from workspace | PY `test_api_bridge` (traversal, malformed), `test_projects_and_api_m4`; WEB `handlers.test` 400/404 | — | **PASS** | — |
| 22 | Windows process execution & filesystem | Subprocess tree kill; `.venv` resolution; workspace writes | PY `test_isolation`; LIVE on Windows; `start-local.ps1` | — | **PASS** | POSIX rlimits unavailable on Windows |
| 23 | Oscillator vs analytic reference | Matches closed form within tolerance | PY `test_oscillator_analytic` | max abs error ≤ 1e-6; measured **8.92e-11** (rtol 1e-10) | **PASS** | Underdamped case only |
| 24 | Lotka–Volterra invariant | Conserved quantity preserved | PY `test_predator_prey_invariant` | span < 1e-5 over the trajectory | **PASS** | — |
| 25 | Lorenz determinism & divergence | Identical config identical; perturbations amplify | PY `test_lorenz` | Fixed-config equality; early min → growth | **PASS** | Chaotic trajectories are not claimed identical indefinitely |
| 26 | Numerics: convergence, cross-method, equilibrium | Tighter rtol reduces error; RK45≈BDF; equilibrium stationary | PY `test_convergence` | Monotone error decrease; agreement < 1e-5; drift < 1e-6 | **PASS** | — |
| 27 | Reproducibility hashing | Canonical hashing stable cross-process; env hash ignores interpreter path | PY `test_reproducibility` | Same content ⇒ same digest | **PASS** | Determinism ≠ reproducibility proof; stated in ADRs |
| 28 | Accessibility (automated) | No serious/critical axe violations, light **and** dark | LIVE `accessibility.spec` (2 tests) | axe-core serious/critical = 0 | **PASS** | Automated only; no screen-reader test |
| 29 | Keyboard access | Skip link, sample action, project select, inputs, tabs operable | LIVE `accessibility.spec` keyboard test; LIVE step 11b | — | **PASS** | Verified for primary controls only |
| 30 | Responsive layout (<1055 px) | Sidebar stacks above main | CSS breakpoints in `globals.scss` | — | **NOT VERIFIED** | Not exercised in a browser at a narrow viewport this milestone |
| 31 | Secrets handling | Keys server-side, absent from client bundle | PY `test_planner`; no provider configured | — | **PARTIAL** | Bundle not scanned with a key configured |
| 32 | Teams / billing / cloud / auth | — | — | — | **UNSUPPORTED** | Out of scope by design |
| 33 | Arbitrary model upload / user code | — | — | — | **UNSUPPORTED** | Registry-only model ids; no imports |
| 34 | Global sensitivity / uncertainty quantification | — | — | — | **UNSUPPORTED** | Only OAT + point comparisons implemented |
| 35 | Non-Windows host | — | — | — | **NOT VERIFIED** | Only Windows 11 tested |
| 36 | Model-agnostic experiment creation (M5) | Every registered model can seed, validate and execute a new experiment | PY `test_api_bridge` (`test_every_registered_model_*`, 3 models); WEB `Workspace.m5`; ISO + LIVE browser runs | spec `model_ref` matches; validation ok; comparisons produced | **PASS** | Seeded config is a labelled demonstration (+10% on first input), not a justified experiment |
| 37 | Authoritative model metadata (M5) | Parameters show name/type/role/unit/nominal/bounds/**description** from the schema; capabilities + limitations shown | WEB `Workspace.m5` (`kg`, `Mass.`, `cap-factorable`/`cap-outputs`); ISO step 2 | UI values agree with `ModelSchema`; nothing inferred | **PASS** | Descriptions shown only where the schema declares them |
| 38 | Model eligibility, explained (M5) | Ineligible model disabled in the picker with a reason; eligibility is technical, not scientific | WEB `Workspace.m5` (ineligible model); `modelViability` unit tests | — | **PASS** | All 3 registered models are currently eligible; the disabled path is covered by test only |
| 39 | Observation vs. established conclusion (M5) | Results state they are simulated outputs under the configuration, not an established conclusion | WEB `Workspace.m5` (`observation-caveat`); LIVE step 6 | — | **PASS** | Text framing only; no scientific-claim engine |
| 40 | Evidence package verification (M6) | Every declared artifact exists and matches recorded size + SHA-256; undeclared files surfaced and not verified; read-only | PY `test_evidence_verify` (10), `test_api_bridge` verify op, `test_cli` verify + exit codes | Hashes recomputed with SHA-256; malformed/escaping entries rejected | **PASS** | Consistency check, **not** cryptographic authenticity (manifest is not self-hashed or signed) |

**Totals:** 32 PASS · 3 PARTIAL · 2 NOT VERIFIED · 3 UNSUPPORTED (40 rows).
*(The totals line was corrected in Milestone 5 from `30 PASS · 4 PARTIAL · 3 NOT VERIFIED · 4 UNSUPPORTED`, which did not match the table.)*
