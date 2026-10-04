# Architecture

Design decisions are recorded as Architecture Decision Records (ADRs). Each ADR
states the context, the decision, and the consequences, including what is
deliberately deferred.

| ADR | Title |
| --- | --- |
| [0001](./ADR-0001-repository-layout.md) | Repository layout |
| [0002](./ADR-0002-pydantic-source-of-truth.md) | Pydantic schemas are the single source of truth |
| [0003](./ADR-0003-units-mvp.md) | Minimal unit system for the MVP |
| [0004](./ADR-0004-local-in-process-execution.md) | Local, in-process execution (partially superseded by 0005) |
| [0005](./ADR-0005-isolated-execution.md) | Isolated execution with a hard wall-clock timeout |
| [0006](./ADR-0006-non-finite-and-missing-data.md) | Non-finite values and missing data are explicit |
| [0007](./ADR-0007-contract-versioning-and-analysis-alias.md) | Contract naming, aliasing and versioning |
| [0008](./ADR-0008-web-boundary.md) | The web UI talks to Python through a one-shot JSON bridge |
| [0009](./ADR-0009-progress-jobs.md) | Progress reporting via a local job journal |
| [0010](./ADR-0010-projects.md) | A minimal project entity |
| [0011](./ADR-0011-ai-planner.md) | The AI planner is a proposal-only, optional layer |

See also:

* [`run-lifecycle.md`](./run-lifecycle.md) - the run state machine, legal
  transitions and terminal states.
* [`ambiguities.md`](./ambiguities.md) - ambiguities and contradictions found in
  the product specification, and how each was resolved.
* [`../methods/`](../methods/) - per-method verification notes.
* [`../audit/milestone-2-audit.md`](../audit/milestone-2-audit.md) - the
  Milestone 2 findings, priorities and acceptance criteria.
