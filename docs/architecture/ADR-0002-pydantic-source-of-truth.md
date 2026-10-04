# ADR-0002: Pydantic schemas are the single source of truth

**Status:** Accepted

## Context

The specification says a typed spec may be expressed with "JSON Schema or
Zod/Pydantic models" (section 7.3) and lists both `packages/schemas` and
`packages/experiment-spec` as packages. If the Python and TypeScript contracts
are each hand-maintained, they will drift, and a spec accepted by the UI could be
rejected by the engine (or vice versa).

## Decision

* The **Pydantic models** in `drw.schema` are authoritative:
  `ModelSchema`, `ExperimentSpec`, `ModelResult`, `RunRecord`, etc. All
  validation and run counting happens in Python.
* The TypeScript package `@drw/experiment-spec` is a **mirror**: hand-written
  types for the editor, plus a deliberately minimal `validateExperimentSpecShape`
  guard for fast UI feedback. It is not authoritative.
* **JSON Schemas are generated** from the Pydantic models by
  `scripts/export_schemas.py` into `packages/experiment-spec/schema/`. They are
  committed so the TS side can build without a Python runtime, and regenerated
  whenever the contract changes.

## Consequences

* A schema change is a Python-first change, followed by regenerating JSON Schema
  and updating the TS mirror. CI runs the Python tests; a future drift check could
  diff generated schemas in CI.
* The TS guard can only catch shape errors, not scientific ones (bounds, units,
  budget). That is intentional: the engine is the gate.
