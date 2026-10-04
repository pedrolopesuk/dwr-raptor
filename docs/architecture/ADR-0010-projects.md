# ADR-0010: A minimal project entity

**Status:** Accepted

## Context

Experiments were stored flat under `<workspace>/experiments/<id>/`. Milestone 4
requires creating and listing projects, associating experiments with a project,
and doing so **without** disturbing stable experiment identifiers or existing data.
Teams, billing and permissions are explicitly out of scope.

## Decision

* A project is a tiny JSON file: `<workspace>/projects/<project_id>.json` with
  `project_id`, `name`, `description`, `model_id`, `created_at`.
* Ids are `default` (the built-in sample project) or `proj-<12 hex>`; both are
  pattern-validated and path-contained.
* An experiment records `project_id` in its `meta.json`. `ExperimentStore.save`
  takes a `project_id` (defaulting to `default`) and validates the project exists.
* `list_experiments` accepts an optional `project_id` filter; `list_projects`
  ensures the default project exists on first use.

## Compatibility

Experiments written before projects existed have **no** `project_id`. They are
**read** as belonging to `default` (`meta.setdefault("project_id", "default")`)
and are never rewritten. Experiment ids are unchanged and evidence packages are
untouched, so existing data and stable identifiers are preserved. No migration
step is required; a future backfill is optional.

## Consequences

* Projects are discoverable and experiments are grouped, with no database and no
  new dependency.
* The `default` project is created lazily, so a fresh workspace is usable
  immediately.
* Ownership, roles, sharing and project deletion are **not** implemented.
