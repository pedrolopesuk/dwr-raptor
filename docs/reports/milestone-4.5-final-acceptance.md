# Milestone 4.5 (Carbon) - final acceptance report

Two deliverables: a **verified, working application** and a **complete UI
migration to the IBM Carbon Design System**. No new product capabilities were
added; the Python scientific core, the bridge contract, the schemas and the
storage format are unchanged.

---

## 1. Environment and versions

| Item | Value |
| --- | --- |
| OS / shell | Windows 11 (10.0.26200), Windows PowerShell 5.1 |
| Node / pnpm | v24.17.0 / 11.9.0 |
| Python | 3.14.6 (`.venv\Scripts\python.exe`) |
| Scientific | numpy 2.5.3, scipy 1.18.1, pydantic 2.13.5, PyYAML 6.0.3, jsonschema 4.26.0 |
| Lint / test | ruff 0.16.10, pytest 9.1.1 |
| Web | Next.js 15.5.27, React 19.3.0, TypeScript 5.x |
| **Carbon** | `@carbon/react` 1.117.0, `@carbon/styles` 1.116.0, `@carbon/icons-react` 11.89.0, `sass` 1.105.1 |
| Browser tests | Playwright 1.63.0 + Chromium, `@axe-core/playwright` 4.13.0 |
| VCS | **not a git repository** - no branch/commit made |

---

## 2. Every verification command and its result

**Baseline (before edits)** - `docs/reports/milestone-4.5-baseline.md`

| Command | Result |
| --- | --- |
| `python -m ruff check packages/core/src tests scripts` | All checks passed |
| `python -m pytest -q` | **160 passed** in 59.86s |
| `pnpm -r typecheck` | exit 0 |
| `pnpm -r build` | exit 0 |

**After the Carbon migration and fixes**

| Command | Result |
| --- | --- |
| `pnpm --filter @drw/web typecheck` | exit 0 |
| `pnpm --filter @drw/web build` (`next build`) | exit 0 - `/` = 55.9 kB, First Load 159 kB |
| `pnpm exec vitest run` (apps/web) | **33 passed** / 5 files in 60.24s |
| `pnpm exec playwright test --config playwright.local.config.ts` (live app on :3847) | **4 passed** in 52.6s |
| `pnpm e2e:only` (isolated build + own server) | **4 passed** in 48.3s |
| `python -m ruff check …` | All checks passed |
| `python -m pytest -q` | **160 passed** in 64.55s |
| `pnpm test` (packages/experiment-spec) | **5 passed** |
| `scripts/start-local.ps1 -Port 3847 -Mode prod -NoBuild` | server started; `http://localhost:3847` |
| `pwsh verification script` (metrics recompute, evidence hashes, timeout, analytic) | all checks positive (section 4) |

---

## 3. Tests: passed / failed / skipped / blocked

* **Passed:** 160 Python + 5 contract + 33 web + 8 browser = **206 executed tests**.
* **Failed:** none.
* **Skipped:** none.
* **Blocked / not executed:** the optional **LLM provider** HTTP path (no API key
  configured) - **NOT VERIFIED**.

---

## 4. Scientific checks performed and tolerances

| Check | Method | Tolerance | Result |
| --- | --- | --- | --- |
| Oscillator vs closed form | numerical vs analytic underdamped solution | max abs error ≤ 1e-6 (`rtol` 1e-10) | **8.92e-11** |
| Lotka–Volterra invariant | conserved quantity along trajectory | span < 1e-5 | PASS (test) |
| Lorenz determinism / divergence | fixed-config equality; perturbation growth | exact for fixed config | PASS (test) |
| Convergence | error vs analytic as `rtol` tightens | monotone decrease, final < 1e-6 | PASS (test) |
| Cross-method | RK45 vs BDF on a non-stiff problem | agreement < 1e-5 | PASS (test) |
| Predator–prey equilibrium | analytic rest point `(γ/δ, α/β)` | drift < 1e-6 | PASS (test) |
| Differential formula | stored `max_abs_delta` vs a fresh core recompute | exact equality | prey `5.664636503144003`, predator `2.2061095802881088` - **identical** |
| Timeout | 1 ms budget | must be a real failure | `timed_out=true`, code `timeout`, 0 outputs |
| Evidence integrity | SHA-256 of every manifest file | must match | 4 files, **0 mismatches** |
| Browser ↔ core agreement | Metrics tab value | must equal core output | displays `5.66464` (core `5.66464…`) |
| Sensitivity interpretation | OAT +10%, peak metric, clamped, elasticity | ranking sorted | β `1.3233` > α `0.8626` > 0, verified in-browser |

