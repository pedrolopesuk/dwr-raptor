# Run lifecycle

The run state machine is defined in `drw.schema.result` and enforced by the
runner (`Runner._advance`), which raises rather than applying an illegal
transition.

## Legal transitions

```
DRAFT ──► VALIDATED ──► QUEUED ──► RUNNING ──► SUCCEEDED ──► ANALYZED ──► VERIFIED ──► EXPORTED
  │            │            │           │
  └────────────┴────────────┴───────────┴──────► FAILED
```

* `FAILED` is reachable from `DRAFT`, `VALIDATED`, `QUEUED`, `RUNNING`,
  `SUCCEEDED` and `ANALYZED`.
* `VERIFIED → EXPORTED` is the only edge out of `VERIFIED`.

## Terminal states

`FAILED` and `EXPORTED`. `is_terminal(status)` and the `TERMINAL_STATES` set are
exported from `drw.schema.result`. A terminal state admits no further transition.

## What the runner actually does

For each run the runner applies, in order:

`QUEUED → RUNNING → (SUCCEEDED | FAILED)`

A run that is skipped because the experiment was cancelled is created as `QUEUED`
and moved straight to `FAILED` (a legal edge) with a `cancelled` warning
diagnostic. The full `SUCCEEDED → ANALYZED → VERIFIED → EXPORTED` tail is a
data-model concern for later milestones; this milestone produces `SUCCEEDED` or
`FAILED` runs and records them immutably.

## Failure semantics

* A failed run is **first-class history**: it is never deleted or mutated.
* `Runner.retry` creates a *new* run with `attempt = original.attempt + 1` and
  `parent_run_id = original.run_id`; the original is untouched.
* A failed baseline means no comparisons are produced (there is no reference).
* A failed variant is retained but skipped during analysis.
* Failure diagnostics are deterministic: the same failure yields the same
  `code`/`message`; only `started_at`, `finished_at` and `duration_s` vary.
