# infra/docker (placeholder)

No Dockerfiles yet. A future worker image will pin the scientific runtime and run
model code in an isolated container with restricted network, memory and CPU
(specification sections 8.1 and 14.1). The MVP runs locally in-process instead
(see `docs/architecture/ADR-0004-local-in-process-execution.md`).
