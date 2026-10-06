# Milestone 7 - reproduction check

A reproducibility check that re-executes a stored experiment's saved
specification, compares the fresh runs to the stored reference using the existing
comparison code, and reports numerical identity, tolerance-equivalence and
provenance differences separately - read-only, across the Python core, CLI, bridge
and web UI.

## 1. Verdict

**PASS.** All acceptance criteria met; full validation green (below). No schema,
evidence format, model identity, deterministic ID, overwrite or numerical
methodology change; no new dependency.

## 2. Repository findings and tolerance-policy decision

* The comparison infrastructure already existed (`drw.numerics.delta.compare_outputs`
  / `compare_run`: alignment, `max_abs_delta`, `max_abs_relative_delta`, `mae`,
  `rmse`, masking of non-finite pairs, unsafe-denominator handling). The new code
  **reuses** it; no second numerical engine was created.
* `verification.rtol/atol` are **solver-integration** tolerances (runner →
  `RunContext` → `OdeModel.run` → `solve_ivp`), not a run-to-run equivalence policy;
  `verification.relative_epsilon` is the delta denominator-safety threshold.
* **Decision (ADR-0013):** the reproduction check **requires explicit
  `rtol`/`atol`** (validated: finite, `>= 0`, `rtol < 1`), with the pass criterion
  `|fresh - reference| <= atol + rtol * |reference|` (the `numpy.isclose`
  convention). No threshold is invented or silently derived from the solver
  settings.
* Persistence: `Runner.run` never writes; only `store.save` persists. Re-execution
  is therefore non-persistent by construction, and the store is never mutated.

## 3. Architecture and files changed

| File | Change |
| --- | --- |
| `packages/core/src/drw/reproduce.py` | **new** - `reproduce_experiment`, `ReproduceReport`/`RunComparison`/`OutputComparison`/`ProvenanceComparison`/`ReproduceTolerances`, `ReproduceError` |
| `packages/core/src/drw/cli.py` | `reproduce` subcommand + handler |
| `packages/core/src/drw/api.py` | `reproduce_experiment` op + `_param_number` helper |
| `apps/web/src/lib/types.ts` | reproduce report types |
| `apps/web/src/lib/client.ts`, `directClient.ts`, `handlers.ts` | `reproduceExperiment` |
| `apps/web/src/app/api/experiments/[id]/reproduce/route.ts` | **new** POST route |
| `apps/web/src/components/ReproducePanel.tsx` | **new** UI panel |
| `apps/web/src/components/Workspace.tsx` | renders the panel once a stored experiment is active |
| `apps/web/src/test/stubClient.ts` | reproduce fixtures |
| tests | `tests/unit/test_reproduce.py`, `tests/integration/test_reproduce_workflow.py`, `test_cli.py`, `test_api_bridge.py`, `apps/web/src/components/ReproducePanel.test.tsx`, `Workspace.m5.test.tsx`, `e2e/workspace.spec.ts`, `e2e/accessibility.spec.ts` |
| docs | `docs/architecture/ADR-0013-*.md`, `CHANGELOG.md`, `README.md`, `docs/testing/acceptance-matrix.md`, this report |

## 4. Core, CLI, bridge, web

**Core (`reproduce_experiment(experiment_id, *, rtol, atol, store=None)`).** Loads
the stored spec + reference runs, re-executes through `Runner` (no persist),
compares each stored run to its fresh counterpart via `compare_outputs`, and
returns a report. Classification precedence: `execution_failed` →
`inconclusive` → `identical` → `equivalent_within_tolerance` → `different`.
Per-output metrics + status; provenance (spec/model/environment hashes) reported
separately. `ReproduceError` for invalid tolerances / unusable reference /
re-execution setup failures.

**CLI.** `drw reproduce <experiment_id> --rtol <r> --atol <a> [--workspace <dir>]`.
Exit 0 identical/equivalent, 1 different, 2 invalid request / missing reference /
execution error. Prints the verdict, per-output metrics and fingerprint
differences, plus the validity caveat.

**Bridge.** `reproduce_experiment` (read-only): `experiment_id` + numeric
`rtol`/`atol`; unknown experiment → `not_found`, invalid tolerances/unusable
reference → `bad_request`; a completed-but-different comparison is returned as
data (`report.verdict`) consistent with the `validate` convention.

**Web.** A "Reproduce this result" panel: shows the saved experiment and reference
run(s); explicit validated `rtol`/`atol` inputs (required, no default); a running
state with the button disabled; verdict tags for every classification; per-output
metric tables; a fingerprints table; warnings; and an explicit note that numerical
agreement is not scientific validity. The panel appears only once a stored
experiment is active, and states the original is never overwritten.

