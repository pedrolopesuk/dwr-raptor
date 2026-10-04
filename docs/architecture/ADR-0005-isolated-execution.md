# ADR-0005: Isolated execution with a hard wall-clock timeout

**Status:** Accepted (supersedes the timeout limitation in ADR-0004)

## Context

Milestone 1 ran every model in-process. `execution.timeout_s` was recorded but
never enforced (ADR-0004, ambiguity A9). A model that loops forever or diverges
without bound would hang the runner indefinitely, and a model that crashes the
interpreter (segfault, `sys.exit`, memory exhaustion) would take the whole
experiment - and, in the future, a web process - down with it. The master build
prompt also states: "Never execute untrusted user-supplied code in the web
application process."

## Decision

Each run may execute in a **separate child process** via
``python -m drw.execution.worker``:

* `ExecutionSpec.isolation` selects `"subprocess"` (default) or `"in_process"`.
* The parent (`drw.execution.isolation.SubprocessExecutor`) writes a JSON request,
  waits with a **hard wall-clock timeout** (`RunContext.timeout_s`), and on expiry
  kills the **process tree** (`taskkill /F /T` on Windows, `os.killpg(SIGKILL)`
  on POSIX).
* stdout/stderr are redirected to files in a private temp directory, so a chatty
  or failing child cannot deadlock the parent on a full pipe.
* The temp directory is always removed, in a `finally` block.
* Failure modes are recorded as deterministic diagnostics: `timeout`,
  `cancelled`, `worker_crash`, `invalid_worker_response`, `worker_model_error`.
* A cancellation `threading.Event` can be passed to `Runner.run`; it kills a
  running child and marks runs that never started as `FAILED` with a `cancelled`
  diagnostic.

### Downgrade rule

A caller-supplied adapter **instance** cannot be reconstructed in a child, and a
model id that is not in the registry cannot be built there. In both cases the
runner downgrades to in-process and records an `isolation_downgraded` warning; it
never silently pretends the timeout was enforced.

## What is actually enforced

| Control | POSIX | Windows |
| --- | --- | --- |
| Wall-clock timeout + process-tree kill | yes | yes |
| `RLIMIT_CPU` / `RLIMIT_AS` (opt-in) | yes | no |
| Filesystem sandbox | **no** | **no** |
| Network sandbox | **no** | **no** |
| Separate interpreter per run | yes | yes |

`SubprocessExecutor.enforced_limits()` reports this at runtime, and a test asserts
we do **not** claim filesystem/network sandboxing.

## Consequences

* Default runs are ~1 process spawn slower; the test suite grew from ~2 s to
  ~36 s (dominated by spawns). This is acceptable for correctness, and callers
  who want speed can set `isolation="in_process"` explicitly.
* Custom adapter instances lose hard timeouts (documented warning).
* Isolation is **not** a sandbox: a model can still read its own files and use the
  network. Real sandboxing (containers, restricted mounts) remains future work
  (specification section 14).
* The worker imports only the schema, adapter and registry - never the runner -
  so an isolated model cannot reach the orchestration layer.
