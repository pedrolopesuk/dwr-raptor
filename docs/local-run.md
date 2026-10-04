# Local run guide (Windows PowerShell)

Everything runs on this machine: no Docker, no database, no cloud service, no
account. The Python scientific core does the computation; the Next.js app is a
thin UI over it (ADR-0008).

## One-time setup

```powershell
cd C:\Users\main\Documents\trussotFabric\fabric-siosy

python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e "packages/core[dev]"

pnpm install
```

## Launch

```powershell
pnpm start:local                       # production build + server
pnpm start:local -- -Mode dev          # hot-reloading dev server
pnpm start:local -- -Port 4000         # explicit port
```

`scripts/start-local.ps1` checks Node/pnpm/Python, verifies the core is
importable, finds a **free** port (it does not assume 3000 is free), points the
app at the local interpreter and workspace, and prints the URL:

```
Differential Research Workbench - local launch
  mode      : prod
  python    : ...\.venv\Scripts\python.exe
  workspace : ...\.drw\web-workspace
  url       : http://localhost:3847
```

Open that URL in a browser. Stop the server with **Ctrl+C** in the same window.

Equivalent manual commands (what the script runs):

```powershell
pnpm --filter @drw/web build
pnpm --filter @drw/web exec next start -p 3847
```

## Environment variables

| Variable | Purpose | Default |
| --- | --- | --- |
| `DRW_PYTHON` | Interpreter the web app spawns for the bridge | `<repo>\.venv\Scripts\python.exe`, else `python` |
| `DRW_WORKSPACE` | Where projects, experiments, evidence and job journals live | `<repo>\.drw\web-workspace` |
| `DRW_LLM_PROVIDER` | Enables the optional LLM planner (`openai`) | unset → offline rule-based planner |
| `DRW_LLM_API_KEY` | Provider key (server-side only) | unset |
| `DRW_LLM_MODEL` | Provider model id | `gpt-4o-mini` |
| `DRW_LLM_BASE_URL` | OpenAI-compatible endpoint | `https://api.openai.com/v1` |

The app is fully usable **without** any LLM provider or key. See
[`ai/README.md`](ai/README.md) for the planner's data/privacy notes.

## Quick checks

```powershell
python -m pytest -q                                   # 160 scientific/unit/integration tests
pnpm -r test                                          # web + contract tests
pnpm --filter @drw/web e2e                            # isolated browser E2E (builds, port 3111)
python -m drw demo --out .drw\demo                    # CLI: baseline vs +10% + sensitivity
```

## Your data

Everything you create lives under `DRW_WORKSPACE`:

```
.drw/web-workspace/
  projects/<project_id>.json
  experiments/<experiment_id>/{meta,spec,results}.json + evidence/
  jobs/<job_id>.jsonl
```

Nothing outside that directory is written. Deleting the workspace resets the app;
leaving it keeps every project, experiment and evidence package.
