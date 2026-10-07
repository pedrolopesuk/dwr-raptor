/**
 * Wire types for the DRW researcher UI.
 *
 * The authoritative contract lives in Python (Pydantic) and is mirrored in
 * `@drw/experiment-spec`. Everything here is either a re-export of that contract
 * or the JSON envelope produced by the bridge (`python -m drw.api`). No
 * scientific computation is defined in TypeScript.
 */

export type { ExperimentSpec, FactorSpec } from "@drw/experiment-spec";

import type { ExperimentSpec } from "@drw/experiment-spec";

export interface BridgeRequest {
  op: string;
  params: Record<string, unknown>;
}

export interface BridgeErrorShape {
  code: string;
  message: string;
  diagnostics: unknown[];
}

export type BridgeResponse<T> = { ok: true; data: T } | { ok: false; error: BridgeErrorShape };

export interface ModelParameter {
  name: string;
  type: "float" | "int" | "bool" | "categorical";
  role: "input" | "state" | "control";
  unit: string;
  description: string;
  nominal: number | boolean | string | null;
  lower: number | null;
  upper: number | null;
  options: string[];
  differentiable: boolean;
}

export interface ModelOutput {
  name: string;
  kind: "scalar" | "vector" | "timeseries" | "matrix" | "categorical";
  unit: string;
  description: string;
  axis_unit: string | null;
}

export interface ModelSchema {
  model_id: string;
  version: string;
  description: string;
  runtime: string;
  parameters: ModelParameter[];
  outputs: ModelOutput[];
  metadata: Record<string, unknown>;
}

export interface ModelSummary {
  model_id: string;
  version: string;
  description: string;
  n_parameters: number;
  n_outputs: number;
}

export interface Diagnostic {
  level: "info" | "warning" | "error";
  code: string;
  message: string;
}

export interface RunEstimate {
  method: string;
  baseline_runs: number;
  variant_runs: number;
  total_runs: number;
  warnings: Diagnostic[];
}

export interface ValidationResult {
  ok: boolean;
  diagnostics: Diagnostic[];
  estimate: RunEstimate;
}

export interface OutputValue {
  name: string;
  kind: string;
  unit: string;
  values: number | number[];
  axis: number[] | null;
  axis_unit: string | null;
}

export interface ModelResult {
  status: string;
  outputs: Record<string, OutputValue>;
  diagnostics: Diagnostic[];
}

export interface RunRecord {
  run_id: string;
  label: string;
  status: string;
  isolation: string;
  timed_out: boolean;
  attempt: number;
  parent_run_id: string | null;
  inputs: Record<string, number | boolean | string>;
  metrics: Record<string, number>;
  diagnostics: Diagnostic[];
  error: string | null;
  duration_s: number | null;
  result: ModelResult | null;
}

export interface Comparison {
  reference_run_id: string;
  variant_run_id: string;
  label: string;
  output: string;
  unit: string;
  method: string;
  alignment: string;
  interpolated: boolean;
  axis: number[];
  reference: number[];
  variant: number[];
  delta: number[];
  relative_delta: number[] | null;
  metrics: Record<string, number>;
  warnings: Diagnostic[];
}

export interface EvidenceFile {
  path: string;
  kind: string;
  sha256: string;
  size_bytes: number;
}

export interface EvidenceData {
  manifest: Record<string, unknown>;
  report: string;
  files: EvidenceFile[];
}

export interface ExperimentData {
  experiment_id: string;
  name: string;
  hypothesis: string;
  model_ref: { model_id: string; version?: string | null };
  isolation: string;
  spec_hash: string;
  model_hash: string;
  environment: Record<string, unknown>;
  estimate: RunEstimate;
  warnings: Diagnostic[];
  runs: RunRecord[];
  comparisons: Comparison[];
  started_at: string | null;
  finished_at: string | null;
  project_id?: string | null;
  job_id?: string | null;
  evidence?: EvidenceData;
  uncertainty?: UncertaintySummary | null;
}

