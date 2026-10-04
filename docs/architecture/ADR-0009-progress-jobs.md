# ADR-0009: Progress reporting via a local job journal

**Status:** Accepted

## Context

The UI↔Python boundary is a one-shot JSON bridge (ADR-0008): the run request stays
open for the whole experiment and returns only when it finishes. That gives a
"running" state but no intermediate feedback. Milestone 4 asked whether that can
support reliable progress without breaking cancellation or the process isolation
of ADR-0005, and to prefer the simplest solution.

**Options considered**

1. **A separate job/orchestration service** (start-run returns immediately, a
   worker executes, clients subscribe). Rejected: new process, new state, a race
   between "start" and the actual execution, and it duplicates the runner. This is
   exactly the infrastructure the milestone says not to add without evidence.
2. **Server-sent events / streaming** from the route handler. Requires the bridge
   to stream, i.e. a long-lived protocol and a rewritten worker. Rejected as
   disproportionate for runs that complete in seconds.
3. **A local journal** written by the existing bridge, polled by the client.
   Chosen.

## Decision

* The **client supplies a `job_id`** (`job-<16 hex>`) with the run request. The
  server validates the id and confirms it resolves inside the workspace.
* The bridge appends **measured events** to `<workspace>/jobs/<job_id>.jsonl`:
  `started` (with the engine's own estimated run count), `run_completed` (one per
  finished run: id, label, status, timed_out, duration), and `finished` (status,
  counts, comparisons, experiment id).
* A new bridge op `job_status` reads the journal and derives a coarse phase:
  `pending` → `running` → `finished`, with `completed_runs` / `total_runs`.
* The UI polls `job_status` while the run request is open and shows
  "k of n runs completed". **No percentages are invented**; only these events exist.

## Lifecycle, cancellation, cleanup, persistence

* **Identity:** `job-` + 16 lowercase hex characters, strict pattern, path-checked.
* **States:** derived from events, never stored separately, so there is no state to
  drift: `pending` (no events), `running` (started, not finished), `finished`.
* **Cancellation:** unchanged and still authoritative - the client aborts the run
  request, which kills the bridge child (ADR-0005). The journal then simply stops
  without a `finished` event; the client, which initiated the abort, shows
  `cancelled`. The journal is never used to *infer* cancellation.
* **Validation:** the spec is validated before any event is written, so a rejected
  experiment produces an empty journal (`pending`) rather than a misleading run.
* **Cleanup:** journals are tiny JSONL files; `prune(max_age_hours=24)` runs
  opportunistically at the start of each run.
* **Persistence:** journals live in the workspace alongside experiments and are not
  part of the evidence package (they describe execution, not results).

## Consequences

* Real, cheap progress with no new service, dependency or protocol.
* Progress is poll-based (~0.7 s), so it is "coarse but honest".
* The journal is not a source of truth: the run response remains authoritative, and
  a journal that stops early is reported as interrupted/cancelled by the client,
  not guessed by the server.
