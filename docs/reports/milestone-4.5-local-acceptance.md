# Milestone 4.5 - Local launch and interactive acceptance

Stabilization and launch-readiness pass. **No new features.** The only code added
is the Windows launcher and the live-acceptance test harness; nothing in the
scientific core, contracts or UI behaviour changed.

Repository: `C:\Users\main\Documents\trussotFabric\fabric-siosy`

---

## 1. Environment and versions

| Item | Value |
| --- | --- |
| OS / shell | Windows 11 (10.0.26200), PowerShell 5.1 |
| Node | v24.17.0 |
| pnpm | 11.9.0 |
| Python | 3.14.6 (`C:\Users\main\Documents\trussotFabric\fabric-siosy\.venv\Scripts\python.exe`) |
| Scientific stack | numpy 2.5.3, scipy 1.18.1, pydantic 2.13.5, PyYAML 6.0.3, jsonschema 4.26.0 |
| Lint / tests | ruff 0.16.10, pytest 9.1.1 |
| Web | Next.js 15.5.27, React 19.3.0, TypeScript 5.x |
| Browser automation | Playwright 1.63.0, bundled Chromium (installed in `%LOCALAPPDATA%\ms-playwright`) |
| VCS | **not a git repository** (no `.git`); nothing was initialised |
| Working tree | preserved as-is; no branch, no commit |

---

## 2. Commands executed

```powershell
git status --short                                   # fatal: not a git repository (expected)
node --version ; pnpm --version
.\.venv\Scripts\python.exe --version
.\.venv\Scripts\python.exe -c "import drw; ..."       # drw 0.1.0
.\.venv\Scripts\python.exe -m ruff check packages/core/src tests scripts
.\.venv\Scripts\python.exe -m pytest -q
pnpm -r typecheck
pnpm -r build
pnpm -r test
pnpm --filter @drw/web e2e:only                       # isolated browser E2E (port 3111)
.\.venv\Scripts\python.exe -m drw demo --out .drw\acceptance-demo
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\start-local.ps1 -Port 3847 -Mode prod -NoBuild
# HTTP checks against http://localhost:3847
Invoke-WebRequest http://localhost:3847/api/models
Invoke-WebRequest http://localhost:3847/
Invoke-RestMethod  http://localhost:3847/api/projects
Invoke-RestMethod  http://localhost:3847/api/planner
# Live browser walkthrough against the running server
$env:DRW_BASE_URL="http://localhost:3847"
pnpm --filter @drw/web exec playwright test --config playwright.local.config.ts
# Independent verification script (results.json vs fresh Runner; evidence hashes; analytic oscillator)
.\.venv\Scripts\python.exe <scratch>\list_and_verify.py
```

---

## 3. Tests and actual results

| Check | Result |
| --- | --- |
| `ruff check` | **All checks passed** (exit 0) |
| `pytest -q` | **160 passed** in 60.55s |
| `pnpm -r typecheck` | exit 0 |
| `pnpm -r build` | exit 0 (web + contract package) |
| `pnpm -r test` | `@drw/experiment-spec` **5 passed**; `@drw/web` **33 passed** (57.00s); exit 0 |
| Isolated browser E2E (`pnpm e2e`) | **1 passed** (29.9s) |
| Live browser acceptance (running server) | **1 passed** (40.4s) |
| CLI scientific demo | ran; evidence manifest + 6-row sensitivity ranking produced |

No test failed. No check was skipped as un-runnable **except** one class:
the optional **LLM provider path** was not exercised (no API key configured) - see
section 8.

---

## 4. Fixes and files changed

**Functional defects requiring code fixes: none were found.** Discovery and the
end-to-end walkthrough both passed on the first attempt; startup, routes, the
Windows subprocess bridge, validation, execution, persistence, sensitivity,
evidence export and the planner all worked as documented.

Changes made are launch/acceptance tooling and documentation only:

| File | Change |
| --- | --- |
| `scripts/start-local.ps1` | **new** - prerequisite checks, free-port scan, env wiring, prints URL |
| `package.json` | added `start:local` script |
| `apps/web/playwright.local.config.ts` | **new** - runs the acceptance spec against an already-running app |
| `apps/web/e2e/local-acceptance.spec.ts` | **new** - live browser walkthrough + console/5xx assertions |
| `apps/web/playwright.config.ts` | `testIgnore` for the local spec (so `pnpm e2e` stays isolated) |
| `docs/local-run.md` | **new** - Windows local run guide |
| `README.md` | document `pnpm start:local` |
| `CHANGELOG.md` | Milestone 4.5 entry |

