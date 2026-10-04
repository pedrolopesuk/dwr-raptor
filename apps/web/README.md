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
* `src/components/Workspace.tsx` - the workflow: sample → configure → validate →
  review → run → results → export → reopen.

## Tests

```bash
pnpm --filter @drw/web typecheck
pnpm --filter @drw/web test          # needs the Python core installed
pnpm --filter @drw/web build
```

`src/components/Workspace.e2e.test.tsx` renders the real UI and runs real
experiments and evidence export through the bridge. It is not a browser test; see
`docs/architecture/ADR-0008-web-boundary.md`.

## Scope

No billing, teams, cloud orchestration, arbitrary model imports, global
sensitivity, uncertainty quantification, or AI agent. Isolation is a process
boundary, not a security sandbox.