export interface ExperimentSummary {
  experiment_id: string;
  project_id?: string;
  name: string;
  hypothesis: string;
  model_id: string;
  isolation: string;
  spec_hash: string;
  n_runs: number;
  n_succeeded: number;
  n_failed: number;
  created_at: string | null;
  warnings: Diagnostic[];
}

export interface PerspectiveSpecResponse {
  spec: ExperimentSpec;
}

export interface SensitivityRow {
  parameter: string;
  unit: string;
  baseline_value: number;
  perturbed_value: number;
  clamped: boolean;
  reference_peak: number | null;
  variant_peak: number | null;
  abs_delta: number;
  max_abs_relative_delta: number | null;
  elasticity: number | null;
}

export interface SensitivityData {
  metric: string;
  perturbation: string;
  ranking: SensitivityRow[];
}

export interface EnvironmentData {
  environment: Record<string, string>;
  environment_hash: string;
}

export interface GlobalSensitivityCapabilities {
  /** Backend default base sample size N (`drw.global_sensitivity.DEFAULT_SAMPLE_COUNT`). */
  default_sample_count: number;
  /** Hard cap on model evaluations for one study (`MAX_EVALUATIONS`). */
  max_evaluations: number;
}

export interface IdentifiabilityCapabilities {
  /** Method identifier (`drw.identifiability.IDENTIFIABILITY_METHOD`). */
  method: string;
  /** Relative finite-difference step scale (`DEFAULT_STEP_SCALE`). */
  default_step_scale: number;
  /** Condition number above which a study is "ill-conditioned". */
  condition_threshold: number;
  /** Hard cap on model evaluations for one identifiability study. */
  max_evaluations: number;
  /** Fixed, disclosed time-series feature set (`TIMESERIES_FEATURES`). */
  timeseries_features: string[];
}

export interface ModelCapabilities {
  model_id: string;
  version: string;
  parameter_names: string[];
  factorable_parameters: {
    name: string;
    unit: string;
    lower: number | null;
    upper: number | null;
  }[];
  fixed_parameters: string[];
  state_parameters: string[];
  categorical_parameters: string[];
  timeseries_outputs: string[];
  scalar_outputs: string[];
  sampling_methods: string[];
  analysis_methods: string[];
  sensitivity: string | null;
  isolation: string;
  /** Authoritative global-sensitivity study limits (single-sourced in the core). */
  global_sensitivity: GlobalSensitivityCapabilities;
  /** Authoritative local-identifiability study configuration (single-sourced in the core). */
  identifiability?: IdentifiabilityCapabilities;
  /** Authoritative validation configuration (single-sourced in the core). */
  validation?: ValidationCapabilities;
  limitations: string[];
}

export interface Project {
  project_id: string;
  name: string;
  description: string;
  model_id: string | null;
  created_at: string;
}

export interface JobEvent {
  seq: number;
  event: string;
  at: string;
  [key: string]: unknown;
}

export interface JobStatus {
  job_id: string;
  phase: "pending" | "running" | "finished" | "unknown";
  terminal: boolean;
  completed_runs: number;
  total_runs: number | null;
  status: string | null;
  events: JobEvent[];
}

export interface PlanProposal {
  spec: ExperimentSpec | null;
  assumptions: string[];
  questions: string[];
  diagnostics: Diagnostic[];
  validation_ok: boolean;
  provider: string;
  used_ai: boolean;
  rationale: string;
}

export interface PlannerStatus {
  llm_configured: boolean;
  provider: string;
  note: string;
}

/** Reproduction check (ADR-0013): explicit tolerances, read-only comparison. */
export interface ReproduceTolerances {
  rtol: number;
  atol: number;
}

export type ReproduceVerdict =
  | "identical"
  | "equivalent_within_tolerance"
  | "different"
  | "inconclusive"
  | "execution_failed";

