# ADR-0001: Repository layout

**Status:** Accepted

## Context

The specification (section 8.4) sketches a repository as a flat, space-separated
list: `drw/ apps/ web/ services/ api/ runner/ analysis/ ai/ packages/ schemas/
client/ plotting/ experiment-spec/ models/ examples/ predator-prey/ lorenz/
infra/ docker/ compose/ tests/ unit/ integration/ scientific/ fixtures/ docs/
architecture/ methods/ ai/ scripts/ .github/workflows/`.

Two things are underspecified: what the outer `drw/` is (a repository root or a
directory inside it), and where the Python scientific core lives (the list names
TypeScript-sounding packages under `packages/`, but never places the Python
module).

## Decision

* The **repository root is this directory**; it plays the role of the spec's
  `drw/`. The listed children become top-level directories here.
* The **Python scientific core is `packages/core`** (distribution name
  `drw-core`), a `src`-layout package importing as `drw`:
  `packages/core/src/drw/{schema,numerics,models,execution,cli.py}`.
* TypeScript packages live alongside it under `packages/`; pnpm simply ignores
  `packages/core` because it has no `package.json`.
* `services/*`, `apps/web`, `infra/*` are created as **boundary placeholders**
  with READMEs. They mark the seams described in the spec's service boundaries
  (section 8.2) without implementing deferred phases.

## Consequences

* The literal directory names from the spec mostly exist, so later phases have a
  home.
* `packages/schemas`, `packages/client` and `packages/plotting` are intentionally
  **not** created: there is no MVP need, and the Python schemas have a different
  home. See ADR-0002.
* Tests live at `tests/{unit,scientific,integration,fixtures}` as the spec lists,
  even though the code under test lives under `packages/`.
