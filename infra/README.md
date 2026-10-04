# infra/ (deferred)

Packaging and deployment assets.

**Status: not implemented.** The MVP is local-only and requires no containers.
`docker/` and `compose/` are placeholders for the later cloud/worker phases
(specification section 8.1: "Containers: Docker/Apptainer adapter later").

Reproducible execution today is provided by:

* `packages/core/pyproject.toml` (pinned dependency ranges),
* the environment fingerprint embedded in every run and evidence manifest
  (`drw.execution.environment`).
