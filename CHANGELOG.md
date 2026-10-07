# Changelog

All notable changes to this project are documented in this file. The project
follows a milestone-oriented changelog; entries record *scientific* behaviour
changes explicitly (see the spec's AI coding loop, section 12.4).

## [Milestone 12C] - Validation / generalisation

### Added

- **Validation orchestration layer** (`drw/schema/validation.py`, `drw/validation/`,
  `drw/validation_store.py`). Out-of-sample validation of a **frozen** calibration:
  it takes `CalibrationResult.best.parameters`, executes the model with those
  parameters **frozen** over independent validation datasets through the existing
  `Runner`, and compares each run with **M12A** `evaluate_run`. It never executes a
  model directly, never re-implements comparison and contains **no optimizer**
  (validation cannot refit).
- **`ValidationConfig`** (request): model ref, `CalibrationRef`, one or more
  `ValidationDataset`s (`DatasetRef` + `ObservationMapping` + `IndependenceSpec`),
  an `EvaluationConfig`, a `ValidationBudget` (its own budget; never shared with
  M12B), an execution template, optional user `AcceptanceCriterion`s, report-gap and
  descriptive-run flags. Model-aware checks via `validate_validation_config` /
  `resolve_validation`.
- **Frozen-parameter enforcement.** The run baseline is `best.parameters` ∪ fixed ∪
  experiment baseline ∪ nominal; after the run the M12A
  `EvaluationResult.parameter_snapshot` is asserted equal to the frozen vector, else
  `validation_parameter_mismatch` fails closed.
- **Structured independence model** (never a boolean). Mechanical checks: dataset
  identity / `science_hash` / source-file SHA-256 overlap, coordinate / time-window
  disjointness and group-key disjointness ⇒ `verified` / `violated` / `declared` /
  `unverifiable`; measurement process and experiment lineage are `declared` only and
  are never upgraded to verified. A `violated` dataset fails closed unless the run
  is explicitly flagged descriptive.
- **Per-dataset results** (no cross-dataset scalar): agreement (M12A metrics,
  counts, exclusions), the optional descriptive calibration-vs-validation gap, the
  independence report, the interpolation/extrapolation context and the acceptance
  outcomes.
- **Optional acceptance criteria** (`<=`, `<`, `>=`, `>` on a requested M12A
  metric): a separate axis from agreement; a null/non-finite metric is
  `indeterminate`, never `met`; `met` alone never yields a supported status.
- **Metrics** are exactly M12A metrics (`rmse`, `mae`, `max_abs_error`, …); no new
  comparison mathematics, no R²/MAPE/log/domain metrics.
- **Content-addressed `ValidationStore`**: `<workspace>/validations/<validation_id>/
  {config,result,provenance,manifest}.json`, `validation_id = "val-" +
  result_hash[:12]`, append-only, idempotent identical save, conflicting-payload
  rejection, integrity `verify`, plus `check_validation_staleness` computed on read
  from the recorded hashes (never a mutable flag; never auto-recomputed).
- **Determinism.** `validation_hash` (request identity, wall-clock/outcomes
  excluded) and `result_hash` (outcome identity); no randomness.
- **CLI** `drw validation run|list|get|verify|staleness`; **bridge ops**
  `run_validation`, `list_validations`, `get_validation`, `verify_validation`,
  `check_validation_staleness`; additive `capabilities.validation`; web Validation
  page (frozen-calibration setup, the three separate axes, metric/gap table,
  independence report, staleness banner); the UI no longer says validation is
  unavailable.
- Tests: contract/identity/frozen-vector (42), independence checks (22), scientific
  benchmarks (18), store/staleness (13), CLI/bridge/store integration (7), plus web
  component + Playwright.

### Notes

- **Validation is not calibration, not model selection and not proof that the model
  is true.** Agreement, independence and any acceptance criterion are reported
  separately.
- **Explicitly not implemented:** cross-validation (k-fold/grouped/blocked/temporal/
  leave-one-group-out), cross-dataset scalar aggregation, model selection /
  hyperparameter search, Bayesian/posterior predictive validation, uncertainty
  propagation, R²/MAPE/log/domain metrics, extrapolation geometry and run-output
  caching.
- **Unmodified**: `ExperimentSpec`, `ModelSchema`, `Runner`, `RunRecord`/
  `ModelResult`/`OutputValue`, `EvidenceManifest`, M11 `Dataset`/`ObservationSet`/
  `ObservationMapping`/`DatasetStore`/`science_hash`, M12A `evaluate`/`evaluate_run`/
  `EvaluationConfig`/`evaluation_hash`, and M12B calibration semantics / contracts /
  `CalibrationStore`.
- Zero new dependencies.

## [Milestone 12B] - Calibration / parameter estimation

### Added

- **Calibration orchestration layer** (`drw/schema/calibration.py`,
  `drw/calibration/`, `drw/calibration_store.py`). It drives the existing
  `Runner` (one single-run `ExperimentSpec` per candidate) and reads its objective
  **only** from M12A `evaluate_run`. It never executes a model directly, never
  re-implements comparison, and performs no inference.
- **`CalibrationConfig`** (request): free `ParameterSelection`s (float, finite
  `lower < upper`, selected bounds must stay within the model's declared bounds,
  explicit/`nominal` initial — a midpoint is never chosen silently), fixed
  parameters, objective, optimizer, budget, seed, execution template, `DatasetRef`,
  `ObservationMapping`, `EvaluationConfig`, identifiability mode and
  `data_role = "calibration"`. Model-aware validation and resolution via
  `validate_calibration_config` / `resolve_calibration`.
- **Objective oracle** (`drw/calibration/objective.py`): selects exactly one
  mapping pair and one M12A metric (RMSE default; MAE, max_abs_error,
  mean_residual, relative_*, weighted_rmse, chi_square), minimise-only. Invalid
  evaluations (M12A `ok=false`, `null`/non-finite metric) yield `objective=None`
  plus an explicit failure code — never a fabricated value.
- **Optimizers** (`drw/calibration/optimizers.py`): **Powell** (default, bounded,
  derivative-free), **Differential Evolution** (opt-in global, seeded,
  single-worker, `polish=False`) and **Random Search** (deterministic baseline).
- **Serial execution loop** (`drw/calibration/loop.py`): validates each candidate,
  builds a throwaway single-run spec, runs it through `Runner`, evaluates it with
  `evaluate_run`, extracts the objective and records every candidate with its run
  id, status, evaluation hash, objective, `n_used`/`n_excluded`, duration and
  failure code. `calibrate` / `calibrate_for_experiment`.
- **Budgets**: `max_evaluations` is the authoritative **hard** cap owned by the
  loop (no optimizer can exceed it), plus `max_wall_seconds`, a per-run
  `timeout_s` and optional `max_failed`; cancellation via a `threading.Event`.
- **Failure semantics**: reject-and-record; invalid candidates store
  `objective=null` with a code; `+inf` is an optimizer-interface sentinel only
  (disclosed as `invalid_objective_sentinel`). All-failed → `status="failed"`,
  no best. Budget exhaustion → `budget_exhausted`, `converged=false`. Convergence
  → `converged`, but never statistical certainty.
- **`CalibrationResult`** (outcome): request vs execution vs result vs
  convergence vs history vs diagnostics vs provenance vs **mandatory scientific
  disclosure**. Content-addressed `result_hash` (wall-clock excluded) and a
  deterministic `calibration_hash` (request identity).
- **CalibrationStore** (`drw/calibration_store.py`): content-addressed, append-only
  `<workspace>/calibrations/<calibration_id>/{config,result,history,provenance,manifest}.json`,
  idempotent identical save, conflicting-payload rejection, hash verification.
  **No `EvidenceManifest` change; no persistence in the pure core.**
- **Advisory identifiability** (M10): `off`/`warn` (default)/`require`; never an
  optimizer constraint.
- **CLI** `drw calibrate <experiment_id> --config <json> [--dry-run] [--persist]
  [--json] [--workspace]`; **bridge ops** `calibrate`, `list_calibrations`,
  `get_calibration`, `verify_calibration`; **web** "Calibrate against dataset"
  panel (free-parameter bounds/initials, dataset + mapping, objective, optimizer,
  budgets, seed, identifiability mode, result with best parameters, objective
  history, status, invalid count, diagnostics, disclosure); additive
  `capabilities.calibration`.
- Tests: contract/identity (35), objective oracle (11), scientific benchmarks
  (17: scalar/known-optimum/bounded/scaling/determinism/multi-parameter/noisy/
  weighted/partial-failure/timeout/invalid-state/non-identifiable/multi-minima/
  convergence-failure/budget-cap/reproducibility), loop mechanics (8), store (7),
  CLI/bridge integration (5), plus web component + Playwright.

### Notes

- **Calibration is not validation, not Bayesian inference, and not parameter
  uncertainty**; convergence is not certainty (ADR-0027).
- **Unmodified**: `ExperimentSpec`, `ModelSchema`, `Runner`, `RunRecord`/
  `ModelResult`/`OutputValue`, `EvidenceManifest`, M11 `Dataset`/`ObservationSet`/
  `ObservationMapping`/`DatasetStore`/`science_hash`, M12A `evaluate`/
  `evaluate_run`/`EvaluationConfig`/`evaluation_hash`, and M10 identifiability.
- Zero new dependencies (`scipy` was already a core dependency).
- Reference: ADR-0022…ADR-0027.

## [Milestone 12A] - Observation <-> model evaluation

### Added

- **Execution-free evaluation** (`drw/evaluation.py`, `drw/schema/evaluation.py`).
  Evaluates an already-produced model run against a dataset under an M11
  `ObservationMapping` and an explicit `EvaluationConfig`. It never launches the
  `Runner`, never changes parameters and performs no inference.
- **`EvaluationConfig`**: requested metrics, residual modes
  (`raw`/`relative`/`normalized`), alignment (`exact` or **opt-in linear
  interpolate**), tolerance, relative epsilon, datetime `time_origin`, and an
  explicit `degrees_of_freedom` (required only for `reduced_chi_square`; never
  estimated).
- **Residuals:** raw `r = y_model − y_obs`; opt-in relative only where
  `|y_obs| > relative_epsilon`; opt-in normalized `r/σ` only for `std`/`precision`
  with finite `σ > 0`. No fabricated uncertainty; `stderr`/`asymmetric`/`interval`
  are never collapsed into a symmetric σ.
- **Metrics:** `n_used`, `n_excluded`, `mean_residual`, `mae`, `rmse`,
  `max_abs_error`, plus optional `relative_*`, `weighted_rmse`, `chi_square`,
  `reduced_chi_square`, all over usable aligned pairs with exclusion counts.
- **Datetime bridge:** a datetime coordinate is converted to elapsed seconds
  relative to an explicit `time_origin`, and the model axis (a time unit) to
  seconds; no astronomical time systems.
- **One comparison abstraction** (aligned points): scalar = 1 point,
  timeseries = N points, a vector = several pairs; `matrix`/`categorical` outputs
  fail `output_kind_unsupported`.
- **Fail-closed** (`ok=false`, no metrics) on unknown variable/output, non-numeric
  observation, unsupported kind, shape/unit problems, alignment failure,
  non-finite model output, invalid uncertainty, and no usable observations.
  Exclusions carry reasons and observation indices; nothing is dropped silently.
- **Content-addressed `EvaluationResult`** (`evaluation_hash`, canonical hashing)
  carrying dataset/run/model/mapping/config + provenance (spec/model/environment/
  dataset/mapping hashes). **On-demand only — not persisted.**
- **Derived `science_hash`** (`drw.observations.science_hash`): a dataset's
  scientific-content identity independent of provenance (ADR-0020). Additive; it
  never replaces or alters `content_hash` and is not stored.
- **CLI** `drw evaluate <experiment_id> --mapping <json> [--run ...] [--metric ...]
  [--relative] [--weighted] [--interpolate] [--tolerance] [--time-origin] [--dof]
  [--dry-run] [--json] [--workspace]`; **bridge op** `evaluate` (read-only); web
  "Evaluate against dataset" panel (metrics table, observed-vs-predicted plot,
  exclusions, provenance).
- Tests: unit (config, residuals, metrics, units, alignment, datetime,
  missing/quality, determinism, hashing, science hash), scientific benchmarks
  (perfect/offset/perturbation/timeseries/interpolation/unit conversion/
  incompatible units/missing/uncertainty/repeated coordinates/datetime/execution
  failure/non-finite/unsupported kind/mapping mismatch/determinism), and
  CLI/bridge integration.

### Notes

- **Evaluation is read-only and execution-free**; it is **not** calibration, not
  validation and not a scientific conclusion (see ADR-0019).
- **No persistence**: no `evaluation.json`, no `EvaluationStore`, no
  `EvidenceManifest` change. **No inference**: no likelihood, posterior,
  parameter estimation or `scipy.optimize`.
- **Unmodified**: `ExperimentSpec`, `ModelSchema`, `Runner`, `EvidenceManifest`
  and M11 dataset/store/observation semantics. `ObservationMapping` was not
  extended (alignment lives in `EvaluationConfig`).
- Zero new dependencies.
- Reference: ADR-0019 (evaluation), ADR-0020 (dataset identity), ADR-0021
  (alignment & datetime bridge).

## [Milestone 11C] - CSV dataset ingestion & inspection

### Added

- **CSV observation adapter** (`drw/adapters/`). An `ObservationAdapter` protocol
  plus a registry; the built-in `csv` adapter (v1.0.0) exposes `can_handle`,
  `inspect` (advisory) and `read` (explicit configuration -> validated dataset).
  Zero new dependency (stdlib `csv`).
- **Advisory inspection.** Column names, inferred primitive kind
  (int/float/bool/categorical/datetime), row count, preview, missing/non-finite
  counts, delimiter/header detection, ragged-row/duplicate diagnostics, and
  candidate coordinate/measurement/uncertainty/quality roles. Detection is
  **advisory**; nothing scientific is inferred.
- **Explicit import configuration** (`CsvImportConfig`/`ColumnConfig`): role,
  name, kind, unit, `depends_on` coordinates, uncertainty companion(s)/inline,
  quality flag column, per-column missing codes, datetime format, plus dataset
  name/description/version/labels, delimiter/header overrides, global missing
  codes, and explicit non-finite/invalid policies (`error` by default).
- **Missing/invalid/non-finite semantics.** Empty cells and configured sentinels
  become explicit missing; non-finite and type-invalid cells fail with diagnostics
  by default (never silently rewritten); quality flags never delete rows.
- **ISO-8601 datetime** parsing via the standard library (no astronomical time
  systems).
- **`import_csv`** is the single parse -> validate -> `DatasetStore.save` path
  (shared by CLI and bridge); `dry_run` validates without persisting; a failed
  import leaves no partial dataset.
- **CLI:** `drw dataset inspect|import|list|describe|verify` (with `--json`,
  `--missing-code`, `--no-header`, `--delimiter`, `--dry-run`, `--config`,
  `--workspace`).
- **Bridge ops:** `list_dataset_sources`, `inspect_dataset`, `import_dataset`
  (`dry_run` supported), `list_datasets`, `describe_dataset`/`get_dataset`,
  `verify_dataset`. Files are read only from `<workspace>/dataset-sources/`, with
  path containment enforced; no arbitrary filesystem access.
- **Web:** "Import a dataset (CSV)" panel (select source -> inspect -> preview ->
  per-column role/name/unit/coordinates/uncertainty/quality -> Validate -> Import
  -> immutable `DatasetRef`) and a "Datasets" panel (list with id/name/created/
  hash/source kind, detail with variables/units/uncertainty/provenance/hash/
  verification, and an explicit Verify action).
- **Fixtures + tests:** five domain CSV fixtures (astrophysics, space, physics,
  biology, climate); CSV adapter unit tests, CLI/bridge integration tests, web
  component tests and Chromium E2E scenarios.

### Notes

- **Import is the only mutating dataset operation**; `inspect`/`list`/`describe`/
  `verify` are read-only.
- **Observation integrity only** - importing a dataset does not establish model
  validity, calibration or a scientific conclusion; the UI/Docs say so.
- No new dependency. No change to `ExperimentSpec`, `ModelSchema`,
  `EvidenceManifest`, the experiment store, Runner or M10 analysis. `DatasetStore`
  gained a read-only `provenance` accessor.
- Non-CSV formats (Parquet/HDF5/NetCDF/FITS), N-D arrays, interpolation/
  resampling and calibration remain out of scope (M11D/M12).
- Reference: `docs/architecture/ADR-0018-csv-adapter.md`.

## [Milestone 11B] - Dataset storage, provenance & integrity

### Added

- **`drw/dataset_store.py` — immutable, content-addressed dataset storage.**
  `DatasetStore` with `save`, `load`, `list`, `exists`, `ref`, `resolve` and
  `verify`, reusing `ExperimentStore`'s id-validation and path-containment
  discipline. Layout: `<workspace>/datasets/<dataset_id>/{meta,schema,data,
  provenance}.json` + `files/`.
- **Append-only semantics.** Saving the same dataset again is idempotent;
  saving a *different* dataset under an existing id raises `DatasetExistsError`
  and never overwrites; there is no update/destructive API.
- **Content addressing preserved.** The full `content_hash` is authoritative;
  `dataset_id = "ds-" + hash[:12]`; `save`/`load`/`verify` recompute and check
  identity, and refuse short-id hash-prefix collisions.
- **`DatasetRef`** now carries an optional, non-identity `created_at` and is
  reconstructed by `ref`/`list`/`resolve` (lookup by authoritative content hash).
- **`DatasetStore.verify(dataset_id)`** returns a structured
  `DatasetVerification` (per-check `ok`/`missing`/`unreadable`/`invalid`/
  `mismatch`/`not_packaged`): required files present and readable, dataset
  reconstructs, `meta.dataset_id` matches the directory, stored `content_hash`
  matches the recomputed content, the id is the short hash, `DatasetFile`
  metadata is valid, and any **packaged** file matches its declared SHA-256/size.
  Corruption is never silently repaired.
- **Packaged vs external files.** A referenced-but-absent file is reported
  `not_packaged` (never falsely verified); `package_file` copies a local file into
  `files/` only when its bytes match the declared metadata and never overwrites
  (a portability primitive, not an adapter).
- Tests: save/load round trip, idempotency, overwrite/collision refusal,
  corruption of each file, wrong hash/id, replaced content, missing files,
  refs/resolve, deterministic listing, empty/multiple stores, synthetic/manual/
  derived datasets, `DatasetFile` metadata, packaged-file hash verification,
  packaged-file tamper, path traversal, invalid ids, in-memory-mutation isolation,
  no-silent-repair, and the one-changed-value identity test.

### Notes

- **Storage only.** No CSV/import adapters, no web/CLI/bridge, no calibration, no
  N-D arrays, no new dependency, no database/cloud. `ExperimentStore`,
  `EvidenceManifest` and the evidence layout are unchanged.
- Verification proves stored bytes match the declared content/identity - it is
  **not** model validity, calibration or a scientific conclusion.
- Reference: `docs/architecture/ADR-0017-dataset-storage.md`.

## [Milestone 11A] - Scientific observation contract

### Added

- **Universal, domain-agnostic observation model** (`drw/schema/observation.py`,
  `drw/observations.py`). `Dataset` → `ObservationSet` → `Variable`, with the
  **Observation** as a semantic row (not a stored class). Covers astrophysics,
  space, physics, engineering, biology and climate through the same contract;
  there is no domain-specific type or field.
- **Columns with roles** (`coordinate`/`measurement`/`derived`/`uncertainty`/
  `quality`/`metadata`), optional units, `depends_on` coordinates, and
  **multi-coordinate** variables. **Repeated coordinate values are allowed**
  (coordinates do not uniquely identify rows).
- **Tagged uncertainty** (`none`/`std`/`stderr`/`asymmetric`/`interval`/
  `precision`), inline or via a companion column; types are never collapsed.
  Covariance/correlation are deferred (M12).
- **Explicit missing/quality semantics.** `None` is *missing*; non-finite and
  type-invalid cells are rejected at construction; quality flags map to
  `missing/invalid/censored/rejected` (unusable) or `flagged` (usable); usability
  is reported with reasons and **no row is ever silently deleted**.
- **Units** reuse `drw.schema.units`; `unit=None` means *unspecified* (distinct
  from `"dimensionless"`), never inferred. Compatibility is mandatory in a
  mapping; conversions are explicit and incompatible units hard-fail.
- **Provenance schema** (`source_kind`/`imported_at`/`dataset_version`/adapter/
  source id/uri/filename/acquisition time/source sha256/preprocessing/notes/
  license) - contract only; M11B persists it.
- **Content-addressed identity.** Full `content_hash` is authoritative;
  `dataset_id = "ds-" + content_hash[:12]`; `DatasetRef` carries both;
  `resolve_dataset_id`/`assert_same_dataset` refuse short-id hash-prefix
  ambiguity.
- **Standalone `ObservationMapping`** (dataset ref + model ref + pairs + exact
  alignment + notes) with `validate_mapping` cross-artifact checks and explicit
  `convert_to_output`. Only `alignment.strategy = "exact"` is supported (with an
  explicit tolerance); interpolation/resampling/aggregation are M12.
- Tests: five domain examples, canonical round-trip, deterministic hashing,
  dataset refs/identity, role/coordinate/column validation, units, uncertainty
  variants, companion columns, missing/quality, datetime and elapsed time,
  multi-coordinate variables, mapping validation and exact alignment.

### Notes

- **Contract only.** No storage, no import adapters, no CLI/web, no calibration,
  no fitting, no residuals/validation, no N-D arrays, no new dependency.
- Observation integrity is **not** model validity, calibration or a scientific
  conclusion; the code and docs say so explicitly.
- Reference: `docs/architecture/ADR-0016-observation-model.md`.

## [Milestone 10] - Local parameter identifiability

### Added

- **On-demand local identifiability study** (`drw/identifiability.py`). Answers
  whether the declared outputs can *locally* distinguish the parameters near a
  baseline, and which parameter combinations are effectively indistinguishable.
  Reuses `Runner`; no numerical engine is duplicated.
- **Method:** central finite differences estimate the Jacobian
  `J_ij = (y_i(theta+h) - y_i(theta-h)) / (2h)`; a normalized sensitivity matrix
  (`S_ij = J_ij * range_j / s_i`, with `s_i` the baseline output magnitude floored
  by the observed variation) is decomposed by SVD. The report contains singular
  values, numerical rank, condition number, right-singular directions with
  dominant parameter weights (including the null space when there are fewer
  informative targets than parameters) and the strongest parameter-pair
  correlations. Thresholds are disclosed; the rank tolerance is raised to the
  central-difference noise floor so a direction weaker than the difference
  accuracy is not claimed as identifiable.
- **Targets:** scalar outputs use their value; time-series outputs use a fixed,
  disclosed feature set (`max, min, mean, final, argmax_t`). **Continuous bounded
  parameters only**; discrete/boolean/categorical and unbounded parameters are
  rejected, and bounds are never invented.
- **Verdicts:** `well-conditioned`, `ill-conditioned`, `rank-deficient`,
  `inconclusive` (with reasons). **Fail-closed:** a parameter at a bound, a
  failed/timed-out/missing/non-finite evaluation, or a matrix with no measurable
  magnitude yields `inconclusive`; nothing is fabricated. Cost is `2p + 1` model
  evaluations; a 4096-evaluation cap is enforced before execution.
- **Interfaces:** CLI `drw identifiability <experiment_id> [--factors a,b]
  [--outputs ...] [--step-scale S] [--seed S] [--rank-tolerance T]
  [--condition-threshold C]`; bridge op `identifiability` (read-only w.r.t. the
  store; isolated subprocess evaluations; optional measured progress via the job
  journal); web "Parameter identifiability" panel. Study limits are exposed
  additively through `capabilities.identifiability`.
- Tests: SVD/rank/conditioning, finite-difference step and bound handling,
  invalid inputs, failure semantics, determinism and step-scale robustness,
  evaluation cap; scientific ground truth (oscillator `m`/`k` degeneracy,
  predator-prey `beta`/`predator0` collinearity, a full-rank control, hand
  matrices); real-model integration with read-only/determinism/CLI-bridge parity;
  web component and Chromium browser scenarios.

### Notes

- **Local and structural only.** The result is not global identifiability, not
  practical identifiability from noisy observations, not a calibration, causal
  claim, or model-validity statement. Passing the analysis does **not** establish
  that the model is scientifically valid.
- **Additive and on-demand.** No `ExperimentSpec`/`ModelSchema`, evidence-format,
  ID, overwrite, delta, OAT, uncertainty, Sobol or reproduce change; no
  persistence; no new dependency; no parallelism. Calibration, observations/
  dataset ingestion and optimization are **not** implemented.
- Domain-agnostic (astrophysics, physics, biology, climate, engineering, ...).
- Methods note: `docs/methods/identifiability.md`; ADR-0015.

## [Milestone 9] - Global variance-based sensitivity (Sobol indices)

### Added

- **On-demand global sensitivity study** (`drw/global_sensitivity.py`). Estimates
  first-order `S_i` and total-order `S_Ti` Sobol' indices for a scalar output over
  independent input factors, reusing `Runner` and the seeded Sobol' quasi-Monte
  Carlo sampler. The Saltelli coupled design (`A`, `B`, `AB_i`, `N*(d+2)`
  evaluations) is built from one `2d`-dimensional sample split into `A`/`B`.
- **Estimators (fixed and recorded):** first order Saltelli et al. (2010), total
  order Jansen (1999), denominator `var([f(A), f(B)], ddof=1)`; a percentile
  bootstrap interval is reported as a **diagnostic only**.
- **Finite-sample honesty:** indices are **not clipped** to theoretical bounds;
  zero/non-finite variance and any failed/timed-out/missing/non-finite evaluation
  yield an explicit `inconclusive` result with counts and reasons (fail-closed).
  Bounded default `N=32` and a 4096-evaluation cap (explicitly overridable).
- **Interfaces:** CLI `drw sobol <experiment_id> [--output] [--factors a,b] [--n N]
  [--seed S] [--bootstrap B]`; bridge op `global_sensitivity` (read-only w.r.t. the
  store; isolated subprocess evaluations; optional measured progress via the job
  journal); web "Global sensitivity (Sobol)" panel with the independence/caveat.
- Tests: analytic Ishigami benchmark, additive/interaction/constant/no-effect
  cases, determinism, failure semantics, invalid inputs, evaluation-count
  invariants, real-model integration, CLI/bridge and web.

### Notes

- **Additive and on-demand.** No `ExperimentSpec`/`ModelSchema`, evidence-format,
  ID, overwrite, delta, OAT, uncertainty or reproduce change; no persistence; no
  new dependency; no parallelism. Independent-input assumption is stated; the study
  is not causal and not scientific validation.
- Methods note: `docs/methods/global-sensitivity.md`; ADR-0014.

## [Milestone 8] - Ensemble uncertainty quantification

### Added

- **`uncertainty` analysis method.** When an experiment declares
  `analyses: [{method: "uncertainty"}]`, the run produces a **descriptive**
  summary of each declared scalar output over the experiment's **existing** sampled
  variant runs (`drw.uncertainty`). No additional executions are performed.
- Per output: `valid_samples`, `mean`, sample standard deviation (`ddof=1`),
  `minimum`, `maximum` and `p05`/`p50`/`p95`. Quantiles use
  `numpy.percentile(..., method="linear")`; the method, sampling method and seed are
  recorded in the summary. **Count semantics are explicit:** `requested_variants` is
  a per-run count; the summary-level `valid_output_samples` / `excluded_output_samples`
  are totals summed across the declared scalar outputs ("output-samples") and can
  exceed the variant count for multi-output models; the per-output
  `valid_samples` / `excluded_samples` are authoritative.
- A model with **no scalar outputs** yields an empty summary with an explicit note
  ("nothing to summarize"); statistics are never fabricated.
- **Explicit exclusions:** failed runs (`run_failed`), timeouts
  (`run_timed_out`), missing outputs (`output_missing`) and non-finite values
  (`non_finite`) are counted per output and never replaced with zero. With fewer
  than two valid samples the standard deviation is reported as `null` and the
  summary is flagged `insufficient`.
- **Evidence:** an additive `uncertainty.json` artifact (kind `uncertainty`) is
  added to the evidence package **only when the summary exists**; the manifest
  `files` list and verification cover it. Experiments without the analysis are
  byte-for-byte unchanged.
- **CLI** `drw uncertainty <experiment_id> [--workspace <dir>]` and a read-only
  bridge op `uncertainty`, both computed from stored runs without re-executing.
- **Web:** a descriptive "Uncertainty" tab in the results view.
- `capabilities.analysis_methods` now advertises `uncertainty`.

### Notes

- **Descriptive, not probabilistic.** The summary describes the sampled design
  (parameters are sampled independently and uniformly over the declared factor
  bounds, exactly as the sampler draws them); it is not a probability
  distribution, a confidence interval, or scientific validation. The CLI, report
  and UI say so.
- No global (variance-based) Sobol sensitivity, optimization, parallelism, new
  dependencies, schema-contract changes, model-equation or solver changes. Delta
  and relative-delta behavior is unchanged.
- Methods note: `docs/methods/uncertainty.md`.

## [Milestone 7] - Reproducibility check

### Added

- **Reproduction check (`drw.reproduce`, ADR-0013).**
  `reproduce_experiment(experiment_id, rtol, atol)` re-executes a stored
  experiment's saved specification and compares the fresh runs to the stored
  reference runs using the existing comparison infrastructure
  (`compare_outputs`/`compare_run`). It is **read-only**: the fresh execution is
  never persisted, so the stored experiment, reference result, manifest and
  artifacts are unchanged.
- **Explicit tolerances.** The check requires caller-supplied `rtol`/`atol`
  (validated: finite, `>= 0`, `rtol < 1`). The declared `verification.rtol/atol`
  are solver-integration tolerances and are **not** reused. Pass criterion:
  `|fresh - reference| <= atol + rtol * |reference|`.
- **Classification:** `identical`, `equivalent_within_tolerance`, `different`,
  `inconclusive`, `execution_failed`, with per-output metrics (max abs/rel delta,
  MAE, RMSE, valid/non-finite points) and a **separate** provenance comparison of
  the spec/model/environment hashes.
- **CLI:** `drw reproduce <experiment_id> --rtol <r> --atol <a> [--workspace <dir>]`
  (exit 0 identical/equivalent, 1 different, 2 invalid request/unusable
  reference/execution error).
- **Bridge op:** `reproduce_experiment` (read-only), resolving the reference
  through the existing store.
- **Web UI:** a "Reproduce this result" panel in the results view with explicit,
  validated tolerance inputs; ready/running/verdict states; per-output metric
  tables; a fingerprint comparison table; and an explicit note that numerical
  agreement is not scientific validity. The original result is never overwritten.

### Notes

- **Reference vs fresh identity made explicit.** The report exposes
  `fresh_runs_persisted` (always `false`; the fresh execution exists only in
  memory) and the CLI/UI label the **stored reference** and the **fresh execution
  (not persisted)** distinctly, noting that a fresh run identifier can equal the
  stored one because the deterministic id derives from the specification. Fresh
  results are never persisted.
- No schema, evidence format, model identity, deterministic ID, overwrite or
  numerical-methodology change. No new dependencies.
- Not claimed: cross-machine/cross-platform bitwise reproducibility, or scientific
  validity from a passing check.

## [Milestone 6] - Scientific trust: evidence verification

### Added

- **First-party evidence verification.** `drw.execution.evidence.verify_evidence`
  checks an evidence package against its manifest read-only: every declared
  artifact must exist, stay inside the manifest's directory, and match its recorded
  size and SHA-256. It reports `ok`, `missing`, `size_mismatch`, `hash_mismatch`,
  `invalid_path`, `invalid_entry` and `unreadable` per artifact. Undeclared files
  are listed in `extra_files` and are explicitly **not** verified (they do not, on
  their own, fail verification).
- **`drw verify` CLI subcommand** (exit 0 = verified, 1 = failed verification,
  2 = unusable manifest/path).
- **`verify_evidence` bridge op** (read-only) which resolves the manifest from the
  stored experiment (`experiment_id`) so arbitrary filesystem paths are never
  reachable from the web layer.

### Changed

- **Documentation corrected to match ADR-0006 and the code:** the relative-change
  rule in `drw/numerics/delta.py` and the acceptance matrix now reads
  `r = Δy/y_ref` where `|y_ref| > ε`, else `NaN` (flagged). No numerical change.

### Fixed

- **Empty evidence manifests are rejected (audit F1).** A manifest with an empty
  `files` list now raises `EvidenceVerificationError` instead of verifying
  `ok=true` with zero artifacts. `drw verify` exits 2; the bridge returns
  `bad_request`.
- **Directory-listing errors are controlled (audit F3).** An `OSError` while
  listing the evidence directory is reported as `EvidenceVerificationError` rather
  than propagating uncaught; the CLI exits 2 and the bridge returns `bad_request`.

### Notes

- **Consistency, not cryptographic authenticity.** The manifest is not self-hashed
  or signed, so a successful verification does not protect against a party who can
  rewrite both the artifacts and the manifest. Nothing is written by verification.
- No change to experiment identity, deterministic ids, overwrite behaviour,
  schemas, model hashes, numerical methodology or the evidence format.
- Investigation and rationale: `docs/reports/milestone-6-investigation.md`.

## [Milestone 5] - Model-agnostic experiment workflow

### Added

- **Model picker (ADR-0012).** The researcher workspace now lists every
  registered model (`oscillator`, `predator-prey`, `lorenz`) and can start a new
  experiment from any of them. Creation reuses the existing
  `sample_experiment(model_id)` / `drw.demo.build_demo_experiment` path; **no new
  bridge operation or numerical code** was added.
- **Technical eligibility, explained.** `modelViability` derives whether a model
  can seed an experiment from its declared `capabilities` (a numeric parameter to
  vary and a comparable output). Ineligible models are disabled in the picker
  with the reason; the UI states that eligibility is technical, **not**
  scientific validity.
- **Authoritative metadata in the model panel.** `ModelPanel` now shows each
  parameter's `description` (and output descriptions) straight from the model
  schema, plus a "what this model supports" block (factorable parameters,
  outputs, sensitivity, limitations).
- **Demonstration labelling.** A newly seeded experiment is labelled in the UI as
  a **demonstration** (+10% on the first input), explicitly not a scientifically
  justified experiment.
- **Observation vs. conclusion.** The Results overview states that outputs are
  simulated results for the configured model/baseline/intervention - an observed
  simulation result, not an established scientific conclusion.
- Tests: web `Workspace.m5.test.tsx` (model selection, metadata, validation
  failure, result rendering, eligibility) and `modelViability` unit tests;
  Python `test_api_bridge.py` now asserts that **every** registered model seeds,
  validates and executes through the bridge.

### Changed

- `Workspace` loads a model's `capabilities` alongside the model list; the sample
  action is preserved as the predator-prey regression example.

### Notes

- **No persistence-semantics change.** Deterministic `exp-<hash12>` ids and
  identical-spec overwrite are documented, not altered. No Python core, bridge,
  schema or storage changes.
- A baseline timing flake in the Python-backed `Workspace.e2e.test.tsx` was
  recorded and fixed by allowing real subprocess startup (see
  `docs/reports/milestone-5-baseline.md`).
- Isolation remains a process boundary, **not** a sandbox (ADR-0005).

## [Milestone 4.5 - Carbon UI] - Design-system adoption

### Changed

- **UI migrated to the IBM Carbon Design System** (`@carbon/react` 1.117.0,
  `@carbon/styles`, `@carbon/icons-react`, Dart Sass). The custom
  `globals.css` design system was removed. Every primary screen (shell, sidebar,
  model/experiment editor, validation, review, planner, results tabs, tables,
  charts legend) now uses Carbon components and tokens.
- Application shell: Carbon `Header` + skip link; theme toggle between Carbon
  `g10` (light, default) and `g100` (dark), persisted in `localStorage`.
- Layout helpers use Carbon spacing/type tokens and CSS custom properties;
  no hard-coded hex values were introduced.

### Added

- **Automated accessibility suite** (`e2e/accessibility.spec.ts`): axe-core
  (light + dark) with a zero serious/critical gate, plus a keyboard test for the
  skip link, sample action, project select, baseline field and validation.
- Documentation: `docs/architecture/carbon-design-system.md`,
  `docs/testing/acceptance-matrix.md`,
  `docs/reports/milestone-4.5-baseline.md`,
  `docs/reports/milestone-4.5-final-acceptance.md`.

### Fixed

- axe `scrollable-region-focusable` (serious) caused by Carbon `CodeSnippet`'s
  non-focusable scrollable `<pre>`; the spec and evidence previews are now
  focusable `<pre>` elements (documented exception).
- jsdom lacked `ResizeObserver`/`matchMedia`, which Carbon components require;
  inert stubs added to the Vitest setup.
- The workspace context line now shows the active project name instead of
  "no project" before projects finish loading.

### Notes

- **No Python, bridge, schema or storage changes.** Scientific behaviour is
  unchanged; all 160 Python tests still pass.
- pnpm build scripts for the Carbon/IBM packages are explicitly declined
  (`allowBuilds: false`) because they ship prebuilt CSS/fonts.

## [Milestone 4.5] - Local launch and interactive acceptance

### Added

- **Windows launcher** `scripts/start-local.ps1` (root script `pnpm start:local`):
  checks Node/pnpm/Python, verifies the scientific core is importable, finds a free
  port, wires `DRW_PYTHON`/`DRW_WORKSPACE`, prints the URL, and never kills other
  processes or deletes data.
- **Live acceptance harness**: `apps/web/playwright.local.config.ts` and
  `apps/web/e2e/local-acceptance.spec.ts` drive the already-running app in Chromium
  and assert no console errors / 5xx responses.
- **Local run guide** `docs/local-run.md`; acceptance report
  `docs/reports/milestone-4.5-local-acceptance.md`.

No functional defects were found during the walkthrough; no scientific, contract
or UI behaviour changed.

## [Milestone 4] - Browser trust, projects, and AI experiment planning

### Added

- **Browser end-to-end tests (Playwright).** `apps/web/e2e/workspace.spec.ts` runs
  the production build in Chromium: open, load the sample, configure baseline and
  intervention, reject an invalid configuration, run, inspect plots and metrics,
  reload a saved experiment, export evidence, and exercise the timeout path.
  `pnpm --filter @drw/web e2e` builds and runs it.
- **Measured execution progress (ADR-0009).** A local job journal
  (`drw.jobs`, `<workspace>/jobs/<id>.jsonl`) records `started`,
  `run_completed` and `finished` events; the client supplies `job-<16 hex>`, polls
  the new `job_status` op, and the UI shows "k of n runs completed". No invented
  percentages. Cancellation semantics are unchanged (abort kills the child).
- **Minimal projects (ADR-0010).** `drw.store` gains `projects/<id>.json`,
  `create_project`, `list_projects`, and `project_id` on experiment metadata with
  a `project_id` filter for listings. Legacy experiments without a `project_id`
  are read as `default` and never rewritten. New ops `list_projects`,
  `create_project`; UI project selector and creation.
- **Model capabilities.** `drw.capabilities.model_capabilities` derives factorable
  / fixed / state / categorical parameters, time-series and scalar outputs,
  sampling and analysis methods, sensitivity availability, isolation and honest
  limitations. Exposed via `capabilities` and included in `describe_model`.
- **AI experiment planner (ADR-0011).** `drw.planner` proposes an `ExperimentSpec`
  from a question. Deterministic rule-based planner by default; optional
  server-side LLM provider (off unless configured). Proposals are validated by the
  authoritative Python validator, are never auto-executed, and require explicit
  approval. New ops `plan_experiment`, `planner_status`; UI planner panel with
  user input / AI suggestion / assumptions / open questions / validation and a
  human-readable preview.
- **Execution timeout control** in the review step, written into
  `execution.timeout_s`.

### Notes

- No new runtime dependencies: the bridge, journal, projects and planner use the
  standard library and existing packages. Playwright is a devDependency.
- The LLM HTTP client is not automatically tested without a key; the rule-based
  planner and the untrusted-field filtering are covered by tests with a fake
  provider.
- Isolation remains a process boundary (ADR-0005), not a sandbox.

## [Milestone 3] - Researcher-facing workspace

### Added

- **JSON bridge (`drw.api`, ADR-0008).** One-shot `python -m drw.api` boundary
  with ops `list_models`, `describe_model`, `sample_experiment`, `validate`,
  `run`, `list_experiments`, `get_experiment`, `evidence`, `export_evidence`,
  `sensitivity`, `environment`. Reuses the existing contracts and engine; no new
  Python dependency.
- **Local experiment store (`drw.store`).** Filesystem store per experiment
  (`spec.json`, `results.json`, `meta.json`, `evidence/`) with id validation and
  path-containment checks; reopening returns the stored spec unchanged.
- **Reusable OAT sensitivity (`drw.sensitivity`).** Extracted from the demo so the
  CLI, the bridge and the UI share one implementation.
- **Web workspace (`apps/web`).** Next.js App Router UI: model panel, baseline vs
  intervention editor, validate, review-before-run, run with cancel, and results
  organized into Overview / Plots / Metrics / Sensitivity / Reproducibility, with
  saved-experiment list and reopen. Route handlers call the bridge; TypeScript
  contains no scientific computation.
- **Web tests.** Pure helper tests, handler/bridge integration tests (node), UI
  state tests (validation, failure, cancellation, timeout) and a real end-to-end
  test that renders the UI and executes the Python core, including evidence export
  and reopen.

### Notes

- Isolation remains a process boundary (ADR-0005), not a security sandbox; the UI
  states this explicitly.
- A FastAPI `services/api` and browser-level (Playwright) tests are deferred; see
  ADR-0008.

## [Milestone 2] - Scientific trust and execution hardening

### Added

- **Isolated execution (ADR-0005).** `ExecutionSpec.isolation` (`subprocess`
  default). `drw.execution.worker` runs one model per process;
  `SubprocessExecutor` enforces `timeout_s` as a hard wall-clock limit, kills the
  process tree, redirects output to files in a private temp dir, always cleans up,
  and records deterministic failures (`timeout`, `cancelled`, `worker_crash`,
  `invalid_worker_response`, `worker_model_error`). `Runner.run(cancel_event=...)`
  supports cancellation. `RunRecord.isolation`/`timed_out` added.
- **Non-finite and missing-data handling (ADR-0006).** A run is `SUCCEEDED` only
  when every output value is finite; otherwise `FAILED` with `non_finite_output`.
  Comparisons mask non-finite pairs and report `valid_points` /
  `non_finite_points`. `ParameterSpec` now rejects non-finite nominal/bounds.
- **Analysis resilience.** An incompatible or missing output no longer aborts the
  experiment; it is reported (`comparison_failed`, `output_missing_for_comparison`)
  and the remaining outputs/variants still compare.
- **Sampling diagnostics.** `grid` + `n_samples` warns `n_samples_ignored`;
  stochastic sampling with a `steps` factor warns `factor_steps_ignored`.
- **Sensitivity interpretation.** The demo now reports normalized `elasticity`
  alongside `abs_delta`, flags bound-clamped perturbations, and states that OAT
  cannot detect interactions.
- **Independent numerical checks.** Error-vs-tolerance convergence against the
  analytic oscillator, RK45-vs-BDF agreement, and an analytic Lotka-Volterra
  equilibrium stationarity test.
- **Contract versioning (ADR-0007).** `analysis` accepted as an input alias for
  `analyses`; `schema_version_mismatch` warning. Schema drift and TS parity tests.
- **Environment hash refinement.** `environment_hash` excludes the interpreter
  path so identical environments agree across machines.
- **Run lifecycle docs.** `docs/architecture/run-lifecycle.md`; `TERMINAL_STATES`
  and `is_terminal` exported; the runner enforces transitions.

### Changed (scientific behaviour)

- A non-finite solve is now a `FAILED` run returning no outputs (was `SUCCEEDED`).
- Comparison metrics over partially non-finite series are now computed over finite
  pairs and are finite; previously they propagated `NaN` silently.
- `environment_hash` values change (interpreter path excluded).

## [Unreleased]

### Added

- **Repository bootstrap (INFRA-001).** pnpm workspace, Python package layout,
  CI workflow, lint/test configuration, and the specification's directory
  skeleton.
- **Foundational schemas (SCHEMA-001/002).** `ModelSchema` (parameters, units,
  bounds, roles, differentiability) and `ExperimentSpec` (hypothesis, baseline,
  factors, sampling, constraints, analyses, execution, verification, reporting),
  with deterministic canonical JSON hashing for provenance.
- **Run state machine (RUN-001).** Immutable run records with an explicit
  lifecycle (`DRAFT -> VALIDATED -> QUEUED -> RUNNING -> SUCCEEDED | FAILED`,
  then `ANALYZED -> VERIFIED -> EXPORTED`); retries create linked attempts.
- **ODE adapter (SCI-001).** `scipy.integrate.solve_ivp` wrapper with
  `auto`/`explicit`/`stiff` solver selection; solver choice and tolerances are
  recorded on every run.
- **Sampling (SCI-002).** Deterministic grid, random, Latin hypercube and Sobol
  designs with seeds; Sobol power-of-two guidance is surfaced as a warning.
- **Delta analysis (SCI-003).** Absolute and relative deltas with
  denominator-safety flagging, plus MAE/RMSE/max-abs/area/peak-shift/correlation
  metrics and explicit time-series alignment.
- **Golden models (SCI-004).** Mass-spring-damper (analytic reference),
  Lotka-Volterra predator-prey (conserved quantity), and Lorenz (determinism and
  divergence).
- **Local execution (SCI-005).** Deterministic local runner, environment
  fingerprinting, and an evidence package (manifest + hashes + results + report).
