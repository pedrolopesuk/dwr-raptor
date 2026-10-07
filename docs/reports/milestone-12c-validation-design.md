# M12C — Validation / Generalisation: Research, Architecture & Specification

**Status:** Research + design only. **No implementation.** No code, contract or schema in this
repository was modified to produce this document. Nothing here should be read as an existing
capability.

**Prepared against:** M12A Evaluation (`drw/evaluation.py`, `drw/schema/evaluation.py`), M12B
Calibration (`drw/calibration/**`, `drw/schema/calibration.py`, `drw/calibration_store.py`), M11
observations (`drw/schema/observation.py`, `drw/observations.py`, `drw/dataset_store.py`), the
Runner/evidence layer, and the current frontend `ScientificStatus` component.

**Notation used throughout.** `[implemented]` = exists today and is relied on. `[recommended]` =
this document's proposal. `[deferred]` = deliberately pushed to M12C+.

---

## 1. Executive summary

Validation in DRW is the scientific claim that a model, **with parameters frozen by a calibration**,
reproduces **independent observations that were not used to fit it**. It is a *predictive* claim made
relative to a defined domain, not a statement of truth. It is materially different from M12A
evaluation ("does the model agree with these observations?") and from M12B calibration ("which
parameters best agree with these observations?").

The core design decisions:

1. **Validation reuses M12A wholesale.** A validation execution produces frozen-parameter model
   outputs; M12A `evaluate_run` compares them to the validation dataset and returns metrics,
   residuals and exclusions. M12C adds *no* comparison mathematics and *no* new residual/alignment/
   unit logic. `[recommended, building on implemented M12A]`
2. **Independence is a structured model, not a boolean.** A `ValidationDataset` carries an explicit
   `IndependenceSpec` describing the dimensions along which it is claimed independent
   (dataset identity, coordinate/time window, entity/group, stratum/regime, measurement process).
   DRW **mechanically verifies** what it can (different content hash, disjoint coordinate windows,
   disjoint declared group keys) and **records but does not prove** the rest, disclosing the
   difference. `[recommended]`
3. **Freezing is enforced by construction and proven by provenance.** Validation references a
   `CalibrationResult` by its content hash (`result_hash`), takes its `best.parameters` as a fixed
   baseline, and executes a fixed-parameter run through the existing `Runner`. There is no optimizer
   in the validation path, so validation *cannot* refit. The `ValidationResult` records the frozen
   vector and the calibration hashes so a reader can see no refit occurred. `[recommended]`
4. **Three orthogonal statuses, never one boolean.** (a) *agreement* (does the model reproduce the
   held-out observations?), (b) *acceptance* (does it meet an explicit, user-defined criterion?),
   (c) *independence* (was the evidence verified independent, or only declared?). A result can be
   "agrees / no criterion specified / declared-not-verified". These never collapse. `[recommended]`
5. **Per-dataset results are preserved; aggregation is optional and explicit.** Multiple validation
   datasets produce one result *per dataset*; a combined scalar is produced only on explicit
   request and only when units/metrics are compatible — otherwise DRW fails closed rather than
   silently averaging incomparable numbers. `[recommended]`
6. **No universal pass/fail; thresholds are user-supplied and clearly labelled as arbitrary.**
   DRW distinguishes "validated" (ran correctly over verified-independent data) from "meets the
   acceptance criterion you supplied". A passing threshold is never presented as scientific truth.
   `[recommended]`
7. **Fail closed; stale rather than silently authoritative.** Any missing hash, incompatible unit,
   empty dataset, unmappable observation or invalid frozen parameter fails that dataset (and, for
   structural problems, the whole validation). If any input a result depended on changes, the result
   is reported **stale/invalid**. `[recommended]`

**Recommendation: SHIP M12C AS SPECIFIED** — *explicit holdout validation of a frozen calibration,
orchestrated through the existing Runner and evaluated by M12A, with mechanical independence checks,
per-dataset results, optional explicit acceptance criteria, content-addressed persistence, and
staleness detection* — **with cross-validation, cross-dataset scalar aggregation, and
extrapolation/regime classification deferred to M12C+** (they are explicitly out of the specified
scope; see §13, §14, §29). Rationale in §32.

---

## 2. Scientific definition of validation for DRW

**DRW validation is:** *given a completed calibration that fitted a bounded parameter vector to a
designated calibration dataset, and given one or more validation datasets that are asserted and (so
far as mechanically possible) verified to be independent of the calibration dataset, execute the
model with the **frozen** calibrated parameters over each validation dataset under an explicit
observation mapping and evaluation configuration, and report — per validation dataset — the
agreement between model and observations, the independence evidence, the (optional) acceptance
outcome, and an explicit statement of what this does and does not establish.*

Formally, for calibration result `C` with frozen parameter vector `θ*`, and validation dataset `V`
with mapping `M` and evaluation config `E`:

```
validation(V) = M12A.evaluate_run( Runner.run(spec(baseline = θ* ∪ fixed, factors = ∅)), V, M, E )
```

The only new object is the **orchestration** that (i) freezes `θ*`, (ii) records independence
evidence, (iii) forbids refitting, and (iv) frames the outcome. All measurement is M12A's.

**Validation is NOT:** a rerun of the calibration data; a likelihood; a posterior predictive check;
a causal claim; a guarantee outside the tested domain; a generalisation bound.

---

## 3. Terminology

| Term | Meaning in DRW |
|---|---|
| **Calibration dataset** | The dataset (M11) used to fit parameters in a completed M12B run. Its `content_hash` is the calibration artifact identity. |
| **Validation dataset** | An M11 dataset used *only* to test the frozen model. Must be distinct from the calibration dataset. |
| **Holdout / held-out** | Observations excluded from fitting and reserved for validation. In DRW this is realized as a *separate dataset*, not an internal split. |
| **Independence** | The structured assertion + verification that the validation dataset does not share the information used to fit. See §5. |
| **Verified independence** | Independence DRW can prove mechanically from content hashes / coordinate ranges / declared group keys. |
| **Declared independence** | Independence asserted by the user and recorded, but not provable by DRW. Always disclosed. |
| **Frozen parameters** | The `best.parameters` of a calibration result, held fixed for validation. |
| **Acceptance criterion** | A user-supplied predicate on a named metric (e.g. `rmse <= 0.5`). Arbitrary by nature; labelled as such. |
| **Generalisation gap** | A *reported* comparison between a calibration metric and the same metric on the validation data. Descriptive, not a decision. |
| **Domain of validity** | The region of input/parameter/entity space actually exercised by calibration+validation. DRW records what was tested; it does not extrapolate claims beyond it. |
| **Extrapolation / interpolation** | Whether a validation point lies outside (extrapolation) or inside (interpolation) the range of the calibration data along a declared coordinate. See §14. |
| **Stale / invalid result** | A stored validation whose inputs no longer match the hashes it recorded. |

---

## 4. Validation data model

Validation is expressed as a **config + execution + result**, mirroring M12B's shape (request →
outcome), and consumes an existing `CalibrationResult`.

