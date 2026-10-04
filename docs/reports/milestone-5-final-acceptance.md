# Milestone 5 - final report: model-agnostic experiment workflow

Incremental evolution of DRW from a sample-centred interface to a model-agnostic
experiment workflow, using capabilities already present in the Python core. This
is **not** a rewrite: no Python core, bridge, schema, storage or numerical change
was made. The web layer remains a thin orchestrator; Python remains authoritative.

---

## 1. What changed and why

The only real limitation was in the UI: `Workspace.openSample()` hardcoded
`"predator-prey"` and the model list was used only for a count (milestone-4.5 risk
#7). The core was already model-agnostic - `sample_experiment(model_id)` builds a
valid baseline-vs-+10% spec for every registered model (verified in Phase 1).

Changes:

* **Model picker** (`NewExperimentPanel`, rendered in the sidebar). Lists all
  registered models from `list_models`; creating an experiment calls the existing
  `sample_experiment(model_id)` + `describe_model(model_id)`. No new bridge op.
* **Technical eligibility, explained** (`lib/experiment.ts: modelViability`).
  Derived from `capabilities`; an ineligible model is disabled with the reason.
  The UI states eligibility is technical, **not** scientific validity.
* **Authoritative metadata** (`ModelPanel`). Now shows parameter/output
  `description` and a capabilities/limitations block - all straight from
  `ModelSchema`, nothing inferred.
* **Demonstration labelling** (`Workspace`). A seeded experiment is labelled as a
  demonstration (+10% on the first input), explicitly not a justified experiment.
* **Observation vs. conclusion** (`ResultsView`). Results state they are simulated
  outputs under the configuration, not an established scientific conclusion.
* **Preserved sample** as a regression-tested example (`start-sample` unchanged).
* **Deterministic ids / identical-spec overwrite preserved** and documented; not
  redefined (ADR-0012).

Recorded decision: `docs/architecture/ADR-0012-model-agnostic-experiments.md`.

---

## 2. Verification commands and actual results

All commands were run in this session; results are as observed.

| Command | Baseline (before) | Final (after) |
| --- | --- | --- |
| `.venv\Scripts\python.exe -m ruff check packages/core/src tests scripts` | All checks passed | **All checks passed** |
| `.venv\Scripts\python.exe -m pytest -q` | 160 passed | **166 passed** in 57.80s |
| `pnpm -r typecheck` | exit 0 | **exit 0** |
| `pnpm --filter @drw/experiment-spec test` | 5 passed | **5 passed** |
| `pnpm --filter @drw/web test` | 32 passed / 1 failed (flake) | **44 passed** (6 files) in 57.47s |
| `pnpm --filter @drw/web build` | exit 0 (`/` 55.4 kB / 158 kB) | **exit 0**, `/` 56.9 kB / 160 kB |
| `pnpm --filter @drw/web e2e:only` (Chromium, prod build) | not run this session | **4 passed** (32.6s) |
| live: `npx playwright test --config playwright.local.config.ts` (server on :3847) | not run this session | **4 passed** (42.4s) |

`pytest` grew by 6 (three models × {seed+validate, execute}). Web `vitest` grew
from 33 to 44 (new `Workspace.m5.test.tsx` = 7, `modelViability` unit tests = 4).

Formatting note: `.venv\Scripts\python.exe -m ruff format --check packages/core/src tests scripts`
reports **22 pre-existing files would be reformatted** (e.g. `drw/api.py`,
`drw/cli.py`, `drw/store.py`, and most test files) - a baseline condition, not
introduced here. `ruff format --check` is **not** part of CI (`.github/workflows/ci.yml`
runs `ruff check`, which passes). I did not reformat unrelated files, to avoid
large unrelated churn.

---

## 3. Files modified

Web (thin layer):
* `apps/web/src/components/Workspace.tsx` - model state, `openModel`, demo note, picker wiring.
* `apps/web/src/components/NewExperimentPanel.tsx` - **new** model picker.
* `apps/web/src/components/ExperimentsSidebar.tsx` - renders the picker.
* `apps/web/src/components/ModelPanel.tsx` - descriptions + capabilities/limitations.
* `apps/web/src/components/ResultsView.tsx` - observation-vs-conclusion note.
* `apps/web/src/lib/experiment.ts` - `modelViability`.
* `apps/web/src/test/stubClient.ts` - multi-model fixtures.
* `apps/web/src/components/Workspace.m5.test.tsx` - **new**; `Workspace.e2e.test.tsx` - timeout hardening.
* `apps/web/src/lib/experiment.test.ts` - `modelViability` tests.

Python (tests only; **no core change**):
* `tests/integration/test_api_bridge.py` - all-models seed/validate/execute.

Docs:
* `docs/reports/milestone-5-baseline.md`, `docs/reports/milestone-5-final-acceptance.md` (this file),
  `docs/architecture/ADR-0012-model-agnostic-experiments.md`,
  `docs/testing/acceptance-matrix.md`, `CHANGELOG.md`, `README.md`.

**Not modified:** `packages/core/src/**`, `drw.api` ops, schemas, `drw.store`,
`packages/experiment-spec/**`.

---

## 4. Regression results

* The predator-prey sample workflow is asserted unchanged by `Workspace.test.tsx`,
  `Workspace.m4.test.tsx`, `Workspace.e2e.test.tsx`, the isolated
  `workspace.spec.ts` browser run, and the live `local-acceptance.spec.ts`
  browser run (all green).
* All 160 pre-existing Python tests still pass; the schema-contract, persistence
  and evidence-integrity suites are unaffected (no core change).
* `handlers.test.ts` (real bridge, node env) still passes, including the run /
  evidence / sensitivity path against the real Python core.
* Acceptance matrix: 4 new rows (36-39). A pre-existing totals error in the
  matrix (`30 PASS · 4 PARTIAL · 3 NOT VERIFIED · 4 UNSUPPORTED`, which did not
  match its own table) was corrected to **31 PASS · 3 PARTIAL · 2 NOT VERIFIED ·
  3 UNSUPPORTED** and flagged in the file.

---

## 5. Browser evidence

* **Isolated** (`pnpm --filter @drw/web e2e:only`, own throwaway workspace):
  3 accessibility tests (axe light+dark, keyboard) + 1 workspace test - **4 passed**.
  The workspace test drives open → configure → reject invalid → run → plots →
  metrics → sensitivity → export → reopen → timeout.
* **Live** (production server, throwaway workspace, `DRW_BASE_URL`): the same
  4 tests, including the full live acceptance walkthrough, **4 passed**.
* Screenshots written by the live spec: `apps/web/test-results/drw-sample-loaded.png`
  and `apps/web/test-results/drw-results.png` (timestamp 2026-10-04 01:56).
* **Caveat on visual review:** a vision-assisted read of the screenshot returned
  text that does **not** match the shipped copy (e.g. it reported "v0.0.0" and a
  button "Create experiment (Ctrl+Enter)"). The shipped copy was independently
  confirmed present in the production bundle (`.next/static/chunks/app/page-*.js`
  and `.next/server/app/page.js` contain "Open sample project (predator-prey)",
  "scientifically justified experiment", "not an established scientific
  conclusion"). I therefore rely on the passing Playwright/component assertions
  and the bundle grep, **not** the vision description. Manual visual review of the
  screenshots is not claimed.

---

## 6. Scientific claims: verified vs. assumed

**Verified this session**
* Every registered model (`oscillator`, `lorenz`, `predator-prey`) seeds,
  validates and **executes** through the bridge, producing 2 successful runs and
  comparison artifacts (`tests/integration/test_api_bridge.py`).
* UI parameter metadata agrees with the authoritative `ModelSchema` (component
  tests assert `kg`, `Mass.`, and the capability output sets).
* Deterministic `exp-<hash12>` ids and identical-spec overwrite are unchanged
  (code inspection + pre-existing tests).

**Explicitly not claimed**
* The seeded +10% configuration has **no** established scientific meaning; the UI
  says so. No downstream interpretation is made by the platform.
* No new numerical algorithm or scientific capability was added, and this
  milestone did **not** re-derive any analytic/golden value; the existing
  scientific tests simply continue to pass.
* Full scientific validation and production readiness are **not** claimed.

---

## 7. Timing-sensitive test flake: investigation and outcome

Recorded in `docs/reports/milestone-5-baseline.md`. `Workspace.e2e.test.tsx` (the
only web test that spawns real Python) failed at its first assertion under
parallel load: two sequential subprocess spawns exceeded Testing Library's default
1s `findBy*` timeout. It passed standalone (22.9s). Fix: an explicit 60s timeout on
the Python-dependent assertion (root cause = process startup, not a product
defect). After the fix, the full web suite (including that spec) ran **44/44
passed**. The flake did not recur post-fix.

---

## 8. Known limitations, unresolved decisions, work not completed

* The **ineligible-model** branch is covered by unit/component tests with a
  synthetic model; no *real* registered model is ineligible, so it is not exercised
  end-to-end.
* The seeded spec's name remains `"DRW killer demo"` (`build_demo_experiment`);
  relabelling is UI-side. A neutral seed builder is deferred (ADR-0012).
* Deterministic ids / identical-spec overwrite unchanged by design (documented).
* Pre-existing, still **NOT VERIFIED**: the optional LLM provider HTTP path (no
  key); screen-reader access; <1055 px responsive layout; non-Windows hosts.
  Isolation remains a process boundary, **not** a sandbox.
* No new ADR beyond ADR-0012; no other milestone started.

---

## 9. Data preservation

* The real workspace `.drw/web-workspace` was **not touched** - its directories'
  last-write times predate this session (03/10 23:29-23:30); its 4 experiments are
  intact.
* All tests that execute used throwaway workspaces (`%TEMP%\drw-web-*`,
  `drw-pw-*`, and a `drw-m5-live` server workspace). The live throwaway workspace
  was removed and port 3847 confirmed free.
* No dependency was upgraded; no user data was deleted to simplify a test.

---

## 10. Readiness (honest assessment)

Milestone 5's scope is complete and verified: any registered model can start,
validate and run an experiment; metadata shown agrees with the schema; the sample
workflow and all pre-existing tests still pass. Remaining risk is confined to the
items marked NOT VERIFIED above and the standing "not a sandbox" limitation. I do
not claim scientific validation or production readiness.
