# Milestone 5 - baseline, model inventory and plan

Captured **before** any edit in this milestone. Every result below was produced by
running the command shown in this session; nothing is carried over from an earlier
report.

## Environment

| Item | Value |
| --- | --- |
| OS / shell | Windows 11, `cmd.exe` / PowerShell 5.1 |
| Node / pnpm | v24.17.0 / 11.9.0 |
| Python | 3.14.6 at `.venv\Scripts\python.exe` |
| Scientific stack | numpy 2.5.3, scipy 1.18.1, pydantic 2.13.5 |
| VCS | **not a git repository** (`fatal: not a git repository`) - no VCS state to preserve |

## Commands run and actual results (baseline)

| Command | Result |
| --- | --- |
| `.venv\Scripts\python.exe -m pytest -q` | **160 passed** in 59.36s |
| `.venv\Scripts\python.exe -m ruff check packages/core/src tests scripts` | **All checks passed** |
| `pnpm -r typecheck` | exit 0 (`@drw/experiment-spec`, `@drw/web`) |
| `pnpm -r build` | exit 0 - `next build` OK (`/` = 55.4 kB, First Load 158 kB) |
| `pnpm --filter @drw/experiment-spec test` | **5 passed** |
| `pnpm --filter @drw/web test` | **32 passed / 1 failed** (see flake below) |
| `.venv\Scripts\python.exe -m drw list-models` | `lorenz`, `oscillator`, `predator-prey` (3 registered) |

Playwright/Chromium suites were **not** run in this baseline step.

## Timing-sensitive web-test failure (recorded, not dismissed)

`pnpm --filter @drw/web test` reported 32 passed / 1 failed. The failure was
`src/components/Workspace.e2e.test.tsx` - the only web test that drives the real
Python core through the real handlers (`createDirectClient`) - at its **first**
assertion:

```
TestingLibraryElementError: Unable to find role="cell" and name "alpha"
  at src/components/Workspace.e2e.test.tsx:32:25
```

Investigation performed this session:

* The rendered DOM at the moment of failure still showed the **"Start here"**
  section, i.e. the sample spec had not been applied yet. No error notification
  was present, so the request had neither failed nor completed.
* The failure occurred ~1.2s after the click. Loading the sample requires **two
  sequential Python subprocess spawns** (`sample_experiment` + `describe_model`)
  via `src/lib/bridge.ts`. The assertion used Testing Library's **default 1s
  `findBy*` timeout**, which is shorter than the spawn time under CPU contention
  from the rest of the parallel Vitest run.
* Re-running only that file passed: **1 passed in 22.9s**
  (`pnpm exec vitest run src/components/Workspace.e2e.test.tsx`).

Conclusion: a **load-sensitive timing flake**, not a product defect. It is
recorded here and folded into Phase 3 as a reliability fix (explicit timeout on
the Python-dependent assertions in that spec) so the final suite is trustworthy.
The flake status is re-checked against the final suite in the milestone report.

## Model inventory and real viability (probed directly against the core)

`drw.demo.build_demo_experiment(model_id)` and `validate_experiment` were invoked
for every registered model:

| Model | Seeded target | Factorable numeric params | Timeseries / scalar outputs | Seeded spec validation | Est. runs |
| --- | --- | --- | --- | --- | --- |
| `oscillator` | `m` | m, k, c, x0, v0 | x, v / peak_displacement | 0 errors, 0 warnings | 2 |
| `predator-prey` | `alpha` | alpha, beta, delta, gamma, prey0, predator0 | prey, predator / peak_prey | 0 errors, 0 warnings | 2 |
| `lorenz` | `sigma` | sigma, rho, beta, x0, y0, z0 | x, y, z / max_abs_x | 0 errors, 0 warnings | 2 |

The Python core is therefore **already model-agnostic**: `op_sample_experiment`
forwards `model_id`, and `build_demo_experiment` seeds a valid baseline-vs-+10%
spec for any registered model. No `drw.capabilities` limitation is reported for
any of the three.

## The UI limitation this milestone removes

`apps/web/src/components/Workspace.tsx` `openSample()` hardcodes
`"predator-prey"`; the fetched model list is used only for a count and there is
no model picker. `capabilities` and `sampleExperiment(model_id)` are plumbed end
to end but unused for selection. `ModelPanel` shows parameter bounds but not the
authoritative `description`. This is recorded as milestone-4.5 risk #7
("Model picker is future work").

## Constraints confirmed for this milestone

* Python core stays authoritative; the web layer stays a thin orchestrator.
* Registry-only models; no arbitrary code execution; no new infrastructure.
* Isolation remains a process boundary, **not** a sandbox (ADR-0005).
* Deterministic experiment ids (`exp-<hash12>`) and identical-spec overwrite are
  preserved and documented, not changed (`Runner.run`, `ExperimentStore.save`).