```
CalibrationResult  ──(frozen θ*, result_hash)──┐
ValidationDataset[] ──(DatasetRef + mapping + independence spec)──┤
ValidationConfig ──(datasets, metrics, acceptance, budget, execution)──┼──▶ ValidationResult
Validation execution (Runner + M12A per dataset) ─────────────────────┘
```

**New contracts required** (`[recommended]`):
- `ValidationConfig` — the request (§7).
- `ValidationResult` — the outcome (§8).
- `ValidationDataset` — one validation target: `DatasetRef` + `ObservationMapping` +
  `IndependenceSpec` + optional acceptance override.
- `IndependenceSpec` — the structured independence model (§5).
- `AcceptanceCriterion` / `AcceptanceOutcome` — explicit user criteria and their evaluation (§6/§10).
- `ValidationContext` — the (partly derived) interpolation/extrapolation classification (§14).
- `ValidationProvenance` — the provenance chain (§17).
- `ValidationRef` — content-addressed reference for persistence.
- A `ValidationStore` mirroring `CalibrationStore` (`[implemented]` pattern) — §21.

**Not new:** observations, units, uncertainty, alignment, residuals, metrics, the Runner, evidence
packaging. All reused.

The shape is chosen so that validation is *composition*, exactly as the brief suggests:
`CalibrationResult + ValidationConfig + execution + M12A = ValidationResult`.

---

## 5. Independence model

Independence is **not** a boolean. It is a set of declared dimensions, each with a mechanical
verification result where possible.

```
IndependenceSpec:
  vs_dataset:        DatasetRef            # the calibration dataset being controlled against
  coordinate_windows: { coord: (lo, hi) }  # optional explicit windows (numeric or ISO-8601 datetime)
  group_key:          str | None           # e.g. an entity/campaign/region column name
  claimed_dimensions: [ "dataset" | "time_window" | "entity" | "region" | "measurement_process" | "experiment" ]
  declaration:        str                  # free text: why the user asserts independence
```

For each claimed dimension DRW produces an `IndependenceCheck`:

| Dimension | What DRW can do mechanically | Classification |
|---|---|---|
| `dataset` | Compare `dataset.dataset_id` / `content_hash`; also compare `science_hash` (same measurements, different provenance) and `files[].sha256`. | **verified** if hashes differ; **violated** if identical. |
| `time_window` | If the mapped coordinate is `datetime` (or numeric with a unit), compare min/max of the calibration window vs the validation window; require disjoint. | **verified** if disjoint; **violated** if overlapping. |
| `entity` | If a `group_key` column exists on both datasets, compute the value sets and require intersection = ∅. | **verified** if disjoint; **violated** if shared values. |
| `region` | Same as `entity` using a declared region/stratum column. | **verified** / **violated** / **declared** (see below). |
| `measurement_process` | Compare dataset `provenance` (`source_kind`, adapter id/version, `source_uri`, `source_sha256`). Different process ⇒ *supporting* evidence, not proof. | **declared** (recorded, never upgraded). |
| `experiment` | Compare the originating experiment/run lineage if recorded. | **declared**. |

Rules:
- DRW **never upgrades** `declared` to `verified`.
- A `violated` check is a **hard failure** for that validation dataset (leakage; §11) — unless the
  user explicitly marks it as a *descriptive, non-independent* run, in which case the result is
  reported but can never be labelled independent/supported.
- A `declared`-only validation is fully reported, with the disclosure that independence is
  user-asserted, not proven.
- If a `claimed_dimension` cannot be checked at all (missing column/coordinate), it is recorded as
  `unverifiable` (a distinct state from `declared`), also disclosed.

This yields a per-dataset `IndependenceReport` = list of checks + a roll-up: `verified` (all claimed
dimensions verified), `partially_verified`, `declared_only`, or `violated`.

**What DRW cannot see.** Data leakage through an *external* preprocessing step, a shared upstream
file that was re-imported as a new dataset (partially detectable via `files[].sha256` and
`source_sha256`), or a validation set chosen *after* looking at results. These are recorded as
declarations and disclosed; DRW does not pretend to prove them.

---

## 6. Calibration → validation relationship

**Freezing (`[recommended]`, enforced structurally).**
- `ValidationConfig.calibration` = `CalibrationRef` (`result_hash` + `calibration_id`). DRW resolves
  the stored `CalibrationResult` (§ `CalibrationStore.load`, `[implemented]`).
- The frozen vector is `CalibrationResult.best.parameters` (a `dict[str,float]`; `[implemented]`).
  If `best` is `null` (a failed calibration), the validation is **invalid before execution**
  (fail closed): there is nothing to validate.
- The fixed-parameter set is reconstructed exactly as M12B does: free parameters come from
  `best.parameters`; everything else is the calibration's fixed set / experiment baseline
  (`[implemented]` logic, reused).
- The validation build produces a **single-run** `ExperimentSpec` (`factors=∅`, `analyses=∅`,
  `max_runs=1`) per validation dataset, executed through the **existing** `Runner` —
  exactly the M12B candidate-spec pattern (`[implemented]`).
- **No optimizer exists in the validation path.** Validation cannot modify parameters. This is the
  mechanical proof of "no refit".

**What the validation result records about the calibration** (for provenance, §17):
`calibration.result_hash`, `calibration.calibration_hash`, `calibration.best.parameters` (the exact
frozen vector), `calibration.provenance.model_hash`, `calibration.provenance.dataset_content_hash`
(the calibration dataset), `calibration.provenance.mapping_hash`, and the paired
`evaluation_hash`.

**Cross-check at run time.** After executing, DRW re-reads the produced `EvaluationResult.parameter_snapshot`
and asserts it equals the frozen vector; a mismatch is a fail-closed internal error
(`validation_parameter_mismatch`). This makes a refit (or an accidental parameter change) detectable
rather than merely forbidden.

**Direction of dependency.** Validation depends on calibration; calibration never depends on
validation. Recomputing a calibration invalidates any validation that referenced the old
`result_hash` (§19).

---

## 7. ValidationConfig proposal

```
ValidationConfig:
  schema_version: str
  experiment_id: str                # the investigation/experiment the model belongs to
  model_ref: ModelRef
  calibration: CalibrationRef       # { calibration_id, result_hash, experiment_id, model_id, status }
  datasets: tuple[ValidationDataset, ...]   # >= 1
  evaluation: EvaluationConfig      # reused M12A config (metrics, residual modes, alignment, ...)
  budget: ValidationBudget          # §15
  execution: ExecutionTemplate      # reuses the M12B template shape (solver, timeout_s, isolation, max_runs=1)
  acceptance: tuple[AcceptanceCriterion, ...] = ()   # optional, explicit (§10)
  aggregate: AggregationPolicy = "none"              # "none" | "explicit" (§5, §10)
  notes: str = ""

ValidationDataset:
  dataset: DatasetRef
  mapping: ObservationMapping
  independence: IndependenceSpec
  label: str = ""
  acceptance: tuple[AcceptanceCriterion, ...] | None = None   # per-dataset override

ValidationBudget:
  max_evaluations: int              # hard cap (§15)
  max_wall_seconds: float
  max_failed: int | None = None

AcceptanceCriterion:
  metric: str                       # an M12A metric name
  observation: str | None           # pair selector when the mapping has >1 pair
  output: str | None
  op: "<=" | "<" | ">=" | ">"
  value: float
  rationale: str = ""               # free text; the criterion is the user's, not DRW's
```

