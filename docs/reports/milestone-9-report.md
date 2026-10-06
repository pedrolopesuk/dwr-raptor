# Milestone 9 - global variance-based sensitivity (Sobol indices)

An **on-demand** global sensitivity study: first-order `S_i` and total-order
`S_Ti` Sobol' indices for a scalar output over independent input factors. Reuses
the existing `Runner` and the seeded Sobol' quasi-Monte Carlo sampler; no numerical
engine is duplicated, nothing is persisted, and all prior contracts are unchanged.

## 1. Verdict

**PASS.** Implemented across core, CLI, bridge and web; validated against the
analytic Ishigami function and additive/interaction/constant/no-effect cases. One
prototype defect (a collinear A/B design) was found and fixed during development
(§2). No schema, evidence-format, ID, overwrite, delta, OAT, uncertainty or
reproduce behaviour changed; no new dependency; no parallelism.

## 2. Files and interfaces changed

| File | Change |
| --- | --- |
| `packages/core/src/drw/global_sensitivity.py` | **new** — Saltelli design, Jansen/Saltelli estimators, bootstrap diagnostics, `SobolReport`, `GlobalSensitivityError`, `sobol_indices`, `sobol_indices_for_experiment` |
| `packages/core/src/drw/api.py` | read-only `global_sensitivity` op (+ job-journal progress) |
| `packages/core/src/drw/cli.py` | `drw sobol` command |
| `apps/web/src/lib/{types,client,handlers,directClient}.ts` | `SobolReport` types + `globalSensitivity` |
| `apps/web/src/app/api/experiments/[id]/global-sensitivity/route.ts` | **new** POST route |
| `apps/web/src/components/GlobalSensitivityPanel.tsx` | **new** panel |
| `apps/web/src/components/Workspace.tsx` | renders the panel once a stored experiment is active |
| `apps/web/src/test/stubClient.ts` | Sobol fixture + stub method |
| tests | `tests/unit/test_global_sensitivity.py`, `tests/scientific/test_sobol_ishigami.py`, `tests/integration/test_global_sensitivity_workflow.py`, `test_cli.py`, `test_api_bridge.py`, `apps/web/src/components/GlobalSensitivityPanel.test.tsx`, `Workspace.m5.test.tsx` |
| docs | `docs/methods/global-sensitivity.md`, `docs/architecture/ADR-0014-global-sensitivity.md`, `CHANGELOG.md`, `README.md`, `docs/testing/acceptance-matrix.md`, this report |

## 3. Estimator formulas and sampling design

Saltelli coupled design: one `2d`-dimensional N-point scrambled Sobol' sample is
split into `A` and `B` (`d` columns each); `AB_i` replaces column `i` of `A` with
`B[:, i]`. Evaluations = `N*(d+2)`. Estimators:

```
V    = var([f(A), f(B)], ddof=1)
S_i  = (1/N)  Σ f(B)_j (f(AB_i)_j − f(A)_j) / V      # Saltelli et al. 2010
S_Ti = (1/2N) Σ (f(A)_j − f(AB_i)_j)² / V            # Jansen 1999
```

Recorded as `saltelli2010_first_order+jansen1999_total_order`. A percentile
bootstrap interval is a **diagnostic only**. Estimates are **never clipped**.

**Defect found and fixed during development:** the first prototype built `A`/`B`
as two consecutive blocks of one `d`-dimensional sequence; measured column
correlation was ~0.9999, biasing indices (a product-model `S_1` came out exactly 0).
Switched to the correct `2d`-sample split; the analytic benchmarks below then hold.

## 4. Independent Ishigami reference (a=7, b=0.1, x∈[-π,π]³, seed 20240607)

Analytic: `S1=0.3139, S2=0.4424, S3=0, ST1=0.5576, ST2=0.4424, ST3=0.2437`, `V=13.8446`.