export type ReproduceOutputStatus = "identical" | "equivalent" | "different" | "incomparable";

export interface ReproduceOutputComparison {
  output: string;
  unit: string;
  comparable: boolean;
  status: ReproduceOutputStatus;
  identical: boolean;
  passes_tolerance: boolean | null;
  alignment: string | null;
  interpolated: boolean | null;
  shape_compatible: boolean;
  max_abs_delta: number | null;
  max_abs_relative_delta: number | null;
  mae: number | null;
  rmse: number | null;
  n_points: number | null;
  valid_points: number | null;
  non_finite_points: number | null;
  warnings: Diagnostic[];
  note: string | null;
}

export interface ReproduceRunComparison {
  index: number;
  label: string;
  reference_run_id: string;
  fresh_run_id: string | null;
  reference_status: string;
  fresh_status: string | null;
  comparable: boolean;
  identical: boolean;
  passes_tolerance: boolean | null;
  outputs: ReproduceOutputComparison[];
  warnings: string[];
}

export interface ReproduceProvenance {
  spec_hash_stored: string;
  spec_hash_current: string;
  spec_hash_match: boolean;
  model_hash_stored: string;
  model_hash_current: string;
  model_hash_match: boolean;
  environment_hash_stored: string;
  environment_hash_current: string;
  environment_hash_match: boolean;
  differences: string[];
}

export interface ReproduceReport {
  experiment_id: string;
  verdict: ReproduceVerdict;
  numerical: ReproduceVerdict;
  tolerances: ReproduceTolerances;
  provenance: ReproduceProvenance;
  reference_run_ids: string[];
  fresh_run_ids: string[];
  runs: ReproduceRunComparison[];
  warnings: string[];
  /** False: the fresh execution exists only in memory and is never stored. */
  fresh_runs_persisted: boolean;
}

/** Descriptive uncertainty summary over an experiment's sampled variants. */
export interface UncertaintyOutput {
  output: string;
  unit: string;
  requested_variants: number;
  valid_samples: number;
  excluded_samples: number;
  exclusions: Record<string, number>;
  sufficient: boolean;
  mean: number | null;
  std: number | null;
  minimum: number | null;
  maximum: number | null;
  p05: number | null;
  p50: number | null;
  p95: number | null;
  note: string | null;
}

export interface UncertaintySummary {
  schema_version: string;
  sampling_method: string;
  seed: number;
  /** Per-run count: the number of sampled variant runs. */
  requested_variants: number;
  /** Total valid samples summed across the declared scalar outputs. */
  valid_output_samples: number;
  /** Total excluded samples summed across the declared scalar outputs. */
  excluded_output_samples: number;
  quantiles: number[];
  quantile_method: string;
  outputs: UncertaintyOutput[];
  note: string | null;
  descriptive_only: boolean;
}

/** Global variance-based (Sobol) sensitivity study. */
export interface SobolFactor {
  name: string;
  s1: number | null;
  st: number | null;
  s1_ci: [number, number] | null;
  st_ci: [number, number] | null;
}

export interface SobolReport {
  model_id: string;
  output: string;
  estimator: string;
  sample_count: number;
  seed: number;
  dimensions: number;
  factors: string[];
  evaluations_requested: number;
  evaluations_completed: number;
  variance: number | null;
  inconclusive: boolean;
  reasons: string[];
  results: SobolFactor[];
  bootstrap_resamples: number;
  independent_inputs_assumed: boolean;
  note: string | null;
}

/** Local parameter identifiability study (finite-difference sensitivity SVD). */
export type IdentifiabilityVerdict =
  | "well-conditioned"
  | "ill-conditioned"
  | "rank-deficient"
  | "inconclusive";

export interface IdentifiabilityTarget {
  output: string;
  feature: string;
  unit: string;
  baseline_value: number | null;
  scale: number | null;
  informative: boolean;
  note: string | null;
}