Validation rules (`[recommended]`, fail closed):
- `datasets` must be non-empty; duplicate `dataset_id` rejected.
- Each `mapping.model_ref.model_id` must equal `model_ref.model_id`.
- Each `mapping.dataset` must equal that dataset's ref.
- Each `acceptance.metric` must be requested in `evaluation.metrics` (same rule M12B uses for its
  objective, `[implemented]` analogue).
- `aggregate="explicit"` requires all datasets to share a **compatible unit** for the aggregated
  pair; otherwise configuration error.
- `independence.vs_dataset` must reference the calibration's dataset; DRW confirms
  `vs_dataset.content_hash == calibration.provenance.dataset_content_hash`.
- `data_role` for validation datasets is `"validation"`; the M12B `DataRole` literal currently only
  permits `"calibration"` (`[implemented]`) — M12C adds `"validation"` to a *validation-local* role
  enum rather than widening M12B's.

---

## 8. ValidationResult proposal

```
ValidationResult:
  schema_version: str
  validation_hash: str              # REQUEST identity (§18)
  result_hash: str                  # OUTCOME identity (§18)
  experiment_id: str
  model_ref: ModelRef
  config: ValidationConfig
  calibration: CalibrationSnapshot  # { result_hash, calibration_hash, parameters, model_hash,
                                    #   dataset_content_hash, mapping_hash, evaluation_hash }
  datasets: tuple[ValidationDatasetResult, ...]   # one per validation dataset
  agreement_status: AgreementStatus                # §20
  acceptance_status: AcceptanceStatus              # §20
  independence_status: IndependenceStatus          # §20
  evaluations_requested: int
  evaluations_completed: int
  evaluations_failed: int
  wall_seconds: float
  diagnostics: tuple[Diagnostic, ...]
  provenance: ValidationProvenance   # §17
  note: str                          # mandatory disclosure (§20)

ValidationDatasetResult:
  label: str
  dataset: DatasetRef
  mapping_hash: str
  independence: IndependenceReport   # checks + roll-up (§5)
  context: ValidationContext         # interpolation/extrapolation classification (§14)
  run_id: str | None
  run_status: str | None
  evaluation_hash: str | None        # M12A result hash for the frozen run
  metrics: dict[str, float | None]   # the requested M12A metrics
  n_used: int
  n_excluded: int
  exclusion_counts: dict[str,int]
  calibration_metrics: dict[str, float | None]   # same metrics on the CALIBRATION dataset (gap)
  acceptance: tuple[AcceptanceOutcome, ...]
  agreement: AgreementStatus
  failure: str | None                # fail-closed code (§16)
  diagnostics: tuple[Diagnostic, ...]

AgreementStatus  = "agrees" | "partial" | "does_not_agree" | "inconclusive" | "failed" | "not_run"
AcceptanceStatus = "met" | "not_met" | "not_specified" | "indeterminate"
IndependenceStatus = "verified" | "partially_verified" | "declared_only" | "violated" | "unknown"
```

Design notes:
- **Information preservation first.** Per-dataset results are always present. There is **no implicit
  scalar**. `aggregate="explicit"` adds an `AggregateResult` field only when requested and valid.
- **`calibration_metrics` are re-derived, not stored from M12B.** M12B's `CalibrationResult` keeps
  the *objective* value and per-candidate metrics, but not necessarily the full metric set for the
  fit. To report a like-for-like generalisation gap, DRW re-evaluates the frozen parameters against
  the **calibration dataset** via M12A at validation time (one extra run), and records that
  evaluation's hash. This guarantees the gap compares the *same* metrics of the *same* model+params
  on two datasets. `[recommended]` (Alternative — read the objective from M12B — is rejected because
  it mixes metric names/configs.)
- **`agreement_status` is not pass/fail.** It describes whether held-out observations are reproduced
  (derived from whether usable metrics exist and, if an agreement rule is configured, whether they
  are within it). Absent an explicit agreement rule, `agreement` is `agrees` only when the model
  produced usable comparisons; the *degree* is in the metrics. DRW does not invent a threshold.
- **`acceptance_status` is separate** and is `not_specified` unless the user supplied criteria.
- Everything is content-addressed and deterministic (no timestamps in identity).

---

## 9. Dataset / observation requirements

Reuse the M11 contract (`[implemented]`) unchanged. A validation dataset must:
- be a stored, content-addressed `Dataset` (`content_hash` verified by `DatasetStore`);
- declare `role: measurement` variables that map to model outputs, with units compatible (explicit
  conversion allowed via `MappingPair.unit_conversion` exactly as M12A);
- share the model's expected coordinate semantics (numeric with unit, or ISO-8601 datetime);
- be **distinct** from the calibration dataset (checked, §11).

**Uncertainty-aware observations.** If the calibration used weighted metrics (σ from `std`/
`precision`), validation must use the *same* `EvaluationConfig` to be comparable; DRW records the
config hash and refuses an aggregate across datasets that used different evaluation configs.
`stderr`/`asymmetric`/`interval` are never collapsed to σ (M12A rule, `[implemented]`).

**Missing/quality.** Reuse M12A's exclusion accounting (`usable_count`, `excluded_count`,
`exclusion_counts`). Validation **reports** exclusions per dataset; it never silently drops rows.

**Empty / all-excluded datasets.** Fail that dataset closed (§16).

---

## 10. Metric strategy

**Principle: reuse M12A metrics; add no new comparison mathematics.**

Implemented M12A metrics (`[implemented]`): `mean_residual`, `mae`, `rmse`, `max_abs_error`,
`relative_mae`, `relative_rmse`, `max_abs_relative_error`, and opt-in `weighted_rmse`, `chi_square`,
`reduced_chi_square` (explicit `degrees_of_freedom`).

Recommendation:
- **Core (generic, unit-consistent, always meaningful with usable observations):** `rmse`, `mae`,
  `max_abs_error`, plus counts (`n_used`, `n_excluded`). These are the default validation metrics.
- **Optional, opt-in:** `relative_*` (report but flag the `|y_obs| <= relative_epsilon` denominator
  cases), `weighted_rmse`/`chi_square` (only when σ is usable and the same config was used for
  calibration), `mean_residual` (signed; can cancel — report but never as the sole criterion).
- **`reduced_chi_square`:** only when `degrees_of_freedom` is *explicitly* supplied; DRW never
  estimates dof (M12A rule, `[implemented]`).