| N | S1 | S2 | S3 | ST1 | ST2 | ST3 | max abs error |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 256 | 0.3295 | 0.4355 | −0.0368 | 0.5416 | 0.4392 | 0.2403 | 0.0368 |
| 1024 | 0.3103 | 0.4399 | 0.0031 | 0.5533 | 0.4454 | 0.2421 | 0.0043 |

Errors shrink with N (tolerance 0.06 at N=256, 0.025 at N=1024, justified by
`O(1/√N)` Monte-Carlo behaviour). `S3 = −0.0368` at N=256 is reported **unclipped**.

## 5. Additive and interaction benchmarks

| Case | N / seed | var (analytic) | S (analytic) | ST (analytic) |
| --- | --- | --- | --- | --- |
| `f=x0+2x1` (additive) | 512 / 1 | 0.4171 (0.41667) | 0.1997, 0.7992 (0.2, 0.8) | 0.1998, 0.7992 (= S) |
| `f=x0·x1` (interaction) | 1024 / 2 | 0.04863 (0.04861) | 0.4275, 0.4278 (0.4286) | 0.5718, 0.5711 (0.5714) |

The additive case has `S_T ≈ S`; the interaction case has `S_T > S` (interaction
share ≈ 0.144), as expected. Constant output → `inconclusive` (zero variance);
a no-effect factor → indices ≈ 0.

## 6. Evaluation counts, failure semantics, determinism, data preservation

* Explicitly tested: `evaluations_requested = evaluations_completed = N*(d+2)`.
* **Fail-closed:** a failed/timed-out/missing/non-finite evaluation makes the study
  `inconclusive` (indices `null`) with counts/reasons; zero/non-finite variance is
  `inconclusive`. Invalid factor/output/bounds, `N<2`, duplicate factors and
  over-cap studies are rejected (`GlobalSensitivityError` → CLI exit 2 / bridge
  `bad_request`).
* Determinism: identical report for a fixed seed (unit + scientific tests).
* Data preservation: the integration test snapshots every file under the stored
  experiment before/after a study and asserts equality (the study never writes).

## 7. Validation (exact commands, actual results)

| Command | Result |
| --- | --- |
| `.venv\Scripts\python.exe -m ruff check packages/core/src tests scripts` | All checks passed |
| `.venv\Scripts\python.exe -m pytest -q` | **262 passed** in 247.69s (was 237; +25) |
| `pnpm -r typecheck` | exit 0 |
| `pnpm --filter @drw/experiment-spec test` | 5 pass / 0 fail |
| `pnpm --filter @drw/web test` | **62 passed** (9 files) in 79.18s (was 58; +4) |
| `pnpm --filter @drw/web build` | Compiled successfully; `/` 60.8 kB / 164 kB |
| `pnpm --filter @drw/web e2e:only` (Chromium) | **5 passed** in 44.6s |

## 8. Known limitations and unverified behaviour

* **Independent inputs only** — correlated-input sensitivity is not implemented and
  is stated as a limitation (not a defect).
* **Scalar outputs only** for this version; no time-series global sensitivity.
* Estimates are finite-sample; a bootstrap interval is not proof of convergence,
  and the study is not causal.
* Runtime is `N*(d+2)` sequential model evaluations; the default is bounded
  (`N=32`, cap 4096) and the estimate is surfaced.
* The result is **not persisted** (on demand); a persistent artifact was
  deliberately deferred.
* No new browser E2E step for the Sobol panel (the editor cannot author a study);
  the panel is unit-tested and the existing Chromium suite is unchanged.

## 9. Compatibility

No `ExperimentSpec`/`ModelSchema`, evidence-manifest, deterministic-ID, overwrite,
delta/relative-delta, OAT, M8 uncertainty, M7 reproduce, or isolation-terminology
change. No new dependency; no parallelism; local-first unchanged. The bridge op is
read-only w.r.t. the store; the CLI/UI run model evaluations through the existing
subprocess isolation.

## 10. Scope

No calibration, optimization, parallelism, new models, correlated-input methods,
new infrastructure/dependencies, evidence-format/schema/ID changes, or unrelated
refactors. Milestone 10 was not started.
