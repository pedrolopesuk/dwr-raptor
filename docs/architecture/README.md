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
| [0012](./ADR-0012-model-agnostic-experiments.md) | Model-agnostic experiment creation reuses the demo builder |
| [0013](./ADR-0013-reproduction-tolerance-policy.md) | The reproduction check requires explicit tolerances |
| [0014](./ADR-0014-global-sensitivity.md) | Global sensitivity via a Saltelli coupled design and Jansen/Saltelli estimators |
| [0015](./ADR-0015-identifiability.md) | Local parameter identifiability via a normalized finite-difference sensitivity |
| [0016](./ADR-0016-observation-model.md) | Universal observation/data model |
| [0017](./ADR-0017-dataset-storage.md) | Dataset storage, content addressing & integrity |
| [0018](./ADR-0018-csv-adapter.md) | CSV observation adapter & dataset import |
| [0019](./ADR-0019-observation-model-evaluation.md) | Observation ↔ model evaluation |
| [0020](./ADR-0020-dataset-identity.md) | Dataset scientific identity vs artifact identity |
| [0021](./ADR-0021-evaluation-alignment.md) | Evaluation alignment & datetime bridge |
| [0022](./ADR-0022-calibration-architecture.md) | Calibration architecture |
| [0023](./ADR-0023-objective-semantics.md) | Objective semantics |
| [0024](./ADR-0024-optimizer-selection.md) | Optimizer selection |
| [0025](./ADR-0025-calibration-identity-and-persistence.md) | Calibration identity, provenance & persistence |
| [0026](./ADR-0026-calibration-failure-semantics.md) | Calibration failure semantics |
| [0027](./ADR-0027-calibration-boundaries.md) | Calibration boundaries (validation & parameter uncertainty) |

See also:

* [`run-lifecycle.md`](./run-lifecycle.md) - the run state machine, legal
  transitions and terminal states.
* [`ambiguities.md`](./ambiguities.md) - ambiguities and contradictions found in
  the product specification, and how each was resolved.
* [`../methods/`](../methods/) - per-method verification notes.
* [`../audit/milestone-2-audit.md`](../audit/milestone-2-audit.md) - the
  Milestone 2 findings, priorities and acceptance criteria.