- **Explicitly NOT added now** `[deferred]`: R², MAPE/sMAPE, log-space metrics, domain metrics,
  coverage/interval scores, likelihood-based scores.
  - **R²** is ambiguous without a defined reference model (variance baseline) and is not comparable
    across datasets; adding it invites misuse. Defer.
  - **MAPE/sMAPE** are ill-defined near zero and unit-dependent; M12A already provides relative
    metrics with explicit denominator handling. Defer.
  - **Log-space** metrics imply a log transform of the observable; that is a data/model decision,
    not a generic validation metric. Defer.
  - **Domain-specific metrics** violate domain-neutrality. Defer to adapters/plugins.

**Generalisation gap.** Report, per metric, `validation_value − calibration_value` (same model,
params, mapping semantics, metric config). This is a *descriptive* number; the UI must not present a
positive gap as "overfitting" without context. `[recommended]`

**Multiple datasets / multiple pairs.** Report per dataset and per pair; **do not** summarize across
datasets unless `aggregate="explicit"` and units are compatible. Even then, the aggregate is a
labelled convenience, never the authoritative result.

**Zero/near-zero observations, missing values, uncertainty.** Handled exactly as M12A: relative
metrics are undefined where `|observed| <= relative_epsilon` (flagged); missing/quality rows are
excluded with reasons; weighted metrics require usable σ. No new rules.

---

## 11. Leakage prevention

**Mechanically preventable/detectable (`[recommended]`):**
1. **Same dataset** — `validation.dataset.content_hash == calibration.dataset_content_hash` ⇒
   `violated` (hard fail unless explicitly marked descriptive).
2. **Same science, different provenance** — equal `science_hash` (`[implemented]`) ⇒ `violated`
   (it is the same measurements).
3. **Identical source file** — equal `files[].sha256` or equal `provenance.source_sha256` ⇒
   `violated`.
4. **Overlapping time window** — computed from datetime/numeric coordinate ranges ⇒ `violated`.
5. **Shared entities** — non-empty intersection of declared `group_key` values ⇒ `violated`.
6. **Identical run lineage** — same originating experiment/run id ⇒ `violated`.

**Detectable-as-signal (not proof):**
7. Same `source_uri`, adapter, or `source_kind` ⇒ *supporting* evidence toward independence, recorded
   as `declared`.

**Not preventable by DRW (must be disclosed as declared):**
8. A validation set chosen *after* seeing results; leakage through an external preprocessing pipeline
   that produced a genuinely distinct artifact; information leakage through the model's fixed
   constants; using validation feedback to *choose* the model/parameters (that is model selection,
   outside M12C). DRW records a user declaration and a mandatory disclosure; it never claims to have
   prevented these.

**Selection-leakage guard.** Because a *recorded* calibration must precede validation and validation
cannot refit, "parameter selection using validation results" would require the user to re-run
calibration on a changed dataset — which changes `result_hash` and makes the validation stale
(§19). DRW makes the leak *visible*, not impossible.

---

## 12. Temporal / spatial / group validation

- **Temporal** is a special case of the coordinate-window check: calibration window `[t0, t1]`,
  validation window `[t2, t3]` with `t2 > t1` (holdout-forward) or disjoint windows. Represented by
  the M11 datetime coordinate + explicit `coordinate_windows` in `IndependenceSpec`; **no new
  time-series system**.
- **Spatial/geographic** is the `region`/`group_key` case: a declared stratum column; DRW checks
  value-set disjointness.
- **Entity/subject** is the same `group_key` case.
- **Experiment-level** uses the `experiment` dimension (lineage).

All are expressed through one generic mechanism (windows + group keys + declared dimensions). No
domain-specific types.

---

## 13. Cross-validation recommendation

**Recommendation: DEFER cross-validation to M12C+.** `[deferred]`

Reasons:
- CV multiplies executions (k×) and, more importantly, introduces **fold construction** decisions
  (k, stratification, grouping, blocking) that are easy to get scientifically wrong and hard to make
  reproducible and transparent.
- The scientifically safest first step is the **explicit holdout** the user controls: distinct
  datasets, distinct windows. This is what M12C v1 specifies and it needs no hidden splitting.
- Grouped/blocked/temporal CV is the natural extension *once* the explicit-holdout path exists and
  its provenance/independence model is proven. It can then be built as an explicit **split plan**
  (a `SplitSpec` that yields named calibration/validation dataset pairs) rather than a hidden loop.
- Leave-one-group-out is a special case of grouped CV and is deferred with it.

When M12C+ adds CV: it should be a **visible, declarative split** (reproducible, seeded, recorded),
executed as a sequence of ordinary calibration+validation pairs, not a new engine.

---

## 14. Extrapolation / interpolation classification

`[recommended, minimal]` — record a `ValidationContext` per dataset that is **derived only where
mechanically derivable**, and otherwise **declared**:

- **Coordinate range:** compare each validation coordinate's min/max to the calibration dataset's
  min/max along the same (mapped) coordinate ⇒ `within_range` (interpolation) or `outside_range`
  (extrapolation) per coordinate. This is exact arithmetic on M11 columns.
- **Group/entity novelty:** if a `group_key` is declared, `unseen_groups` = validation groups not
  present in calibration.
- **Regime:** a **declared** label only (e.g. "high-temperature regime"); DRW does not infer regimes.

The `ValidationContext` records these, and the disclosure states: *"Agreement was tested on data
that is [within / partly outside] the range exercised during calibration; agreement here does not
imply agreement outside the tested region."* DRW does **not** claim generalisation beyond the tested
domain.

`[deferred]` Multi-dimensional extrapolation geometry, convex-hull/coverage analysis, and
extrapolation *magnitude* scoring.

---

## 15. Execution and budget model

- **Validation has its own hard budget**, independent of M12B's: `ValidationBudget.max_evaluations`,
  `max_wall_seconds`, `max_failed`. It never consumes or shares M12B's budget.
- **Cost in v1 is small:** one model run per validation dataset (frozen params) **plus** one run per
  dataset to re-evaluate the calibration dataset for the gap (if a gap is requested) — so ≈ `2 ×`
  (number of validation datasets) runs, all bounded by `max_evaluations`.
- **Multiple datasets share one budget.** The loop decrements one counter across datasets; when the
  cap is reached, remaining datasets are recorded `not_run` with a `budget_exhausted` failure and the
  run stops (fail closed, partial results preserved).
- **Per-run timeout** comes from the execution template (`subprocess` isolation default; `[implemented]`
  Runner behaviour).
- **Output reuse/caching.** `[recommended: not in v1]` A model run is deterministic given
  (model_hash, inputs, execution config, environment). Caching a run's `OutputValue`s keyed by that
  tuple would be safe *if* the cache key and the environment hash are recorded in provenance.
  **Recommend deferring caching to M12C+** to keep provenance simple: v1 re-executes. If added later,
  a cache hit must record `reused_run_id` + the original `environment_hash`, and must be invalidated
  by any key change — never silent.
- **Determinism.** Validation itself is deterministic (no randomness). Record `deterministic: true`;
  there is no seed in the validation path (a seed is only meaningful if a stochastic execution is
  later introduced).

