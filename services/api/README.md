# services/api

**Implemented as a JSON bridge, not a network service.**

The boundary between the researcher UI and the scientific core is
`python -m drw.api` (`packages/core/src/drw/api.py`): one JSON request on stdin,
one JSON response on stdout. The Next.js route handlers in `apps/web` spawn it.
See `docs/architecture/ADR-0008-web-boundary.md`.

| Spec API (§9.2) | Bridge op |
| --- | --- |
| `POST /v1/models` / list | `list_models`, `describe_model` |
| `POST /v1/experiments/validate` | `validate` |
| `POST /v1/experiments` / `{id}/run` | `run` |
| `GET /v1/runs/{id}` | `get_experiment` |
| differential analysis | `run` (comparisons), `sensitivity` |
| `GET /v1/evidence/{id}` | `evidence`, `export_evidence` |

A FastAPI service is **deferred**: it would add a second long-lived process, a
port and a dependency for a single-user local tool, with no measured need. The
bridge ops are already the thin, versionable surface such a service would wrap.
