# Milestone 4.5 (Carbon) - repository audit and baseline

Captured **before** any edit in this milestone. Every result below was produced by
running the command shown; nothing is carried over from an earlier report.

## Environment

| Item | Value |
| --- | --- |
| OS / shell | Windows 11 (10.0.26200), Windows PowerShell 5.1 |
| Node | v24.17.0 |
| pnpm | 11.9.0 |
| Python | 3.14.6 at `.venv\Scripts\python.exe` |
| Scientific stack | numpy 2.5.3, scipy 1.18.1, pydantic 2.13.5, PyYAML 6.0.3, jsonschema 4.26.0 |
| Lint / test | ruff 0.16.10, pytest 9.1.1 |
| Web | Next.js 15.5.27, React 19.3.0, TypeScript 5.x |
| Browser automation | Playwright 1.63.0 (Chromium installed under `%LOCALAPPDATA%\ms-playwright`) |
| VCS | **not a git repository** (`fatal: not a git repository`) - nothing to preserve or overwrite |
| Ports | 3000 occupied by an unrelated process; 3111/3847/3939 free |

## Commands run and actual results

| Command | Result |
| --- | --- |
| `git status --short` | `fatal: not a git repository` (expected) |
| `node --version` | `v24.17.0` |
| `pnpm --version` | `11.9.0` |
| `.venv\Scripts\python.exe --version` | `Python 3.14.6` |
| `.venv\Scripts\python.exe -c "import drw"` | `drw 0.1.0` |
| `python -m ruff check packages/core/src tests scripts` | **All checks passed** (exit 0) |
| `python -m pytest -q` | **160 passed** in 59.86s |
| `pnpm -r typecheck` | exit 0 |
| `pnpm -r build` | exit 0 |
| `node -e "require('next')/react/playwright versions"` | next 15.5.27, react 19.3.0, @playwright/test 1.63.0 |

Web unit tests and the browser suites were exercised later in the milestone (see
the final report); they were not re-run in this audit step.

## Repository inventory (as found)

* Python core: `packages/core/src/drw/{schema,numerics,models,execution,sensitivity,store,jobs,planner,capabilities,api,cli,demo}.py`.
* Bridge ops: `list_models`, `describe_model`, `capabilities`, `sample_experiment`,
  `validate`, `run`, `job_status`, `list_experiments`, `get_experiment`,
  `evidence`, `export_evidence`, `sensitivity`, `list_projects`, `create_project`,
  `plan_experiment`, `planner_status`, `environment`.
* Storage: `<workspace>/projects/*.json`, `<workspace>/experiments/<id>/{meta,spec,results}.json + evidence/`, `<workspace>/jobs/*.jsonl`.
* Web: Next.js App Router; route handlers under `src/app/api/**`; UI in
  `src/components/**` with a **custom CSS design system** (`globals.css`) and
  hand-rolled controls (`<input>`, `<select>`, custom `.panel`/`.badge` classes).
* Tests: `tests/{unit,scientific,integration}`, web `vitest` specs, Playwright
  `e2e/workspace.spec.ts` + `e2e/local-acceptance.spec.ts` + `e2e/accessibility.spec.ts`.
* Docs: product spec (`.docx`), ADRs 0001-0011, method notes, audit + acceptance reports, ambiguity log.

## Defects / blockers found in the audit

* **None blocking.** All baseline suites pass; the app builds and runs.
* Observations carried from earlier milestones and confirmed here:
  1. TCP **3000 is in use** on this machine, so `pnpm start:local` scans for a free
     port (it ran on 3847).
  2. Re-running an identical spec overwrites that experiment's stored record
     (ids are spec-hash derived) - deterministic, documented, not a defect.
  3. Isolation is a process boundary + timeout, **not a sandbox**.
  4. The optional LLM provider path has no automated coverage without a key.

## Baseline conclusion

The application is functionally healthy on this machine. The work in this
milestone is therefore (a) adopting Carbon as the UI design system and (b)
re-verifying everything, not fixing broken functionality.