---

## 16. Failure semantics (fail closed)

Two levels: **structural** (fails the whole validation before/around execution) and **per-dataset**
(fails one dataset, others still run), so information is preserved without masking problems.

| Condition | Behaviour | Code |
|---|---|---|
| Calibration not found / unreadable | structural fail | `calibration_not_found` |
| Calibration `best == null` (failed calibration) | structural fail, no execution | `calibration_has_no_best` |
| Calibration `result_hash` mismatch vs stored | structural fail | `calibration_hash_mismatch` |
| `model_ref` of calibration ≠ validation model | structural fail | `model_mismatch` |
| Frozen parameter missing/not finite/out of model bounds | structural fail | `invalid_frozen_parameters` |
| `vs_dataset` ≠ calibration dataset | structural fail | `independence_target_mismatch` |
| A dataset's independence check is `violated` | that dataset fails (unless marked descriptive) | `independence_violated` |
| Validation dataset empty / all rows excluded | that dataset fails | `no_usable_observations` |
| Model execution failed / timed out | that dataset fails | `run_failed` / `run_timed_out` |
| Units incompatible / unspecified | that dataset fails | `incompatible_units` / `unspecified_unit` |
| Mapping invalid (variable/output/coord/depended-on) | that dataset fails | `invalid_mapping` |
| Evaluation `ok=false` (M12A fail-closed) | that dataset fails | the M12A diagnostic code |
| Selected metric(s) all `null`/non-finite | that dataset ⇒ `inconclusive` | `metrics_unavailable` |
| Post-run `parameter_snapshot` ≠ frozen vector | structural fail | `validation_parameter_mismatch` |
| Budget exhausted with datasets remaining | remaining ⇒ `not_run` | `budget_exhausted` |
| Acceptance criterion references an unavailable metric | configuration error | `acceptance_metric_unavailable` |

Roll-ups:
- All datasets failed ⇒ `agreement_status="failed"`, `result_hash` still recorded (a failed
  validation is a result, not silence).
- No acceptance criteria ⇒ `acceptance_status="not_specified"` (never `met`).
- A criterion evaluates against a `null` metric ⇒ that criterion `indeterminate` (never `met`).

**No fabricated numbers.** Invalid candidates/datasets store `null` metrics + a code, mirroring M12B.

---

## 17. Provenance / evidence model

The chain, each link by content hash (`[recommended]`):

```
Model                 → model_ref + model_hash
Calibration dataset    → dataset.content_hash + science_hash
Calibration result     → calibration.result_hash + calibration_hash
Frozen parameters      → CalibrationSnapshot.parameters (exact dict)
Validation dataset(s)  → dataset.content_hash + science_hash (+ files[].sha256)
Observation mapping    → mapping_hash
Validation evaluation  → evaluation_hash (per dataset, from M12A)
Validation result      → validation.result_hash
```

`ValidationProvenance` (`[recommended]`):
```
experiment_id, model_id, model_hash,
calibration_result_hash, calibration_hash,
calibration_dataset_content_hash, calibration_dataset_science_hash,
calibration_mapping_hash, calibration_evaluation_hash,
validation_dataset_hashes: [content_hash...], validation_science_hashes: [...],
mapping_hashes: [...], evaluation_config_hash,
per_dataset_evaluation_hashes: [...],
execution_template (solver, timeout_s, isolation, max_runs),
environment_hash, engine_schema_version, scipy_version, deterministic: true
```

**Evidence integration.** `[deferred]` Do not modify `EvidenceManifest` in M12C. A validation is a
content-addressed artifact in a `ValidationStore` (§21), and its reference may be attached to an
investigation. Folding validations into the evidence package is a later, additive change (a new
`validation` artifact kind), exactly as calibration evidence integration was deferred in M12B.

---

## 18. Reproducibility requirements

**`validation_hash` (REQUEST identity)** over a canonical payload of:
`schema_version`, `experiment_id`, `model_ref`, `calibration.result_hash` (and `calibration_hash`),
each dataset's `content_hash`+`science_hash`+canonical `mapping`, `evaluation` (`EvaluationConfig`),
`acceptance` criteria, `aggregate` policy, `budget`, `execution` template, and the `IndependenceSpec`
per dataset. **Excluded:** timestamps, host paths, wall-clock, and *outcomes*.

