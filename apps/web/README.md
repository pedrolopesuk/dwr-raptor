# apps/web

The DRW researcher workspace: a thin Next.js UI over the Python scientific core.
It contains **no science** - it assembles an `ExperimentSpec`, sends it to Python,
and renders what comes back.

## Run it

From the repository root:

```bash
python -m venv .venv && . .venv/bin/activate   # or .\.venv\Scripts\Activate.ps1
python -m pip install -e "packages/core[dev]"
pnpm install
pnpm --filter @drw/web dev          # http://localhost:3000
```

Then click **Open sample project (predator-prey)**, validate, run, inspect the
results, and export the evidence package.

### Environment

| Variable | Purpose | Default |
| --- | --- | --- |
| `DRW_PYTHON` | Interpreter that runs the bridge (`python -m drw.api`) | `<repo>/.venv/.../python`, else `python`/`python3` |
| `DRW_WORKSPACE` | Where saved experiments live | `<repo>/.drw/web-workspace` |

## How it is wired

```
browser  ──fetch──▶  Next route handler (app/api/**)  ──▶  lib/handlers.ts
                                                            │
                                                   lib/bridge.ts (spawn)
                                                            ▼
                                              python -m drw.api  (JSON stdin/stdout)
                                                            ▼
                                     drw.execution.runner → isolated worker (ADR-0005)
```

* `src/lib/bridge.ts` - server-only; spawns the bridge, supports cancellation via
  `AbortSignal`.
* `src/lib/handlers.ts` - request handlers as plain functions (used by the route
  files and the tests).
* `src/lib/client.ts` - browser client; `src/lib/directClient.ts` is the
  in-process variant used by tests.
* `src/components/shell/**` - the inset application shell: project sidebar (with
  the Library group), project switcher, and the investigation frame that holds the
  contextual section navigation.
* `src/views/project.tsx`, `src/views/investigation.tsx` - the routed pages:
  project Overview, Investigations and Library (Data/Models/Experiments/Evidence);
  and the investigation's SI, Overview, Model, Data, Experiments, Analysis,
  Validation and Evidence.
* `src/components/workspace/WorkspaceProvider.tsx` - the shared state behind SI and
  Manual (they are the same product, not two).
* `src/lib/routes.ts` - the route model (`/projects/:projectId/...`).

## Tests

```bash
pnpm --filter @drw/web typecheck
pnpm --filter @drw/web test          # needs the Python core installed
pnpm --filter @drw/web build
```

`src/views/app.e2e.test.tsx` renders the real routed UI (project shell and pages)
and runs real experiments and evidence export through the bridge. It is not a
browser test; see `docs/architecture/ADR-0008-web-boundary.md`.

## Scope

The researcher UI covers: the project + investigation shell; SI (the rule-based
planner, or an optional LLM provider) proposing an experiment; Manual
configuration, validation and running; results and evidence; dataset import;
model-vs-observation evaluation; sensitivity, identifiability, calibration and
**validation** (testing a frozen calibration against independent observations,
reported as separate agreement / independence / acceptance axes) analyses.
**Not implemented: parameter uncertainty and multi-objective calibration.**
Isolation is a process boundary, not a security sandbox.