Determinism caveat: deterministic seeds/hashes are asserted, but reproducibility
is only claimed for the same spec + code + environment + seed (a chaotic
trajectory is never claimed identical indefinitely).

---

## 5. Browser workflow results

Playwright drove **real Chromium** against the **production build** (`next start`),
with the real Python core behind every step:

* **Live acceptance** (`local-acceptance.spec.ts`, 43.1s): open → sample model →
  baseline/intervention → reject invalid → run → plots → metrics → keyboard tabs →
  sensitivity (β > α) → planner propose/review/apply/validate/run → evidence export
  → reload persistence → 1 ms timeout. Asserts **no console errors** and **no 5xx**.
* **Isolated E2E** (`workspace.spec.ts`, 33.7s): the same critical path on a
  throwaway workspace.
* Screenshots captured and visually inspected: a fully styled Carbon UI (blue
  primary buttons, Carbon tables/dropdowns/tags, sidebar, disabled states, code
  block, planner panel) - **no unstyled or overlapping regions**.

---

## 6. Carbon components and foundations adopted

`Header`/`HeaderName`/`HeaderGlobalBar`/`HeaderGlobalAction` + skip link;
`Button` (primary/tertiary/ghost/danger, icon-only with `iconDescription`);
`TextInput`, `TextArea`, `Select`/`SelectItem`, `FormGroup`; `Tag`,
`InlineLoading`, `ProgressBar`; `InlineNotification` for diagnostics; `Table*`
for parameters, outputs, runs, comparisons, metrics, sensitivity, environment and
evidence; `Tabs`/`TabList`/`Tab`/`TabPanels`/`TabPanel` for results;
`UnorderedList`/`ListItem`; `Theme` (`g10` light / `g100` dark toggle);
`@carbon/react` design tokens (spacing, type, colour) throughout. Details and the
two justified custom components are in `docs/architecture/carbon-design-system.md`.

---

## 7. Accessibility checks and unresolved findings

**Verified**

* axe-core (light **and** dark, start and loaded screens): **0 serious / 0 critical** violations.
* Keyboard: skip link is the first tab stop and targets `#main-content`; the sample
  action, project select, baseline field and Validate button are all keyboard
  operable; result tabs activate with Enter.
* Charts use `role="img"` + `aria-label`; series are distinguished by **colour and
  dash pattern**, never colour alone; progress is a labelled determinate bar.
* One serious violation found and fixed during the milestone: Carbon `CodeSnippet`
  renders a scrollable, non-focusable `<pre>` (`scrollable-region-focusable`). The
  spec/evidence previews are now focusable `<pre>` elements.

**Unresolved / not verified**

* **No screen-reader (NVDA/JAWS/VoiceOver) test** - NOT VERIFIED.
* **Responsive layout below 1055 px** was not exercised in a browser - NOT VERIFIED.
* Manual zoom (200%) not tested - NOT VERIFIED.
* Colour contrast was validated by axe and Carbon tokens, not by a manual
  contrast audit of every surface.

---

## 8. Files changed and reasons

| File | Change | Why |
| --- | --- | --- |
| `apps/web/src/app/globals.scss` | **new**; `globals.css` removed | Carbon stylesheet + token-based layout helpers |
| `apps/web/src/app/layout.tsx` | import the Sass stylesheet | Carbon needs its global CSS |
| `apps/web/next.config.mjs` | `sassOptions.includePaths` | resolve `@use '@carbon/react'` under pnpm |
| `apps/web/src/components/*.tsx` (11 files) | migrated to Carbon components | the migration itself |
| `apps/web/vitest.setup.ts` | `ResizeObserver` + `matchMedia` stubs | Carbon components need them in jsdom |
| `apps/web/e2e/accessibility.spec.ts` | **new** | axe + keyboard verification |
| `apps/web/e2e/local-acceptance.spec.ts` | scoped metric assertion, keyboard tab step, project-name assertion, screenshots | selector robustness + evidence |
| `apps/web/e2e/workspace.spec.ts`, `Workspace.m4.test.tsx` | target the labelled timeout field | input is now a Carbon `TextInput` |
| `apps/web/playwright.local.config.ts` | include the accessibility spec | run both live suites |
| `pnpm-workspace.yaml` | explicit `allowBuilds` decisions | pnpm blocks Carbon/IBM build scripts; they ship prebuilt assets |
| `package.json` files, `pnpm-lock.yaml` | Carbon + sass + axe dev deps | the migration |
| `docs/**` | baseline, matrix, Carbon doc, this report | deliverables |