export interface IdentifiabilityFactor {
  name: string;
  unit: string;
  baseline_value: number | null;
  step: number | null;
  lower: number | null;
  upper: number | null;
  plus_value: number | null;
  minus_value: number | null;
  valid: boolean;
  note: string | null;
}

export interface IdentifiabilityDirection {
  index: number;
  singular_value: number;
  condition_index: number | null;
  problematic: boolean;
  dominant: string[];
  weights: Record<string, number>;
}

export interface IdentifiabilityPairCorrelation {
  first: string;
  second: string;
  correlation: number;
}

export interface IdentifiabilityReport {
  model_id: string;
  experiment_id: string | null;
  method: string;
  factors: string[];
  factors_detail: IdentifiabilityFactor[];
  targets: IdentifiabilityTarget[];
  dimensions: number;
  n_targets: number;
  step_scale: number;
  absolute_step: number;
  rank_tolerance: number;
  condition_threshold: number;
  correlation_threshold: number;
  evaluations_requested: number;
  evaluations_completed: number;
  singular_values: number[];
  numerical_rank: number | null;
  condition_number: number | null;
  directions: IdentifiabilityDirection[];
  factor_correlations: IdentifiabilityPairCorrelation[];
  verdict: IdentifiabilityVerdict;
  inconclusive: boolean;
  reasons: string[];
  normalized: boolean;
  local_only: boolean;
  note: string | null;
}

/** Scientific datasets: observation contract + CSV import (M11). */
export interface DatasetRef {
  dataset_id: string;
  content_hash: string;
  name: string;
  created_at: string | null;
}

export interface DatasetSummary extends DatasetRef {
  source_kind: string | null;
}

export interface DatasetSource {
  filename: string;
  size_bytes: number;
}

export interface ColumnInspection {
  column: string;
  index: number;
  kind: string;
  missing_count: number;
  non_finite_count: number;
  sample_values: string[];
  suggested_role: string | null;
  suggested_name: string | null;
  suggested_uncertainty_for: string | null;
  note: string | null;
}

export interface CsvInspection {
  adapter_id: string;
  adapter_version: string;
  filename: string;
  delimiter: string;
  has_header: boolean;
  row_count: number;
  columns: ColumnInspection[];
  preview: Record<string, string>[];
  diagnostics: Diagnostic[];
  advisory: string;
}

export interface UncertaintyConfig {
  type: "none" | "std" | "stderr" | "asymmetric" | "interval" | "precision";
  value?: number | null;
  column?: string | null;
  lower?: number | null;
  upper?: number | null;
  lower_column?: string | null;
  upper_column?: string | null;
  level?: number | null;
}

export interface QualityConfig {
  flag_column: string;
  missing_flags?: string[];
  invalid_flags?: string[];
  censored_flags?: string[];
  rejected_flags?: string[];
  flagged_flags?: string[];
}

export interface ColumnConfig {
  column: string;
  role: string;
  name?: string | null;
  kind?: string | null;
  unit?: string | null;
  depends_on?: string[];
  uncertainty?: UncertaintyConfig | null;
  quality?: QualityConfig | null;
  missing_codes?: string[];
  description?: string;
  datetime_format?: string | null;
}

export interface CsvImportConfig {
  name: string;
  columns: ColumnConfig[];
  description?: string;
  labels?: Record<string, string>;
  dataset_version?: string;
  delimiter?: string | null;
  has_header?: boolean | null;
  missing_codes?: string[];
  non_finite_policy?: "error" | "missing";
  invalid_policy?: "error" | "missing";
  imported_at?: string | null;
  license?: string | null;
  notes?: string;
}

export interface DatasetVariable {
  name: string;
  kind: string;
  role: string;
  unit: string | null;
  depends_on: string[];
  uncertainty: UncertaintyConfig | null;
  quality: QualityConfig | null;
  description: string;
}