Environment observation (not a defect): **TCP port 3000 is already in use on this
machine**, so the launcher scans upward and the app was started on **3847**.

---

## 5. Browser and end-to-end verification

* **URL:** `http://localhost:3847` — **the server is still running** at the end of
  this task (verified: `GET /` → 200, `GET /api/models` → 200, listening on 3847).
* **What was run:** Playwright drove a real Chromium against the **production**
  build (`next start`), executing the Python core through the JSON bridge on every
  step. This is browser automation, not a manual click-through.
* **Console / network health:** the spec failed the run if any console `error`,
  `pageerror`, or HTTP `>= 500` response occurred. Final assertions:
  `failedRequests == []` and `consoleErrors == []`.
* **Server/bridge health during execution:** every run in the walkthrough
  completed (2 runs + planner run + timeout run) and sensitivity/export calls
  succeeded; no bridge error surfaced.

Not claimed: I did not manually click in a desktop browser. That remains a
one-minute manual confirmation (section 9).

---

## 6. Research workflow demonstrated (live, in Chromium)

1. Opened the app; status `idle`; project selector and model count visible.
2. Inspected `default` project (Sample: predator-prey) and the registered models.
3. Loaded the sample project; the predator-prey parameters/units/bounds render.
4. Set the baseline (`alpha = 1.1`).
5. Set the intervention (`alpha = 1.21`).
6. Validated → `valid`, 2 estimated runs. Rejected an invalid config (`alpha = 999`
   → `invalid`, Run disabled), then restored and re-validated.
7. Configured and ran the sampling experiment (grid, one variant) through the
   isolated subprocess runner.
8. Observed status `running → succeeded`, then `"2 comparison(s) from 2 run(s)"`.
9. Inspected diagnostics/metrics (there were no warnings for this spec).
10. Compared baseline vs intervention (delta/relative delta produced by Python).
11. Inspected the plot (`reference / variant / delta` SVG) - labels and units match
    the returned comparison arrays.
12. Ran sensitivity analysis; the table rendered the OAT ranking.
13. Generated a planner proposal, reviewed it (assumptions, validation), applied it
    to the editor, validated, and executed it - no auto-execution.
14. Reloaded the page; saved experiments remained listed, and reopening showed the
    stored configuration unchanged (`alpha = 1.1`).
15. Exported the evidence package (`wrote ... evidence/evidence.zip`).
16. Exercised invalid input and a 1 ms execution timeout → status `timed_out`.
17. Checked console/network/server health (section 5).

---

## 7. Scientific verification performed

Independent checks, not merely HTTP success:

* **Recompute:** for the newest successful persisted experiment
  (`exp-00a16e4a617d`), the stored comparison metrics equal a **fresh** `Runner`
  run of the stored spec:
  `max_abs_delta(prey) = 5.664636503144003`, `max_abs_delta(predator) =
  2.2061095802881088` — exact match.
* **Browser ↔ core:** the Metrics tab displayed `5.66464`, i.e. the same value the
  core produced for this spec.
* **Sensitivity cross-check in the browser:** the parsed OAT table satisfied
  `abs_delta(beta) > abs_delta(alpha) > 0`, matching the core's ranking.
* **Evidence integrity:** for the persisted experiment, all four manifest files
  (`experiment-spec.json`, `model-schema.json`, `results.json`, `report.md`) had
  SHA-256 and sizes matching `manifest.json` — no mismatches.
* **Timeout record:** the 1 ms run is persisted with `timed_out = true` and
  diagnostic code `timeout`.
* **Analytic reference:** oscillator integration vs the closed-form underdamped
  solution, `max|numeric - analytic| = 8.92e-11` (solver rtol 1e-10).
* The Python suite (160 passed) additionally verifies the analytic oscillator
  error-vs-tolerance convergence, RK45-vs-BDF agreement, the Lotka-Volterra
  conserved quantity, and the analytic predator-prey equilibrium.

---

## 8. Known defects and limitations

