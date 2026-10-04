# ADR-0008: The web UI talks to Python through a one-shot JSON bridge

**Status:** Accepted

## Context

Milestone 3 needs a researcher-facing interface. The specification recommends
Next.js + TypeScript for the UI and FastAPI for the API service (section 8.1),
and lists `services/api` as a boundary. It also states the non-negotiables: keep
the Python package authoritative for validation and numerics, do not duplicate
scientific calculations in TypeScript, keep execution local-first, do not expose
arbitrary remote code execution, and avoid unnecessary infrastructure
(master build prompt rules 1, 6; section 14).

Standing up a second long-lived HTTP server (FastAPI/uvicorn) adds a process to
manage, a port, a new Python dependency, and a second lifecycle to test, for a
single-user local tool. That is infrastructure without a measured need.

## Decision

* The UI is **Next.js (App Router) + React + TypeScript** in `apps/web`.
* The boundary is a **one-shot JSON bridge**: `python -m drw.api` reads one JSON
  request on stdin and writes one JSON response on stdout. It reuses the existing
  contracts and engine (`drw.execution.runner`, `drw.numerics.*`, `drw.store`) and
  adds **no new Python dependency**.
* Next.js **route handlers** (`src/app/api/**/route.ts`) are thin adapters over
  handler functions (`src/lib/handlers.ts`) that call the bridge. Their bodies are
  importable in tests, so the same code is exercised without an HTTP server.
* TypeScript contains **no science**: it assembles an `ExperimentSpec` from form
  state and renders whatever Python returns. Validation, run counting, execution,
  comparison metrics and sensitivity all come from Python.
* A **local filesystem store** (`drw.store`, `DRW_WORKSPACE`) persists the exact
  spec, results and evidence per experiment, so reopening never recomputes the
  configuration.
* **Cancellation** is wired end to end: aborting the fetch aborts the request,
  which kills the bridge child process. Per-run timeouts remain enforced by the
  core (ADR-0005); the bridge reports them as data, not exceptions.

## Consequences

* One fewer moving part than a microservice; a clean checkout runs the UI with
  `pnpm --filter @drw/web dev` and the already-installed Python core.
* Cost: process startup per request (~0.3–1 s locally) and no server-side
  streaming. Live progress is therefore limited to the UI's running state plus the
  per-run statuses reported when a run completes. A streaming API is deferred.
* Only **registered** models can be executed (the bridge refuses anything else);
  arbitrary model/import paths are not reachable from the web process, which also
  never executes model code itself - that happens in the isolated worker
  (ADR-0005).
* Isolation remains a process boundary, **not** a sandbox; the UI says so.

## Deliberately deferred

* FastAPI `services/api` (the bridge is the implemented boundary).
* Browser-level end-to-end tests (Playwright). The end-to-end test renders the
  real UI component and executes the real Python core through the real handlers,
  but it does not launch Chromium.
* Projects/teams/billing, cloud orchestration, global sensitivity, UQ, and any
  autonomous AI agent (the AI panel is not present).