## 5. Commands and outcomes

| Command | Result |
| --- | --- |
| `.venv\Scripts\python.exe -m ruff check packages/core/src tests scripts` | All checks passed |
| `.venv\Scripts\python.exe -m pytest -q` | **210 passed** in 109.61s (was 184; +26) |
| `pnpm -r typecheck` | exit 0 |
| `pnpm --filter @drw/experiment-spec test` | 5 pass / 0 fail |
| `pnpm --filter @drw/web test` | **55 passed** (7 files) in 70.02s (was 44; +11) |
| `pnpm --filter @drw/web build` | Compiled successfully; `/` 58.8 kB / 161 kB |
| `pnpm --filter @drw/web e2e:only` (Chromium) | **5 passed** in 46.9s (workspace incl. reproduce step; accessibility incl. reproduce-panel axe + keyboard) |

**Regression found and fixed during validation (investigated, not bypassed):**
after adding the new specs, `Workspace.e2e.test.tsx` failed once under parallel
load at a default-1s `waitFor` after a real Python validation call; it passed
alone (23.8s). Root cause = subprocess startup vs the default timeout (the same
class as the M5 flake). Fix: explicit 60s timeouts on the remaining
bridge-dependent assertions in that spec. The full web suite then passed 55/55.

## 6. Evidence that stored results remain unchanged

Integration tests hash every file under the experiment directory before and after
`reproduce_experiment` and assert equality (`test_reproduce_workflow.py`), and the
bridge test does the same around the `reproduce_experiment` op. Invalid tolerances
also leave the store untouched. `Runner.run` contains no write path.

## 7. Known limitations / unverified

* **Single environment only.** Bitwise reproducibility is asserted/observed within
  the same environment; cross-machine/cross-platform bitwise equivalence is **not**
  claimed or tested.
* **Numerical agreement ≠ scientific validity**; stated in the CLI note, the UI
  banner and the report. A passing check is not proof the model is correct.
* **Environment fingerprint** is evidence of recorded characteristics, not proof
  that every dependency/hardware influence is captured.
* **Aligned-finite comparison only.** Outputs that cannot be aligned exactly
  (differing shapes/axes) or that contain non-finite pairs are reported
  `inconclusive`, never silently truncated or interpolated.
* **Inherited (out of scope):** structured solver fields, `t_span`/`n_points`
  metadata, `verification.checks` inert, `ANALYZED/VERIFIED/EXPORTED` unused;
  isolation is not a sandbox. `ruff format --check` remains repo-wide non-clean
  (pre-existing, not a CI gate). Responsive layout below 1055px remains NOT
  VERIFIED (pre-existing).

## 8. ADRs and documentation updated

* **ADR-0013** - reproduction tolerance policy (explicit tolerances; identity vs
  equivalence; incomparable handling).
* `CHANGELOG.md` (Milestone 7), `README.md` (`drw reproduce`), acceptance matrix
  (rows 41-43; totals 35 PASS/43), and this report.

## 9. Scope

No subsequent milestone was started. No global sensitivity/UQ, cloud, auth,
billing, new numerical algorithms, new dependencies, or changes to schemas /
evidence format / model identity / deterministic IDs / overwrite semantics.

## 10. Post-audit polish (reference identity + regression coverage)

The final audit found no blocking defect; two non-blocking items were addressed:

* **Reference vs fresh identity.** The report now exposes
  `fresh_runs_persisted` (always `false`) and its docstring states explicitly that
  reference ids are **stored** runs while fresh ids are **in-memory** runs that are
  never persisted; a coinciding id is not evidence of two stored runs. The CLI
  prints "reference runs (stored)" and "fresh runs (in-memory, not persisted)" and,
  when the ids coincide, explains why. The web panel shows a "Stored reference"
  entry, columns "stored reference run" / "fresh run (not persisted)", a persistence
  status of "in memory (not persisted)", and an identity note. No ids were invented
  and nothing is persisted to obtain distinct ids.
* **Regression coverage added:** mixed-output classification (one output outside
  tolerance + one incomparable → top-level `inconclusive`, difference still shown
  per output); exact tolerance boundary (below / at a representable boundary /
  above / zero reference / `rtol=0,atol=0`, with the representation-sensitive
  `1.0+1e-9` case documented and matched to `numpy.isclose`); data preservation
  across a **failed/validation-failed fresh execution** (snapshot equality); and
  CLI/bridge execution-failure semantics. A narrow-viewport (900 px) E2E check
  confirms the reproduce controls remain usable and the panel does not overflow.

No verdict precedence, tolerance formula, reference-pairing, persistence, schema,
or numerical behaviour changed.
