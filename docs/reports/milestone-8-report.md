# Milestone 8 - ensemble uncertainty quantification

Activates the `uncertainty` analysis method: a **descriptive** summary of each
declared scalar output over the experiment's **existing** sampled variant runs.
No additional executions, no new numerical engine, no new dependency; delta and
relative-delta behavior unchanged.

## 1. Verdict

**PASS.** Implemented across the core, evidence, CLI, bridge and web UI; full
validation green (below). One deliberate, documented capability-surface change
(`capabilities.analysis_methods` now advertises `uncertainty`).

## 2. Changed files

| File | Change |
| --- | --- |
| `packages/core/src/drw/uncertainty.py` | **new** - `compute_uncertainty`, `uncertainty_for_experiment`, models, `UncertaintyError` |
| `packages/core/src/drw/execution/result.py` | optional `uncertainty` field on `ExperimentResult` |
| `packages/core/src/drw/execution/runner.py` | computes/attaches the summary when `uncertainty` is declared |
| `packages/core/src/drw/execution/evidence.py` | additive `uncertainty.json` artifact + hashed manifest entry + report section |
| `packages/core/src/drw/store.py` | `result_payload` includes `uncertainty` only when present |
| `packages/core/src/drw/api.py` | read-only `uncertainty` op |
| `packages/core/src/drw/cli.py` | `drw uncertainty <experiment_id> [--workspace]` |
| `packages/core/src/drw/capabilities.py` | `IMPLEMENTED_ANALYSES` includes `uncertainty` |
| `apps/web/src/lib/types.ts`, `client.ts`, `directClient.ts`, `handlers.ts` | `UncertaintySummary` type + `uncertainty` client method |
| `apps/web/src/app/api/experiments/[id]/uncertainty/route.ts` | **new** GET route |
| `apps/web/src/components/UncertaintyTable.tsx` | **new** descriptive table + banner |
| `apps/web/src/components/ResultsView.tsx` | conditional "Uncertainty" tab |
| `apps/web/src/test/stubClient.ts` | uncertainty fixture + stub method |
| tests | `tests/unit/test_uncertainty.py`, `tests/integration/test_uncertainty_workflow.py`, `test_api_bridge.py`, `test_cli.py`, `test_capabilities.py`, `apps/web/src/components/UncertaintyTable.test.tsx` |
| docs | `CHANGELOG.md`, `README.md`, `docs/methods/uncertainty.md`, `docs/testing/acceptance-matrix.md`, this report |

## 3. Mathematical definitions

For each scalar output, over the variant runs (baseline excluded):

* `n` = number of finite values used; `excluded` = `requested - n`, broken down by
  reason.
* `mean` = arithmetic mean; `std` = sample standard deviation (`ddof = 1`);
  `min`/`max` = extrema; `p05`/`p50`/`p95` = percentiles.
* **Quantile algorithm (fixed):** `numpy.percentile(values, [5,50,95], method="linear")`
  - linear interpolation between the nearest order statistics (Hyndman & Fan
  type 7). The string `"linear"` is recorded in `quantile_method`.

## 4. Failure semantics

Runs are accounted for exhaustively and nothing is fabricated:

* `run_failed`, `run_timed_out`, `output_missing`, `non_finite` are counted per
  output; failures never become `0`.
* `n >= 2`: full statistics. `n == 1`: mean/min/max/percentiles reported,
  `std = null`, `sufficient = false`, explanatory `note`. `n == 0`: every statistic
  `null`, `note = "no valid samples: statistics are undefined"`.
* A `grid` design sets a summary note that the nodes are not a sampling
  distribution.
* Unknown experiment → store `KeyError` → CLI exit 2 / bridge `not_found`; an
  experiment with no runs → `UncertaintyError` → CLI exit 2 / bridge `bad_request`.

## 5. Evidence compatibility

* The summary is an **additive** `uncertainty.json` artifact, present **only when
  the experiment declared the analysis**; it is SHA-256 hashed and appears in the
  manifest `files` list (kind `uncertainty`), so `drw verify` covers it. Tested in
  `test_uncertainty_workflow.py::test_evidence_package_carries_an_additive_uncertainty_artifact`.
* Experiments **without** the analysis are unchanged: no `uncertainty.json`, the
  manifest `files` set is exactly the previous four kinds, and the report has no
  Uncertainty section — asserted by
  `test_experiments_without_the_analysis_are_unchanged`.
* The stored per-experiment `results.json` gains an `uncertainty` key only when
  the summary exists, so existing results are not rewritten; no schema contract,
  deterministic ID, overwrite behavior or verification behavior changed.
