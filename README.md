# Differential Research Workbench (DRW)

> The experiment operating system for computational research: connect a model,
> vary what matters, see what changed, understand why, and reproduce it.

DRW is a **model-agnostic experiment layer**. It does not implement domain
solvers; it takes a scientific model that already exists, runs it systematically
(baselines, parameter sweeps, perturbations), compares outcomes, quantifies
sensitivity/uncertainty, and preserves an evidence package another researcher can
reproduce.

This repository is the **MVP vertical slice** described in
`Differential_Research_Workbench_Complete_Spec.docx`:

1. register a typed Python model,
2. define a baseline and a parameter variation,
3. run a deterministic batch,
4. compare baseline vs. variants (delta/relative delta),
5. export a reproducible evidence package.

The full product specification (PRD, science, architecture, AI plan, GTM) lives
in the spec document at the repository root. Implementation decisions and
recorded ambiguities live under [`docs/`](docs/).

---

## Repository layout

```
.
├── apps/web/                     # Next.js research UI            (Phase 2, placeholder)
├── services/
│   ├── api/                      # FastAPI service boundary      (placeholder)
│   ├── runner/                   # local execution service       (placeholder)
│   ├── analysis/                 # analysis service              (placeholder)
│   └── ai/                       # AI orchestrator               (placeholder)
├── packages/
│   ├── core/                     # drw-core: the Python scientific core (this MVP)
│   └── experiment-spec/          # @drw/experiment-spec: TS client types
├── models/
│   └── examples/                 # example experiments (predator-prey, lorenz)
├── infra/{docker,compose}/       # packaging                     (placeholder)
├── tests/{unit,scientific,integration,fixtures}/
├── docs/{architecture,methods,ai}/
├── scripts/
└── .github/workflows/
```

The Python scientific core is the only part that is implemented end-to-end in
this milestone. Directories marked *placeholder* exist to fix the boundaries and
will be filled in later phases. See
[`docs/architecture/ADR-0001-repository-layout.md`](docs/architecture/ADR-0001-repository-layout.md).

---

## Requirements

- **Python** ≥ 3.11 (developed and tested on 3.14)
- **Node** ≥ 20 and **pnpm** ≥ 9 (for the TypeScript workspace packages)
- No GPU, no cloud services, no paid APIs.

## Run the researcher workspace (web UI)

The web app is a thin Next.js interface over the same Python core - it contains
no science. It needs the Python core installed (below) and then:

```bash
pnpm install
pnpm start:local                  # Windows: builds, picks a free port, starts the server
pnpm --filter @drw/web dev        # or the dev server (default port 3000)
```

On Windows, `pnpm start:local` prints the exact URL (it checks that the port is
free) and points the app at the local `.venv`. See
[`docs/local-run.md`](docs/local-run.md).

The interface is built on the **IBM Carbon Design System** (`@carbon/react`),
with a light/dark theme toggle in the header. See
[`docs/architecture/carbon-design-system.md`](docs/architecture/carbon-design-system.md).