**`result_hash` (OUTCOME identity)** over the `ValidationResult` minus `result_hash` and minus
wall-clock durations (mirroring M12B's rule, `[implemented]`), so two equivalent runs hash
identically.

Deterministic given the recorded inputs; `environment_fingerprint` + `scipy` version recorded (as in
M11/M12A/M12B, `[implemented]`). Two machines with equivalent package versions agree on the semantic
hash (M11 rule: `python_executable` excluded).

---

## 19. Staleness / invalidation rules

A stored validation is **stale** whenever any identity input it recorded no longer matches the
current artifact. DRW provides `check_validation_staleness(result) -> ("fresh" | "stale", reasons)`.

Stale triggers:
- **Calibration changed** — the referenced `CalibrationResult.result_hash` no longer exists or no
  longer matches (`calibration_result_missing`, `calibration_result_changed`). Re-calibrating (even
  with the same config but changed data) yields a new `result_hash` ⇒ validation stale.
- **Calibration dataset changed** — `dataset.content_hash` differs from the recorded one.
- **Validation dataset changed** — recorded `content_hash` differs.
- **Model changed** — `model_hash` differs.
- **Mapping changed** — `mapping_hash` differs.
- **Evaluation config changed** — `evaluation_config_hash` differs.
- **Environment changed** — recorded environment hash differs (reported, and by policy *stale* for
  strict reproducibility; at minimum it is a disclosure).

Rules:
- A stale result is **never silently authoritative**; the API/UI must surface `stale` and the
  reasons, and must not present its status as current.
- DRW does **not** auto-recompute; recomputation is an explicit user action producing a new result
  (append-only history, mirroring M12B's `CalibrationStore`).
- Staleness is computed **on read**, not stored as a mutable flag (append-only, content-addressed).

---

## 20. ScientificStatus semantics

The frontend already has a `ScientificStatus` component with levels `descriptive`, `limited`,
`not_validated`, `supported` (`[implemented]`). Validation needs **three orthogonal axes** plus a
lifecycle state; they must not collapse into one badge.

**Axis A — Agreement (descriptive):**
`not_run` · `agrees` · `partial` · `does_not_agree` · `inconclusive` · `failed`
("Does the frozen model reproduce the held-out observations, as far as the configured metrics show?")

**Axis B — Acceptance (the user's criterion):**
`not_specified` · `met` · `not_met` · `indeterminate`
("Does it satisfy the acceptance criteria you supplied?" — labelled as a user choice.)

**Axis C — Independence (evidence quality):**
`verified` · `partially_verified` · `declared_only` · `violated` · `unknown`

**Lifecycle / overall (for a badge):**
- `not_validated` — no validation run, **or** the calibration has not been validated (the current
  frontend wording). This is the honest default until M12C runs.
- `supported` — agreement `agrees` **and** independence `verified` (or `partially_verified` with the
  gap disclosed) **and** acceptance `met`/`not_specified`. Reuses the existing "Supported" level.
- `limited` — agreement `agrees`/`partial` but independence `declared_only`, **or** extrapolation
  context, **or** acceptance `not_specified` while the user expected one. Reuses "Limited evidence".
- `not_supported` — acceptance `not_met`, or agreement `does_not_agree`.
- `inconclusive` — agreement `inconclusive`.
- `failed` — agreement `failed`.
- `descriptive` — a validation deliberately run on non-independent data (marked descriptive).

**Rule:** a `met` acceptance criterion **never** by itself yields `supported`; the overall badge
requires verified/declared independence as well. The mandatory `note` states what was and was not
established.

Mapping to the existing component: `descriptive`, `limited`, `not_validated`, `supported` already
exist; M12C adds `not_supported`, `inconclusive`, `failed` (and the three-axis detail is shown
alongside). `[recommended]`

---

## 21. CLI / API implications

**CLI** (`[recommended]`, mirroring `drw calibrate`):
```
drw validate <experiment_id> --config <validation.json> [--persist] [--json] [--workspace] [--dry-run]
```
- Reads a `ValidationConfig` JSON (which references the calibration by id/hash and embeds datasets +
  mappings + independence specs).
- `--dry-run` validates the config, resolves the calibration, loads datasets, checks independence,
  resolves metrics — **executes nothing**.
- Exit: `0` if ≥1 dataset produced usable metrics; `1` if all datasets failed/inconclusive; `2` for
  config/usage errors (existing convention).
- `drw validate --check <validation_id>` reports staleness.

**Bridge ops** (`[recommended]`, mirroring M12B):
`validate`, `get_validation`, `list_validations`, `verify_validation` (store integrity),
`check_validation_staleness`. Follow existing JSON-in/out and error-code conventions; the experiment
id in the route is authoritative.

**Persistence** (`[recommended]`): `ValidationStore` at
`<workspace>/validations/<validation_id>/{config,result,provenance,manifest}.json`, content-addressed
(`validation_id = "val-" + result_hash[:12]`), append-only, idempotent identical save, conflicting
payload rejected, `verify()` re-hashes — exactly the M12B `CalibrationStore` pattern
(`[implemented]`). No `EvidenceManifest` change.

---

## 22. Web / UI implications

The frontend already has an Investigation → **Validation** page that honestly says "not yet
available" and links to Evaluation/Calibration. **That stays until M12C is implemented.** When
implemented, the page becomes:

- **Setup (Manual):** pick a calibration result (from `list_calibrations`); add one or more
  validation datasets (from `list_datasets`); per dataset: mapping (JSON, as in Evaluation/Calibration),
  independence declaration (dimensions + optional windows + optional group key), metrics, optional
  acceptance criteria; budget; Run.
- **Results:** per-dataset table (agreement, metrics, cal-metric gap, exclusions, independence
  roll-up, context) + the three axes + the mandatory disclosure; staleness banner when stale.
- Keep the **one-page-one-job** rule; validation is its own page and does not become a dashboard.
- Reuse `ScientificStatus` for the badge/axes; reuse existing table/`LineChart` patterns.

Do not build a validation *dashboard*, model-selection UI, or CV UI.

---

## 23. Capability / planner implications

- Add an additive `capabilities.validation` block: `{ default_metrics, supports_independence_checks,
  verifiable_dimensions, declared_dimensions, max_evaluations_default }` (mirrors the existing
  additive `global_sensitivity`/`identifiability`/`calibration` blocks, `[implemented]`).
- The rule-based/LLM planner (`[implemented]`) may **propose** a validation plan (choose calibration,
  datasets, metrics, criteria) but must never execute it. SI proposes; the user approves; Manual runs.
- No new planner capability that implies autonomy.

---

## 24. Test strategy

**Unit (contract):** config validation + fail-closed rules; identity/hash stability & sensitivity;
staleness detection; independence checks (each dimension: verified/violated/declared/unverifiable);
acceptance-criterion evaluation (met/not_met/not_specified/indeterminate); frozen-parameter
assertion.

**Scientific benchmarks (domain-neutral):**
1. **Perfect generalisation** — same generating model; calibration on set A; validation on an
   independent set B drawn from the same law ⇒ validation metrics ≈ 0.
2. **Overfit / regime change** — calibration good on A; validation on a different regime ⇒ large gap
   reported (must not be labelled `supported`).
3. **Leakage: identical dataset** ⇒ `independence_violated`, hard fail.
4. **Leakage: same science, different provenance** ⇒ `science_hash` equal ⇒ violated.
5. **Temporal holdout** — disjoint windows ⇒ verified; overlapping ⇒ violated.
6. **Grouped holdout** — disjoint entity keys ⇒ verified; shared key ⇒ violated.
7. **Extrapolation context** — validation window outside calibration range ⇒ `outside_range` recorded.
8. **Incompatible units** ⇒ dataset fails closed.
9. **Empty / all-excluded dataset** ⇒ fails closed.
10. **Failed calibration** (`best=null`) ⇒ structural fail before execution.
11. **Budget exhaustion** with multiple datasets ⇒ partial results + `budget_exhausted`.
12. **No-refit proof** — `parameter_snapshot` equals the frozen vector; no optimizer in the path.
13. **Determinism** — repeated validation ⇒ identical `result_hash`.
14. **Staleness** — mutate a referenced input ⇒ `stale` with reasons.
15. **Behavioural isolation** — the validation path performs no calibration-store writes and no
    parameter mutation (assert via call counts / absence of optimizer).

**Integration:** CLI + bridge + `ValidationStore` round-trip; capabilities block; staleness
endpoint. **Web:** component test for the (future) Validation panel + one Playwright scenario once
implemented.

Every test must use a domain-neutral model (linear/quadratic/double-well), never an
astrophysics-specific model.

---

## 25. Security / integrity considerations

- **No new execution path.** Validation uses `Runner` (subprocess isolation + timeout by default,
  `[implemented]`); it never calls model code directly.
- **Path containment** for datasets (via `DatasetStore`) and for the store root; no arbitrary
  filesystem access from the bridge.
- **Content integrity**: validation verifies dataset hashes on load (`DatasetStore`), records all
  hashes, and its own `ValidationStore.verify()` re-hashes files.
- **No network**, no arbitrary code, no shell.
- **Budget as a safety control**: the hard `max_evaluations` prevents runaway execution.
- **Honesty as a safety property**: fail-closed + mandatory disclosure ensure an invalid or
  non-independent comparison is never presented as a scientific conclusion.

---

## 26. Risks and unresolved questions

- **Independence verification limits.** DRW cannot prove process/selection independence; only
  artifact/window/group disjointness. Risk: a user over-trusts `verified`. Mitigation: `verified`
  covers only the checked dimensions; everything else is `declared` and disclosed.
- **Acceptance-criteria misuse.** Thresholds invite "pass = true" thinking. Mitigation: separate
  axis, mandatory labelling as the user's criterion, and a rule that `met` alone ≠ `supported`.
- **Metric comparability across datasets.** Different datasets ⇒ different scales; the gap and any
  aggregate are only meaningful under compatible units/configs. Mitigation: fail closed on
  incompatible aggregation; never implicit scalar.
- **`calibration_metrics` re-derivation cost.** One extra run per validation; acceptable and bounded.
- **Staleness UX.** Users may miss a stale banner. Mitigation: staleness computed on read and
  surfaced in CLI/API/UI; stale results are never silently current.
- **Open:** should `weighted_rmse`-based validation be allowed when the validation dataset has
  *different* σ semantics than calibration? (Recommendation: allowed only if the same
  `EvaluationConfig` applies and σ is present; otherwise unweighted + disclosure.)
- **Open:** exact treatment of `interpolate` alignment in validation (M12A opt-in) — recommend
  allowed but disclosed, as in M12A.
- **Open:** whether a validation may reference a *draft* (unpersisted) calibration — recommend
  **no**; a persisted `CalibrationResult` is required so provenance is stable.

---

## 27. Explicit non-goals

- Cross-validation, k-fold, grouped/blocked/temporal CV, leave-one-group-out. `[deferred]`
- Model selection / hyperparameter search / AutoML. `[deferred]`
- Bayesian validation, posterior predictive checks, likelihood ratios, Bayes factors. `[deferred]`
- Parameter/predictive uncertainty propagation into validation. `[deferred]`
- Domain-specific metrics or regimes. `[deferred]`
- Multi-domain aggregation with unit reconciliation. `[deferred]`
- Automatic extrapolation magnitude/geometry scoring. `[deferred]`
- Any auto-execution without explicit user approval.
- Modifying M11/M12A/M12B contracts, the Runner, or `EvidenceManifest`.

---

## 28. Recommended M12C scope (v1)

**In scope:**
- Explicit **holdout validation** of a **frozen** `CalibrationResult` against **≥1 independent
  validation datasets**, orchestrated through `Runner`, evaluated by M12A.
- **Structured independence model** with mechanical checks (dataset/science hash, coordinate/window
  disjointness, group-key disjointness) + declared dimensions, and a per-dataset `IndependenceReport`.
- **Per-dataset** results (agreement, metrics, exclusions, gap, context) — information-preserving.
- **Optional explicit acceptance criteria**, kept as a separate axis from agreement.
- **Optional explicit cross-dataset aggregate** only when units/configs are compatible.
- **Minimal extrapolation/interpolation classification** (range + unseen groups), mostly declared.
- **Content-addressed `ValidationStore`** + integrity `verify` + `check_staleness`.
- **CLI + bridge + capabilities + (later) web panel.**
- Deterministic, content-addressed `validation_hash` / `result_hash`; full provenance.

**Out of scope (deferred):** §27, and specifically cross-validation and extrapolation magnitude.

---

## 29. Deferred M12C+ features

Cross-validation (as an explicit `SplitSpec`), leave-one-group-out, extrapolation geometry/coverage,
R²/MAPE/log metrics, predictive/parameter uncertainty propagation, evidence-package integration of
validations, run-output caching with provenance, multi-objective acceptance, automated
model-selection warnings, and domain metric plugins.

---

## 30. Proposed acceptance criteria (for the eventual implementation)

1. A `ValidationConfig` validates and hashes deterministically; changing any scientific setting
   changes `validation_hash`; timestamps/outcomes do not.
2. Validation **cannot** refit: no optimizer in the path; the produced `parameter_snapshot` equals the
   frozen vector, asserted; a mismatch fails closed.
3. Independence is a structured report; `violated` checks fail the dataset; `declared` is never
   presented as `verified`.
4. Same-dataset / same-`science_hash` / overlapping-window / shared-group cases are detected and
   failed (or marked descriptive).
5. Per-dataset results always present; the cross-dataset aggregate exists only when explicitly
   requested and unit/config-compatible, else fails closed.
6. Metrics are exactly M12A metrics; no new comparison math; `null` metrics + codes, never fabricated.
7. Acceptance is a separate axis; `not_specified` by default; `met` alone never yields `supported`.
8. Fail-closed behaviour for every §16 case; a failed validation still yields a recorded result.
9. `result_hash` is deterministic; repeated equivalent validations hash identically.
10. `ValidationStore` is append-only, content-addressed, idempotent, verifiable; a stale result is
    reported stale with reasons and never silently authoritative.
11. CLI (`drw validate`, `--dry-run`, `--json`, `--persist`), bridge ops, and an additive
    `capabilities.validation` block exist; `EvidenceManifest`, M11, M12A, M12B and the Runner are
    unmodified.
12. The web Validation page stops saying "not yet available" **only** when the above are true; until
    then it stays honest.

---

## 31. Suggested implementation sequence

- **M12C-A — Validation contract.** `drw/schema/validation.py`: `ValidationConfig`,
  `ValidationDataset`, `IndependenceSpec`, `AcceptanceCriterion`, `ValidationResult`,
  `ValidationProvenance`, `ValidationRef`, literals, `compute_validation_hash`,
  `compute_result_hash`, model-aware validation of the config. Unit tests.
- **M12C-B — Independence + leakage checks.** Pure functions over datasets/calibration refs producing
  `IndependenceReport`; unit/scientific tests for each dimension and leakage case.
- **M12C-C — Frozen-parameter validation execution.** `drw/validation/loop.py`: resolve calibration →
  freeze → build single-run specs → `Runner` → M12A `evaluate_run` → per-dataset results → rollout to
  `ValidationResult`; the `parameter_snapshot` assertion; budget enforcement; failure semantics.
  Benchmarks 1–15.
- **M12C-D — Persistence + staleness.** `drw/validation_store.py` (mirror `CalibrationStore`);
  `check_staleness`; tests (round-trip, integrity, mutation ⇒ stale).
- **M12C-E — Interfaces.** CLI `drw validate`, bridge ops, `capabilities.validation`, then the web
  Validation panel; component + Playwright tests; flip the UI wording only then.

Each phase: Ruff + focused tests; final phase: full Python suite, typecheck, web tests, build,
Playwright.

---

## M12C IMPLEMENTATION PROMPT

> Copy-paste the block below to a coding agent once this design is approved. It is self-contained.

---

**M12C — IMPLEMENT: Validation / Generalisation**

Implement M12C exactly per `docs/reports/milestone-12c-validation-design.md`. **Do not** implement
cross-validation, model selection, Bayesian validation, uncertainty propagation, domain metrics, or
evidence-manifest changes (all deferred).

**Hard boundaries — do NOT modify:** `ExperimentSpec`, `ModelSchema`, `Runner`, `RunRecord` /
`ModelResult` / `OutputValue`, `EvidenceManifest`, M11 `Dataset` / `ObservationSet` /
`ObservationMapping` / `DatasetStore` / `science_hash`, M12A `evaluate` / `evaluate_run` /
`EvaluationConfig` / `EvaluationResult` / `evaluation_hash`, M12B calibration semantics / contracts /
`CalibrationStore`. Additive integration only (new modules, `capabilities`, CLI, bridge, web, docs).
Zero new dependencies.

**Architecture (composition, no new science):**
`CalibrationResult (frozen best.parameters) + ValidationConfig + Runner execution + M12A evaluate_run
= ValidationResult`. Validation never executes a model directly (use `Runner`), never re-implements
comparison (use M12A `evaluate_run`), and has **no optimizer** in its path.

**Files to add:**
- `packages/core/src/drw/schema/validation.py` — `ValidationConfig`, `ValidationDataset`,
  `IndependenceSpec`, `IndependenceCheck`/`IndependenceReport`, `AcceptanceCriterion`/
  `AcceptanceOutcome`, `ValidationContext`, `ValidationDatasetResult`, `ValidationResult`,
  `ValidationProvenance`, `ValidationRef`, `ValidationBudget`, literals
  (`AgreementStatus`, `AcceptanceStatus`, `IndependenceStatus`), `compute_validation_hash`,
  `compute_result_hash`, `resolve_validation`/`validate_validation_config`.
- `packages/core/src/drw/validation/__init__.py`, `independence.py`, `loop.py`.
- `packages/core/src/drw/validation_store.py` — mirror `CalibrationStore`
  (`cal-…` → `val-…`, `<workspace>/validations/<id>/{config,result,provenance,manifest}.json`,
  append-only, content-addressed, idempotent identical save, conflicting-payload rejection,
  `verify()`, `load/list/exists/ref`).
- Tests: `tests/unit/test_validation.py`, `tests/unit/test_validation_independence.py`,
  `tests/unit/test_validation_store.py`, `tests/scientific/test_validation_benchmarks.py`,
  `tests/integration/test_validation_workflow.py`.

**Additive integration:** `capabilities.model_capabilities` gains a `validation` block; `cli.py`
gains `drw validate <experiment_id> --config <json> [--dry-run] [--persist] [--json] [--workspace]`;
`api.py` gains ops `validate`, `get_validation`, `list_validations`, `verify_validation`,
`check_validation_staleness`; web: `lib/{types,client,handlers,directClient,stubClient}`,
`app/api/experiments/[id]/validate/route.ts`, a `ValidationPanel`, and the Investigation → Validation
page (keep its current "not yet available" copy until the panel works end-to-end, then update it).

**Required behaviour (fail closed):**
- Freeze: baseline = `calibration.best.parameters` ∪ calibration fixed params; single-run spec
  (`factors=∅`, `analyses=∅`, `max_runs=1`); after the run, assert
  `evaluation.parameter_snapshot == frozen vector`, else `validation_parameter_mismatch`.
- Independence checks: dataset/content-hash, `science_hash`, `files[].sha256`, coordinate/time-window
  disjointness, group-key disjointness ⇒ `verified`/`violated`/`declared`/`unverifiable`. `violated`
  fails that dataset unless explicitly marked descriptive; `declared` is never presented as verified.
- Metrics: reuse M12A metrics only; request the chosen metrics in `EvaluationConfig`; report `null` +
  a code for unusable metrics; no fabricated numbers.
- Per-dataset results always present; aggregate only when `aggregate="explicit"` and units/configs
  are compatible (else config error). Acceptance is a separate axis; `not_specified` by default.
- Budget: `max_evaluations` hard cap shared across datasets; remaining datasets ⇒ `not_run` +
  `budget_exhausted`.
- Determinism: no randomness; `validation_hash` (request) and `result_hash` (outcome, excluding
  wall-clock) both deterministic; record `environment_hash` + `scipy` version.
- Staleness: `check_staleness(result)` compares recorded hashes to current artifacts and returns
  reasons; never silently authoritative.

**Test requirements:** the 15 domain-neutral benchmarks in §24 of the design (perfect generalisation,
overfit/regime change, leakage cases, temporal/grouped holdout, extrapolation context, incompatible
units, empty dataset, failed calibration, budget exhaustion, no-refit proof, determinism, staleness,
no-mutation isolation), plus unit + integration + store tests, plus web component/Playwright when the
panel lands. Use only domain-neutral models.

**Validation commands to run and report:** `ruff check packages/core/src tests scripts`;
`python -m pytest -q`; `pnpm --filter @drw/web typecheck`; `pnpm --filter @drw/web test`;
`pnpm --filter @drw/web build`; `pnpm --filter @drw/web e2e:only`.

**Report:** files changed; architecture; independence/leakage behaviour; failure semantics;
reproducibility guarantees; persistence/staleness; CLI/bridge/web behaviour; exact test counts;
known limitations; explicit confirmation that CV/Bayesian/uncertainty/evidence-integration were NOT
implemented and that M11/M12A/M12B/Runner/EvidenceManifest were NOT modified; zero new dependencies.
**Stop after M12C.**

---

## 32. Recommendation

### SHIP M12C AS SPECIFIED

Ship the specified scope — **explicit holdout validation of a frozen calibration, orchestrated via
the existing `Runner`, evaluated by M12A, with structured independence checks, per-dataset results,
optional explicit acceptance criteria kept separate from agreement, content-addressed persistence, and
staleness detection** — because:

1. **It is the smallest scientifically defensible unit of "generalisation."** A frozen model tested
   on demonstrably distinct data is exactly the claim "does it generalise to independent
   observations?" and nothing more. It needs no hidden machinery.
2. **It composes cleanly with the existing architecture.** It reuses M12A for all measurement, the
   `Runner` for all execution, M11 for all data, and M12B's content-addressed store pattern for
   persistence. The only new contracts are the request/outcome/orchestration.
3. **It cannot refit, by construction.** The absence of an optimizer plus the `parameter_snapshot`
   assertion makes "no refit" mechanically verifiable, not just asserted.
4. **It is honest by design.** Three orthogonal axes (agreement / acceptance / independence) plus
   fail-closed semantics and a mandatory disclosure prevent the two classic failures: calling a
   redescription of calibration data "validation", and calling an arbitrary threshold "truth".
5. **It fits a solo developer.** One run per validation dataset (plus one gap run), one hard budget,
   no distributed/parallel/CV machinery.

The three items the brief might expect but which this proposal **deliberately defers** —
**cross-validation (§13)**, **cross-dataset scalar aggregation (§8/§10)** beyond an explicit opt-in,
and **extrapolation/regime classification beyond a declared range check (§14)** — are the parts with
the worst scientific-risk-to-cost ratio at this stage. Deferring them keeps M12C reproducible,
transparent and auditable, and gives M12C+ a proven foundation (an explicit `SplitSpec`) on which to
add CV safely.

If forced to cut further (a REVISE fallback): ship only items §28 with **no acceptance criteria and no
aggregate** (agreement + independence + metrics + persistence + staleness). Do **not** ship nothing:
validation-with-disclosure is the capability the product's epistemic discipline most needs next, and
it is achievable within the existing contracts.