1. **Re-running an identical spec overwrites its stored record.** The experiment id
   is derived from the spec hash, so the same configuration rewrites
   `results.json`/`evidence/` and updates `created_at`. Experiments with *different*
   specs are untouched. This is by design (deterministic ids) but worth knowing.
2. **Progress is coarse and poll-based** (~0.7 s) - "k of n runs completed" from a
   real journal; there are no percentages and no streaming.
3. **Cancellation is not browser-tested.** There is no deterministic long-running
   first-party model to cancel; it is covered by `tests/unit/test_isolation.py`
   (process kill) and the component test asserting the `cancelled` state.
4. **The optional LLM provider was not executed** (no API key). The rule-based
   planner, proposal validation, apply flow and the untrusted-field filtering are
   tested; the HTTP client is not.
5. **Isolation is a process boundary with a hard timeout, not a sandbox** - model
   code can read files and use the network (ADR-0005). The UI states this.
6. **Job journals accumulate** under `jobs/` and are pruned when older than 24 h at
   the start of the next run.
7. **The UI's sample flow targets predator-prey.** Oscillator and Lorenz are
   registered and listed, but there is no model picker to start a fresh experiment
   from an arbitrary model yet.
8. Single-user, local-only: no authentication, no packaging/installer.
9. The acceptance run **added 4 experiments** to `.drw/web-workspace` (see §11).
10. A shell `Get-ChildItem -Directory` listing appeared to truncate; a Python
    listing showed the true count (4). Shell artifact, not an app defect.

---

## 9. Steps you should complete manually

None are required for the app to work; optional confirmations:

1. Open `http://localhost:3847` in your own browser and click through the workflow
   (the automation already did this, but a human pass is the final acceptance).
2. Optionally set `DRW_LLM_PROVIDER`/`DRW_LLM_API_KEY` and retry the planner to see
   the provider-backed proposal (untested here; see ADR-0011 for privacy notes).
3. Optionally try sensitivity on the **lorenz** experiment via the CLI
   (`python -m drw run models/examples/lorenz/experiment.yaml --out .drw/lorenz`).

---

## 10. Stopping and restarting

The app is **currently running** on `http://localhost:3847` (background task id
`s4skhusc`).

Stop it (preferred - only that process):
```powershell
# in the window that launched it: Ctrl+C
# or, from a new shell, stop the tracked task/process:
Get-NetTCPConnection -LocalPort 3847 -State Listen | ForEach-Object { Stop-Process -Id $_.OwningProcess }
```

Restart it:
```powershell
cd C:\Users\main\Documents\trussotFabric\fabric-siosy
pnpm start:local                  # picks a free port automatically
pnpm start:local -- -Port 3847    # or force a port
pnpm start:local -- -Mode dev     # hot-reloading dev server
```

The launcher never kills other processes and never deletes data.

---

## 11. Existing data preserved

* The workspace `.drw\web-workspace` **did not exist before this task**; it was
  created by the launcher and is the only place the app writes.
* Nothing was deleted, reset or migrated. No files outside `.drw\` were written by
  the app.
* The acceptance run created `projects/default.json`, **4 experiments** (3
  successful, 1 showing the timeout path with 2 failed runs) and 3 job journals.
  These are the artifacts you can now explore.
* The CLI demo wrote to a separate directory, `.drw\acceptance-demo`.
* `.drw/` and Playwright output directories are gitignored.

---

## 12. Verified vs. unverified

**Verified (executed and observed)**

* All automated suites, lint, type-check and production build (section 3).
* The app builds, starts on a free port, and serves `200` at
  `http://localhost:3847`; the Python bridge is reachable and healthy.
* The full researcher workflow in a real Chromium browser, including the planner
  apply→validate→run flow, page reload persistence, evidence export and the
  timeout path (section 6), with zero console errors and zero 5xx responses.
* Scientific correctness cross-checks listed in section 7.
* Projects/experiments/jobs persist on disk and are re-readable.

**Unverified / assumptions**

* The optional LLM provider path (no key).
* Browser-level **cancellation** (covered by non-browser tests instead).
* Behaviour on non-Windows hosts (only Windows was run here).
* Long-running/heavy sweeps and multi-user scenarios (out of scope).
* A human manual click-through (automation covered the same path).
