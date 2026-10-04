# ADR-0004: Local, in-process execution

**Status:** Partially superseded by [ADR-0005](./ADR-0005-isolated-execution.md).
The process boundary now defaults to an isolated subprocess and `timeout_s` is
hard-enforced there; `"in_process"` remains available as the fast path and still
does not enforce the timeout. The domain-level decisions below (baseline-first,
deterministic ids/seeds, immutable failed runs, retry-as-new-attempt) still hold.

## Context

The specification calls for local-first execution, a local process pool first and
a queue later (`Redis queue later`), and for run isolation, timeouts and retries
(sections 8.1, 8.3, 11 and 14). It also states rule 6 of the master build prompt:
"Do not introduce distributed infrastructure until the current milestone has a
measured need."

## Decision

The MVP runner (`drw.execution.runner.Runner`) executes runs **sequentially, in
process, on the local machine**:

* The baseline runs first and is the frozen reference.
* Deterministic ids (`exp-<spec_hash[:12]>-rNNNN`) and seeds are assigned per run.
* Failed runs are preserved as immutable records; `Runner.retry` creates a new
  **attempt** that links to the original via `parent_run_id`.
* An environment fingerprint (Python/numpy/scipy/pydantic versions, platform,
  interpreter path) is attached to every run and to the evidence manifest.

## Consequences and known limitations

* **Timeout is not hard-enforced.** `execution.timeout_s` is recorded in the
  `RunContext` and passed to the adapter, but a long-running in-process model is
  not force-killed (process/signal-based cancellation does not behave identically
  on Windows and POSIX). Sandboxed process execution with real timeouts is a
  later increment.
* **No parallelism.** Grid/sweep runs are sequential. A process pool is the next
  step once runs are long enough for it to matter.
* **No isolation.** Model code runs in the same interpreter; untrusted model code
  must not be executed in this mode. Sandboxing/containers are part of the cloud
  worker workstream (P2).