Choose any registered model (`oscillator`, `predator-prey`, `lorenz`) in the
sidebar to start a new experiment, or click **Open sample project
(predator-prey)** → validate → run → inspect
Overview/Plots/Metrics/Sensitivity/Reproducibility → export evidence → reopen a
saved experiment. A new experiment is seeded from a clearly-labelled
**demonstration** configuration (+10% on the model's first input), which you
review and adjust before validating. Projects group experiments; the optional AI
planner proposes a spec that you must apply, validate and approve before anything
runs.

```bash
pnpm --filter @drw/web e2e        # build + Playwright/Chromium browser + accessibility tests
```

The **AI planner is optional and off by default**. With no provider configured a
deterministic rule-based planner is used and nothing leaves the machine. To enable
an LLM provider (server-side only - never in the browser):

```bash
DRW_LLM_PROVIDER=openai DRW_LLM_API_KEY=... DRW_LLM_MODEL=gpt-4o-mini \
  pnpm --filter @drw/web dev
```

When a provider is configured, the question, your context and the model's declared
metadata are sent to it; simulation data and results are not. See
[`docs/ai/README.md`](docs/ai/README.md) and
[`docs/architecture/ADR-0011-ai-planner.md`](docs/architecture/ADR-0011-ai-planner.md).

See [`apps/web/README.md`](apps/web/README.md) and
[`docs/architecture/ADR-0008-web-boundary.md`](docs/architecture/ADR-0008-web-boundary.md).

## Setup

```bash
# 1. Python scientific core
python -m venv .venv
# Windows (PowerShell):  .\.venv\Scripts\Activate.ps1
# macOS/Linux:           source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e "packages/core[dev]"

# 2. TypeScript workspace
pnpm install
pnpm -r build
```

## Documented commands (definition of done)

These are the commands a clean checkout can run to reproduce the MVP.

```bash
# List the registered reference models and their typed contracts
python -m drw list-models

# Show one model's parameters, units, bounds and outputs
python -m drw describe predator-prey

# Validate a model + an experiment specification (no execution)
python -m drw validate models/examples/predator-prey/experiment.yaml

# Run the example experiment and export a reproducible evidence package
python -m drw run models/examples/predator-prey/experiment.yaml --out .drw/predator-prey

# Fast path: run in-process (does NOT enforce timeout_s; use only for trusted models)
python -m drw run models/examples/predator-prey/experiment.yaml --out .drw/predator-prey-fast --isolation in_process

# The one-command "killer demo": baseline vs +10%, delta + sensitivity ranking
python -m drw demo --out .drw/demo

# Verify an exported evidence package against its manifest (read-only)
python -m drw verify .drw/predator-prey/manifest.json

# Reproduce a stored experiment and compare it to the reference (read-only;
# tolerances are explicit - see docs/architecture/ADR-0013-*.md)
python -m drw reproduce exp-1d700f7ad478 --rtol 1e-9 --atol 1e-12 --workspace .drw/web-workspace

# Descriptive uncertainty summary over a stored experiment's sampled design (read-only)
python -m drw uncertainty exp-1d700f7ad478 --workspace .drw/web-workspace

# Global variance-based (Sobol) sensitivity study (on-demand; runs model evaluations)
python -m drw sobol exp-1d700f7ad478 --factors alpha,beta --n 32 --seed 0 --workspace .drw/web-workspace

# Local parameter identifiability study (on-demand; runs model evaluations; read-only).
# Local/structural only: not global identifiability, not practical (noisy-data) identifiability.
python -m drw identifiability exp-1d700f7ad478 --factors beta,predator0 --outputs prey --workspace .drw/web-workspace
```

## Execution, isolation and timeouts

By default every run executes in an **isolated child process** so
`execution.timeout_s` is a hard wall-clock limit: on expiry the process tree is
killed and the run is recorded as `FAILED` with a `timeout` diagnostic. Failure
codes are deterministic (`timeout`, `cancelled`, `worker_crash`,
`invalid_worker_response`, `worker_model_error`). Set `isolation: in_process` (or
`--isolation in_process`) for the faster legacy path, which does **not** enforce
the timeout.

This is process isolation, **not** a sandbox: a model can still read files and use
the network, and POSIX `rlimit` limits are opt-in and unavailable on Windows. See
[`docs/architecture/ADR-0005-isolated-execution.md`](docs/architecture/ADR-0005-isolated-execution.md).
`SubprocessExecutor.enforced_limits()` reports what is actually enforced at
runtime.

Tests:

```bash
python -m pytest                       # unit + scientific + integration
python -m pytest -m scientific         # numerical golden tests only
pnpm -r test                           # TypeScript package tests
```

Lint / format:

```bash
ruff check packages/core/src tests scripts
ruff format packages/core/src tests scripts
```

Regenerate the JSON Schemas consumed by the TypeScript package:

```bash
python scripts/export_schemas.py
```

---

## Reference models

| Model id | Why it exists | What it demonstrates |
| --- | --- | --- |
| `oscillator` | Has a closed-form solution | Numerical correctness checked against an analytic reference. |
| `predator-prey` | Nontrivial dynamic system | Parameter variation, trajectory deltas, a conserved quantity. |
| `lorenz` | Chaotic dynamics | Determinism for a fixed configuration and perturbation growth. |

## What is intentionally *not* in this milestone

Cloud execution, collaboration, billing, the Next.js UI, the AI planner and
distributed queues are explicitly deferred. They are scaffolded as boundaries but
not implemented - see the spec's section 11 (MVP scope) and section 18
(roadmap). Nothing in this milestone should imply otherwise.

Also deliberately out of scope for now, and **not** to be implied otherwise:

* **Sandboxing.** Execution is isolated by process boundary and timeout only; no
  filesystem or network restriction (ADR-0005).
* **Parallel execution.** Runs are sequential.
* **Optimization.** Not implemented. Global variance-based (Sobol) sensitivity is
  available on demand (`drw sobol`, `docs/methods/global-sensitivity.md`); it
  estimates first-/total-order indices for independent inputs and is not a causal
  analysis. The local one-at-a-time ranking and a **descriptive** uncertainty
  summary over a sampled design are also available (ADR-0006 note; audit SC-3). A
  **local parameter identifiability** study (finite-difference sensitivity SVD;
  `drw identifiability`, `docs/methods/identifiability.md`, ADR-0015) is available
  on demand; it is **local/structural** only - not global identifiability and not
  practical identifiability from noisy observations. **Calibration, parameter
  fitting and observations/dataset ingestion are not implemented.**
* **Full unit dimensional analysis.** Compound units are opaque labels (ADR-0003).

## License

Unlicensed / all rights reserved. No license file is included yet; add one before
any distribution.