export interface DatasetProvenance {
  source_kind: string;
  imported_at: string;
  dataset_version: string;
  adapter: { id: string; version: string } | null;
  original_filename: string | null;
  source_sha256: string | null;
  notes: string;
  license: string | null;
}

export interface DatasetData {
  schema_version: string;
  name: string;
  description: string;
  labels: Record<string, string>;
  provenance: DatasetProvenance;
  observation_set: {
    coordinates: string[];
    variables: DatasetVariable[];
    columns: Record<string, (number | string | boolean | null)[]>;
  };
  files: { name: string; sha256: string; size_bytes: number }[];
  content_hash: string;
  dataset_id: string;
}

export interface DatasetCheck {
  name: string;
  status: string;
  message: string;
}

export interface DatasetVerification {
  dataset_id: string;
  content_hash: string | null;
  ok: boolean;
  errors: number;
  checks: DatasetCheck[];
  extra_files: string[];
  note: string;
}

export interface DatasetImportResult {
  ref: DatasetRef;
  dry_run: boolean;
  stored: boolean;
  verification?: DatasetVerification;
}

export interface DatasetDetail {
  ref: DatasetRef;
  dataset: DatasetData;
  verification: DatasetVerification;
}

/** Observation <-> model evaluation (M12A). */
export interface EvaluationConfig {
  metrics?: string[];
  residual_modes?: string[];
  alignment?: "exact" | "interpolate";
  alignment_tolerance?: number;
  relative_epsilon?: number;
  time_origin?: string | null;
  degrees_of_freedom?: number | null;
}

export interface AlignedPoint {
  observation_index: number;
  model_index: number | null;
  coordinate: number | null;
  observed: number;
  predicted: number;
  residual: number;
  relative_residual: number | null;
  sigma: number | null;
  normalized_residual: number | null;
}

export interface EvaluationExclusion {
  observation_index: number;
  reason: string;
  detail: string;
}

export interface PairEvaluation {
  observation: string;
  output: string;
  kind: string;
  unit: string;
  alignment: string;
  tolerance: number;
  interpolated: boolean;
  points: AlignedPoint[];
  exclusions: EvaluationExclusion[];
  usable_count: number;
  excluded_count: number;
  exclusion_counts: Record<string, number>;
  metrics: Record<string, number | null>;
  diagnostics: Diagnostic[];
}

export interface EvaluationProvenance {
  spec_hash: string;
  model_hash: string;
  environment_hash: string;
  dataset_content_hash: string;
  mapping_hash: string;
}

export interface EvaluationResult {
  eval_schema_version: string;
  evaluation_hash: string;
  dataset: DatasetRef;
  experiment_id: string;
  run_id: string;
  attempt: number;
  model_ref: { model_id: string; version?: string | null };
  model_hash: string;
  parameter_snapshot: Record<string, unknown>;
  mapping: Record<string, unknown>;
  mapping_hash: string;
  config: EvaluationConfig;
  pairs: PairEvaluation[];
  total_usable: number;
  total_excluded: number;
  ok: boolean;
  diagnostics: Diagnostic[];
  provenance: EvaluationProvenance;
}

/** Calibration (M12B). */
export interface CalibrationParameterSelection {
  name: string;
  lower: number;
  upper: number;
  initial: number | null;
  scale?: string;
  transform?: string;
}

export interface CalibrationObjectiveConfig {
  metric: string;
  observation?: string | null;
  output?: string | null;
  aggregation?: string;
  direction?: string;
}

export interface CalibrationOptimizerConfig {
  name: "powell" | "differential_evolution" | "random_search";
  max_iterations?: number | null;
  population_size?: number | null;
  mutation?: number | null;
  recombination?: number | null;
}

export interface CalibrationBudget {
  max_evaluations: number;
  max_wall_seconds: number;
  max_failed?: number | null;
}

export interface CalibrationExecutionTemplate {
  solver?: string;
  timeout_s?: number;
  isolation?: string;
  max_runs?: number;
}

