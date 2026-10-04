# Milestone 4 - baseline and plan

## Phase 0 baseline (verified before changes)

* Not a git repository (no `.git`); no VCS state to preserve. Recorded rather than
  initialised, since the owner has not asked for it.
* Python: `ruff` clean; `pytest` **134 passed** (M3 end state).
* TypeScript: `pnpm -r typecheck` clean; `@drw/experiment-spec` 5 tests; `@drw/web`
  25 tests; `next build` succeeds.
* Contracts confirmed: bridge ops in `drw.api`, experiment store in `drw.store`,
  evidence package unchanged, `ExperimentSpec`/`ModelSchema`/`RunRecord` stable.
* Unresolved architectural ambiguities reviewed: ADR-0008 lists FastAPI and
  browser tests as deferred; ADR-0009/0010/0011 resolve the M4 questions.

## Prioritized plan

| # | Work | Why first |
| --- | --- | --- |
| 1 | Browser E2E (Playwright) against the production build | Highest risk/uncertainty; validates the whole stack as a user sees it |
| 2 | Progress: investigate bridge, add measured job journal | Small, self-contained, unblocks "browser trust" for longer runs |
| 3 | Projects + model capabilities | Needed by the planner and by navigation; storage-only, low risk |
| 4 | AI planner (proposal-only) + safety | Depends on capabilities + validation; largest new surface |
| 5 | UI for 2-4, tests, docs, full verification | Integrates and proves the above |

## Decisions (full rationale in the ADRs)

* **Progress** - no job service, no SSE. A client-supplied `job_id` plus a JSONL
  journal polled via `job_status`; only real events, never percentages (ADR-0009).
* **Projects** - a tiny `projects/<id>.json` entity; `project_id` on experiment
  metadata; legacy experiments read as `default`, never rewritten (ADR-0010).
* **Planner** - proposal-only, rule-based by default, optional server-side LLM
  provider, every field re-checked, never auto-executed (ADR-0011).
* **No new runtime dependencies.** Playwright is a devDependency.

## Explicitly out of scope

Teams, billing, cloud orchestration, arbitrary model uploads/user code, global
sensitivity, uncertainty quantification, autonomous iteration.
