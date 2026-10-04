# services/ (deferred)

The specification (section 8.2) defines these service boundaries:

| Service | Responsibility |
| --- | --- |
| `api` | Project/model/experiment management and orchestration API (FastAPI). |
| `runner` | Schedules and executes jobs. |
| `analysis` | Transforms run outputs into differential/sensitivity/UQ artifacts. |
| `ai` | Calls language models and deterministic tools. |

**Status: not implemented.** In this milestone the same responsibilities live in
the `drw-core` Python package, invoked locally:

| Spec service | Current home |
| --- | --- |
| `api` (thin wrapper) | `drw.cli` (`python -m drw`) |
| `runner` | `drw.execution.runner` |
| `analysis` | `drw.numerics.delta`, `drw.numerics.metrics` |
| `ai` | not implemented (see `docs/ai/`) |

These directories are placeholders that fix the seams; they contain no code yet.
Splitting them into network services is deferred until a measured need appears
(master build prompt rule 6).