export interface CalibrationConfig {
  schema_version?: string;
  experiment_id: string;
  model_ref: { model_id: string; version?: string | null };
  free: CalibrationParameterSelection[];
  fixed?: { name: string; value: number | string | boolean }[];
  objective: CalibrationObjectiveConfig;
  optimizer?: CalibrationOptimizerConfig;
  budget?: CalibrationBudget;
  seed?: number;
  execution?: CalibrationExecutionTemplate;
  dataset: DatasetRef;
  mapping: Record<string, unknown>;
  evaluation?: EvaluationConfig;
  identifiability?: string;
  data_role?: string;
  notes?: string;
}

export interface CalibrationCandidate {
  index: number;
  parameters: Record<string, number>;
  run_id?: string | null;
  run_status?: string | null;
  evaluation_hash?: string | null;
  objective?: number | null;
  failure?: string | null;
  n_used?: number;
  n_excluded?: number;
  duration_s?: number | null;
  diagnostics?: Diagnostic[];
}

export interface CalibrationResult {
  schema_version: string;
  calibration_hash: string;
  result_hash: string;
  experiment_id: string;
  status: string;
  stop_reason: string;
  converged: boolean;
  best: CalibrationCandidate | null;
  objective: {
    metric: string;
    observation: string;
    output: string;
    value: number | null;
    invalid_objective_sentinel: string;
  };
  evaluations_requested: number;
  evaluations_completed: number;
  evaluations_invalid: number;
  iterations: number;
  wall_seconds: number;
  identifiability: Record<string, unknown> | null;
  history: CalibrationCandidate[];
  diagnostics: Diagnostic[];
  provenance: Record<string, unknown>;
  /** The full stored request (present when fetched via get_calibration). */
  config?: {
    dataset: DatasetRef;
    mapping: Record<string, unknown>;
    [key: string]: unknown;
  };
  note: string;
}

export interface CalibrationRef {
  calibration_id: string;
  result_hash: string;
  experiment_id: string;
  model_id: string;
  status: string;
  created_at?: string | null;
}

export interface CalibrationVerification {
  calibration_id: string;
  result_hash: string;
  ok: boolean;
  checks: { name: string; status: string; message: string }[];
  errors: number;
}

/** Validation / generalisation of a frozen calibration (M12C). */
export interface ValidationCapabilities {
  default_metrics: string[];
  metrics: string[];
  independence_checks: string[];
  verifiable_dimensions: string[];
  declared_dimensions: string[];
  default_max_evaluations: number;
  default_max_wall_seconds: number;
  report_gap_default: boolean;
}

export interface AcceptanceCriterion {
  metric: string;
  observation?: string | null;
  output?: string | null;
  op: "<=" | "<" | ">=" | ">";
  threshold: number;
  rationale?: string;
}

export interface CoordinateWindow {
  coordinate: string;
  lower?: number | string | null;
  upper?: number | string | null;
}

export interface IndependenceSpec {
  vs_dataset: DatasetRef;
  coordinate_windows?: CoordinateWindow[];
  group_key?: string | null;
  claimed_dimensions?: string[];
  declaration?: string;
}

export interface ValidationDatasetConfig {
  dataset: DatasetRef;
  mapping: Record<string, unknown>;
  independence: IndependenceSpec;
  label?: string;
  acceptance?: AcceptanceCriterion[] | null;
}

export interface ValidationConfig {
  schema_version?: string;
  experiment_id: string;
  model_ref: { model_id: string; version?: string | null };
  calibration: CalibrationRef;
  datasets: ValidationDatasetConfig[];
  evaluation?: EvaluationConfig;
  budget?: CalibrationBudget;
  execution?: CalibrationExecutionTemplate;
  acceptance?: AcceptanceCriterion[];
  report_gap?: boolean;
  allow_non_independent?: boolean;
  data_role?: string;
  notes?: string;
}