* Read-only post-hoc access (`uncertainty_for_experiment`) leaves the stored
  experiment byte-for-byte unchanged (snapshot equality test).

## 6. Validation (exact commands, actual results)

| Command | Result |
| --- | --- |
| `.venv\Scripts\python.exe -m ruff check packages/core/src tests scripts` | All checks passed |
| `.venv\Scripts\python.exe -m pytest -q` | **234 passed** in 133.17s (was 218; +16) |
| `pnpm -r typecheck` | exit 0 |
| `pnpm --filter @drw/experiment-spec test` | 5 pass / 0 fail |
| `pnpm --filter @drw/web test` | **58 passed** (8 files) in 70.95s (was 56; +2) |
| `pnpm --filter @drw/web build` | Compiled successfully; `/` 59.5 kB / 162 kB |
| `pnpm --filter @drw/web e2e:only` (Chromium) | **5 passed** in 44.1s |

New Python tests: 7 unit (statistics, quantile method, exclusions, insufficient,
determinism, grid note, no-scalar), 6 integration (summary from the design, fixed-
seed determinism, delta unchanged, additive evidence + verify, absence unchanged,
read-only), 2 bridge, 1 CLI. New web test: 2 (`UncertaintyTable`).

## 7. Known limitations

* **Descriptive only.** Not a probability distribution, confidence interval,
  posterior, global Sobol sensitivity, or scientific validation. Parameters are
  sampled independently and uniformly over the declared factor bounds (the
  sampler's behavior), not from a defined prior.
* **Grid designs** produce summaries over grid nodes; flagged as not a sampling
  distribution.
* **No cross-machine/cross-platform reproducibility claim**; determinism is for a
  fixed design + seed + environment.
* **UI entry point is conditional:** the "Uncertainty" tab appears only for
  experiments whose stored spec declares the analysis; the web editor has no
  control to add it (authoring is via spec/planner). The tab is unit-tested; no new
  browser E2E step is added (the existing suite is unchanged and passes).
* Inference cost is the design's own run count (`n_samples`), bounded by the
  existing sequential runner and `max_runs`.

## 8. Rollback

Fully additive and local. To roll back: remove the `uncertainty` handling in
`runner.py`, the artifact block in `evidence.py`, the conditional key in
`store.py`, the `uncertainty` op in `api.py`, the CLI command, and the web tab/
types. No stored data migration is required; existing packages and results are
unaffected (the artifact only ever existed for experiments that declared the
analysis). Delta behavior is untouched throughout.

## 9. Scope

No global Sobol sensitivity indices, optimization, parallelism, new dependencies,
model-equation or solver changes, or unrelated refactoring. The one capability
surface change (`analysis_methods` now lists `uncertainty`) is documented.

## 10. Closure polish (independent audit F1-F3)

Resolves the findings from the Milestone 8 audit without changing any numerical
calculation:

* **F1 - count semantics made explicit.** The ambiguous summary fields were renamed
  to `requested_variants` (a per-run count) and `valid_output_samples` /
  `excluded_output_samples` (totals summed across the declared scalar outputs), with
  per-output `requested_variants` / `valid_samples` / `excluded_samples` remaining
  authoritative. The module and model docstrings, the CLI output, the web
  `UncertaintyTable` (design line + `valid / variants` column + an explanatory
  hint), the TypeScript types, the methods note, the changelog and this report were
  updated. A regression test with **two scalar outputs and four valid variants**
  asserts `requested_variants=4`, `valid_output_samples=8`, and per-output
  `valid_samples=4` (`tests/unit/test_uncertainty.py`).
* **F2 - no-runs path tested.** Added bridge
  (`test_uncertainty_op_no_runs_is_bad_request` → `bad_request`) and CLI
  (`test_uncertainty_command_no_runs` → exit 2) tests using an experiment whose
  stored `results["runs"]` is emptied.
* **F3 - no-scalar diagnostic.** A model that declares no scalar outputs now yields
  an empty summary with the note `"no scalar outputs are declared: there is nothing
  to summarize"` (asserted in a unit test); no statistics are fabricated. The note
  composes with the grid note.

The `uncertainty.json` artifact field names changed accordingly. That artifact was
introduced in this same milestone (Milestone 8), is regenerated on every run and is
not part of any frozen contract, so there is no stored-data migration; deterministic
IDs, overwrite behavior, delta/relative-delta results, evidence hashing/verification
and experiments without the analysis are unchanged.