**Python / bridge / schemas / storage: not modified.**

---

## 9. Known defects and risks

| # | Risk | Severity | Likelihood | Impact | Remediation |
| --- | --- | --- | --- | --- | --- |
| 1 | Isolation is a **process boundary + timeout, not a sandbox** (no FS/network restriction) | Med | Med | A malicious model could touch the host | Containers/seccomp later; UI states this |
| 2 | Optional LLM provider path untested; prompt injection mitigated, not solved | Med | Low (off by default) | Bad proposal | Keep off by default; validators always run; ADR-0011 |
| 3 | `internal_error` responses could echo a local path from an unexpected exception | Low | Low | Minor path disclosure | Sanitize messages if a path is ever observed |
| 4 | Identical spec re-run overwrites that experiment's record | Low | High | Loses the previous identical run | Deterministic ids by design; documented |
| 5 | Cancellation not browser-tested | Low | Med | UI state unverified in-browser | Covered by Python + component tests |
| 6 | Job journals are only pruned opportunistically (24 h) | Low | Low | Disk growth | `JobJournal.prune` runs per run |
| 7 | UI cannot yet start a fresh experiment from oscillator/Lorenz | Low | Med | Only the predator-prey sample flow | Model picker is future work |

No defect blocks founder acceptance testing.

---

## 10. Manual checks still required

1. Open `http://localhost:3847` and click through with your own eyes.
2. Screen-reader pass (NVDA/JAWS) on the primary workflow.
3. Narrow viewport / 200% zoom check.
4. Optional: configure `DRW_LLM_PROVIDER` + key and try the planner (read
   `docs/ai/README.md` first - it documents what is transmitted).

---

## 11. Start / stop commands (Windows PowerShell)

```powershell
# Start (auto-picks a free port; prints the URL)
cd C:\Users\main\Documents\trussotFabric\fabric-siosy
pnpm start:local

# or a fixed port / dev server
pnpm start:local -- -Port 3847
pnpm start:local -- -Mode dev

# Stop: Ctrl+C in that window, or
Get-NetTCPConnection -LocalPort 3847 -State Listen | ForEach-Object { Stop-Process -Id $_.OwningProcess }
```

---

## 12. Confirmed URL and server state

* **URL: `http://localhost:3847`** - the server is **still running** at the end of
  this milestone (background task `s7cwo4l7`, PID 33448), verified by
  `GET /` → 200 and `GET /api/models` → 200.
* Not claimed: I did not sit in front of a desktop browser; verification was via
  Playwright-controlled Chromium plus HTTP checks.

---

## 13. Data preserved / test data created

* **Preserved:** nothing was deleted or reset. The workspace
  `.drw/web-workspace` is the only place the app writes.
* **Existing data:** 4 experiments, 1 project (`default`), job journals. The
  milestone's live browser runs **refreshed** three of them (identical specs reuse
  their deterministic id): `exp-889712f979cd`, `exp-e1260baab1fa` (both
  2/2 succeeded) and `exp-195fbefb5800` (the 1 ms timeout, 2/2 failed with
  `timed_out`), plus the pre-existing `exp-00a16e4a617d`.
* **Isolated test data:** 43 temporary workspaces created by test runs
  (`%TEMP%\drw-pw-*`, `%TEMP%\drw-web-*`) were **removed**; 0 remain. Playwright
  `test-results/` and `.next/` are gitignored build output.
* No user secret or key exists in the workspace or the repository.

---

## 14. Readiness assessment

**Ready for founder acceptance testing.** The application builds, starts on a
confirmed free port, and the complete researcher workflow - projects, model
config, validation, execution with measured progress, differential comparison,
sensitivity, planner proposal with mandatory approval, evidence export and
persistence - was driven end to end in a real browser against the real Python
core, with zero console errors and zero 5xx responses. The UI is consistently
Carbon across every primary screen, and both themes pass automated
accessibility checks with no serious or critical violations.

Remaining risk is confined to what is explicitly marked **NOT VERIFIED** or
**PARTIAL** in `docs/testing/acceptance-matrix.md` (screen reader, narrow
viewport, LLM provider path, browser-level cancellation, non-Windows hosts) and
to the standing limitation that isolation is not a sandbox.