export interface IndependenceCheck {
  dimension: string;
  state: "verified" | "violated" | "declared" | "unverifiable" | string;
  message: string;
}

export interface IndependenceReport {
  status: string;
  checks: IndependenceCheck[];
  declaration: string;
  note: string;
}

export interface CoordinateRangeComparison {
  coordinate: string;
  kind: string;
  calibration_min: number | null;
  calibration_max: number | null;
  validation_min: number | null;
  validation_max: number | null;
  classification: string;
}

export interface ValidationContext {
  coordinate_ranges: CoordinateRangeComparison[];
  unseen_groups: string[];
  regime: string;
  note: string;
}

export interface AcceptanceOutcome {
  metric: string;
  observation?: string | null;
  output?: string | null;
  op: string;
  threshold: number;
  observed?: number | null;
  status: "met" | "not_met" | "indeterminate" | string;
  message: string;
}

export interface ValidationDatasetOutcome {
  label: string;
  dataset: DatasetRef;
  mapping_hash: string;
  independence: IndependenceReport;
  context: ValidationContext;
  run_id?: string | null;
  run_status?: string | null;
  evaluation_hash?: string | null;
  metrics: Record<string, number | null>;
  n_used: number;
  n_excluded: number;
  exclusion_counts: Record<string, number>;
  calibration_metrics: Record<string, number | null>;
  calibration_evaluation_hash?: string | null;
  acceptance: AcceptanceOutcome[];
  agreement: string;
  failure?: string | null;
  diagnostics: Diagnostic[];
}

export interface ValidationCalibrationSnapshot {
  calibration_id: string;
  result_hash: string;
  calibration_hash: string;
  model_id: string;
  model_hash: string;
  parameters: Record<string, number>;
  dataset_content_hash: string;
  dataset_science_hash: string;
  mapping_hash: string;
  evaluation_hash?: string | null;
}

export interface ValidationProvenance {
  experiment_id: string;
  spec_hash: string;
  model_id: string;
  model_hash: string;
  calibration_result_hash: string;
  calibration_hash: string;
  calibration_dataset_content_hash: string;
  calibration_dataset_science_hash: string;
  calibration_mapping_hash: string;
  calibration_evaluation_hash?: string | null;
  validation_dataset_content_hashes: string[];
  validation_science_hashes: string[];
  mapping_hashes: string[];
  evaluation_config_hash: string;
  evaluation_hashes: string[];
  environment_hash: string;
  engine_schema_version: string;
  scipy_version: string;
  deterministic: boolean;
}

/** The M12C validation outcome. Kept distinct from `ValidationResult` (spec validation). */
export interface ValidationOutcome {
  schema_version: string;
  validation_hash: string;
  result_hash: string;
  experiment_id: string;
  model_ref: { model_id: string; version?: string | null };
  config: ValidationConfig;
  calibration: ValidationCalibrationSnapshot;
  datasets: ValidationDatasetOutcome[];
  agreement_status: string;
  acceptance_status: string;
  independence_status: string;
  evaluations_requested: number;
  evaluations_completed: number;
  evaluations_failed: number;
  wall_seconds: number;
  descriptive: boolean;
  diagnostics: Diagnostic[];
  provenance: ValidationProvenance;
  note: string;
}

export interface ValidationRef {
  validation_id: string;
  result_hash: string;
  experiment_id: string;
  model_id: string;
  agreement_status: string;
  created_at?: string | null;
}

export interface ValidationVerification {
  validation_id: string;
  result_hash: string;
  ok: boolean;
  checks: { name: string; status: string; message: string }[];
  errors: number;
}

export interface ValidationStaleness {
  validation_id: string;
  result_hash: string;
  fresh: boolean;
  reasons: string[];
  checks: { name: string; status: string; message: string }[];
}

/** Scientific Intelligence (SI): structured plan / approval / execution contracts. */
export type SIActionCategory = "read" | "scientific" | "model" | "simulation";

export type SIStatus =
  | "proposed"
  | "approved"
  | "rejected"
  | "executed"
  | "failed"
  | "skipped"
  | "unsupported";

export type SIApprovalState = "not_required" | "required" | "approved" | "rejected";

export type SIEffect =
  | "none"
  | "creates_experiment"
  | "creates_calibration"
  | "creates_validation"
  | "creates_analysis"
  | "creates_dataset"
  | "creates_model_spec"
  | "modifies_model";

export interface SIActionRef {
  action_id: string;
  name: string;
  description: string;
  category: SIActionCategory;
  read_only: boolean;
  requires_approval: boolean;
  supported: boolean;
  effects: SIEffect;
  limitations: string[];
}

export interface SIActionPreview {
  action_id: string;
  name: string;
  description: string;
  read_only: boolean;
  requires_approval: boolean;
  supported: boolean;
  effects: SIEffect;
  inputs: Record<string, unknown>;
  input_diagnostics: Diagnostic[];
  summary: string;
  warnings: string[];
}

export interface SIExecutionResult {
  step_id: string;
  action_id: string;
  status: SIStatus;
  ok: boolean;
  summary: string;
  result: Record<string, unknown>;
  artifacts: Record<string, string>;
  diagnostics: Diagnostic[];
  error_code: string | null;
  error_message: string | null;
  started_at: string | null;
  finished_at: string | null;
}

export interface SIPlanStep {
  step_id: string;
  purpose: string;
  action_id: string;
  inputs: Record<string, unknown>;
  expected_output: string;
  scientific_rationale: string;
  depends_on: string[];
  approval: SIApprovalState;
  status: SIStatus;
  execution: SIExecutionResult | null;
}

export interface SIPlan {
  plan_id: string;
  objective: string;
  steps: SIPlanStep[];
  rationale: string;
  assumptions: string[];
  open_questions: string[];
  provider: string;
  used_ai: boolean;
  notes: string;
}

export interface SIAnalysis {
  schema_version: string;
  question: string;
  understanding: string;
  state_summary: string[];
  known: string[];
  missing_information: string[];
  unsupported_requests: string[];
  caveats: string[];
  plan: SIPlan | null;
  provider: string;
  used_ai: boolean;
  diagnostics: Diagnostic[];
}

export interface SIMessage {
  message_id: string;
  role: "user" | "si";
  text: string;
  analysis: SIAnalysis | null;
  at: string;
}

export interface SIInterpretation {
  interpretation_id: string;
  step_id: string;
  action_id: string;
  text: string;
  establishes: string[];
  does_not_establish: string[];
  limitations: string[];
  next_steps: string[];
  artifacts: Record<string, string>;
  at: string;
}

export interface SIInvestigationState {
  schema_version: string;
  investigation_id: string;
  project_id: string | null;
  objective: string;
  hypotheses: string[];
  assumptions: string[];
  models: string[];
  datasets: string[];
  experiments: string[];
  calibrations: string[];
  validations: string[];
  evidence: string[];
  unresolved_questions: string[];
  decisions: string[];
  messages: SIMessage[];
  plans: SIPlan[];
  executions: SIExecutionResult[];
  interpretations: SIInterpretation[];
  current_plan_id: string | null;
  current_next_step: string | null;
  created_at: string;
  updated_at: string;
}

export interface SIProviderStatus {
  llm_configured: boolean;
  provider: string;
  note: string;
}

export interface SIActionsResponse {
  actions: SIActionRef[];
  provider: SIProviderStatus;
}

export interface SIStateResponse {
  state: SIInvestigationState;
  next_step_preview?: SIActionPreview | null;
}

export interface SIAskResponse {
  analysis: SIAnalysis;
  state: SIInvestigationState;
}

export interface SIExecuteResponse {
  execution: SIExecutionResult;
  interpretation: SIInterpretation;
  state: SIInvestigationState;
}
