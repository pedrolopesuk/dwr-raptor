/**
 * Shared test fixtures and an in-memory `DrwClient` stub.
 *
 * Test-only: not imported by application code. Lets component tests exercise the
 * UI states (validation, failure, timeout, planner, projects) without Python.
 */

import { vi } from "vitest";

import type { DrwClient } from "@/lib/client";
import type {
  CalibrationCandidate,
  CalibrationRef,
  CalibrationResult,
  CsvInspection,
  DatasetDetail,
  DatasetImportResult,
  DatasetSummary,
  DatasetVerification,
  EvaluationResult,
  ExperimentData,
  ExperimentSpec,
  IdentifiabilityReport,
  ModelCapabilities,
  ModelSchema,
  ModelSummary,
  Project,
  ReproduceReport,
  RunRecord,
  SobolReport,
  UncertaintySummary,
  ValidationDatasetOutcome,
  ValidationOutcome,
  ValidationRef,
  ValidationResult,
} from "@/lib/types";

export const schema: ModelSchema = {
  model_id: "predator-prey",
  version: "1.0.0",
  description: "Lotka-Volterra predator-prey dynamics.",
  runtime: "python/scipy.solve_ivp",
  parameters: [
    { name: "alpha", type: "float", role: "input", unit: "1/s", description: "", nominal: 1.1, lower: 0.1, upper: 3, options: [], differentiable: true },
    { name: "prey0", type: "float", role: "state", unit: "count", description: "", nominal: 10, lower: 0.1, upper: 100, options: [], differentiable: false },
  ],
  outputs: [{ name: "prey", kind: "timeseries", unit: "count", description: "", axis_unit: "s" }],
  metadata: {},
};

export const sampleSpec = {
  hypothesis: "increasing alpha by 10% raises the prey peak",
  model_ref: { model_id: "predator-prey", version: "1.0.0" },
  baseline: { alpha: 1.1, prey0: 10 },
  factors: [{ parameter: "alpha", values: [1.21] }],
  outputs: ["prey"],
  analyses: [{ method: "delta" }],
  execution: { isolation: "subprocess", timeout_s: 60, max_runs: 512 },
} as unknown as ExperimentSpec;

export const capabilities: ModelCapabilities = {
  model_id: "predator-prey",
  version: "1.0.0",
  parameter_names: ["alpha", "prey0"],
  factorable_parameters: [{ name: "alpha", unit: "1/s", lower: 0.1, upper: 3 }],
  fixed_parameters: [],
  state_parameters: ["prey0"],
  categorical_parameters: [],
  timeseries_outputs: ["prey"],
  scalar_outputs: ["peak_prey"],
  sampling_methods: ["grid"],
  analysis_methods: ["delta", "relative_delta"],
  sensitivity: "oat",
  isolation: "subprocess",
  global_sensitivity: { default_sample_count: 32, max_evaluations: 4096 },
  identifiability: {
    method: "central_finite_difference_sensitivity_svd",
    default_step_scale: 0.001,
    condition_threshold: 1_000_000,
    max_evaluations: 4096,
    timeseries_features: ["max", "min", "mean", "final", "argmax_t"],
  },
  limitations: [],
};

export const oscillatorSchema: ModelSchema = {
  model_id: "oscillator",
  version: "1.0.0",
  description: "Linear mass-spring-damper oscillator.",
  runtime: "python/scipy.solve_ivp",
  parameters: [
    { name: "m", type: "float", role: "input", unit: "kg", description: "Mass.", nominal: 1, lower: 0.1, upper: 10, options: [], differentiable: true },
    { name: "x0", type: "float", role: "state", unit: "m", description: "Initial displacement.", nominal: 1, lower: -5, upper: 5, options: [], differentiable: false },
  ],
  outputs: [
    { name: "x", kind: "timeseries", unit: "m", description: "Displacement.", axis_unit: "s" },
    { name: "peak_displacement", kind: "scalar", unit: "m", description: "max |x|.", axis_unit: null },
  ],
  metadata: {},
};

export const oscillatorCapabilities: ModelCapabilities = {
  model_id: "oscillator",
  version: "1.0.0",
  parameter_names: ["m", "x0"],
  factorable_parameters: [
    { name: "m", unit: "kg", lower: 0.1, upper: 10 },
    { name: "x0", unit: "m", lower: -5, upper: 5 },
  ],
  fixed_parameters: [],
  state_parameters: ["x0"],
  categorical_parameters: [],
  timeseries_outputs: ["x"],
  scalar_outputs: ["peak_displacement"],
  sampling_methods: ["grid", "random", "latin_hypercube", "sobol"],
  analysis_methods: ["delta", "relative_delta"],
  sensitivity: "oat",
  isolation: "subprocess",
  global_sensitivity: { default_sample_count: 32, max_evaluations: 4096 },
  identifiability: {
    method: "central_finite_difference_sensitivity_svd",
    default_step_scale: 0.001,
    condition_threshold: 1_000_000,
    max_evaluations: 4096,
    timeseries_features: ["max", "min", "mean", "final", "argmax_t"],
  },
  limitations: [],
};

export const oscillatorSampleSpec = {
  hypothesis: "increasing m by 10% changes the trajectory and the peak output",
  model_ref: { model_id: "oscillator", version: "1.0.0" },
  baseline: { m: 1, x0: 1 },
  factors: [{ parameter: "m", values: [1.1] }],
  outputs: ["x"],
  analyses: [{ method: "delta" }],
  execution: { isolation: "subprocess", timeout_s: 60, max_runs: 512 },
} as unknown as ExperimentSpec;

export const lorenzCapabilities: ModelCapabilities = {
  model_id: "lorenz",
  version: "1.0.0",
  parameter_names: ["sigma", "rho", "beta"],
  factorable_parameters: [
    { name: "sigma", unit: "dimensionless", lower: 1, upper: 20 },
    { name: "rho", unit: "dimensionless", lower: 5, upper: 50 },
    { name: "beta", unit: "dimensionless", lower: 0.5, upper: 6 },
  ],
  fixed_parameters: [],
  state_parameters: [],
  categorical_parameters: [],
  timeseries_outputs: ["x", "y", "z"],
  scalar_outputs: ["max_abs_x"],
  sampling_methods: ["grid", "random", "latin_hypercube", "sobol"],
  analysis_methods: ["delta", "relative_delta"],
  sensitivity: "oat",
  isolation: "subprocess",
  global_sensitivity: { default_sample_count: 32, max_evaluations: 4096 },
  identifiability: {
    method: "central_finite_difference_sensitivity_svd",
    default_step_scale: 0.001,
    condition_threshold: 1_000_000,
    max_evaluations: 4096,
    timeseries_features: ["max", "min", "mean", "final", "argmax_t"],
  },
  limitations: [],
};

const modelSummaries: ModelSummary[] = [
  { model_id: "predator-prey", version: "1.0.0", description: "Lotka-Volterra predator-prey dynamics.", n_parameters: 6, n_outputs: 3 },
  { model_id: "oscillator", version: "1.0.0", description: "Linear mass-spring-damper oscillator.", n_parameters: 5, n_outputs: 3 },
  { model_id: "lorenz", version: "1.0.0", description: "Lorenz (1963) chaotic attractor.", n_parameters: 6, n_outputs: 4 },
];

/**
 * A `DrwClient` stub listing several registered models with their authoritative
 * capabilities, schemas and seeded specs. Used to test model-agnostic selection
 * without a Python process.
 */
export function multiModelClient(overrides: Partial<DrwClient> = {}): DrwClient {
  const schemas: Record<string, ModelSchema> = {
    "predator-prey": schema,
    oscillator: oscillatorSchema,
  };
  const capsById: Record<string, ModelCapabilities> = {
    "predator-prey": capabilities,
    oscillator: oscillatorCapabilities,
    lorenz: lorenzCapabilities,
  };
  const specsById: Record<string, ExperimentSpec> = {
    "predator-prey": sampleSpec,
    oscillator: oscillatorSampleSpec,
  };
  function must<T>(value: T | undefined, label: string): T {
    if (value === undefined) throw new Error(`no fixture for ${label}`);
    return value;
  }
  return stubClient({
    listModels: vi.fn().mockResolvedValue(modelSummaries),
    describeModel: vi.fn(async (modelId: string) => ({
      schema: must(schemas[modelId], modelId),
      model_hash: `hash-${modelId}`,
    })),
    capabilities: vi.fn(async (modelId: string) => must(capsById[modelId], modelId)),
    sampleExperiment: vi.fn(async (modelId?: string) =>
      must(specsById[modelId ?? "predator-prey"], modelId ?? "predator-prey"),
    ),
    ...overrides,
  });
}

export function reproduceReport(overrides: Partial<ReproduceReport> = {}): ReproduceReport {
  const output = {
    output: "prey",
    unit: "count",
    comparable: true,
    status: "identical" as const,
    identical: true,
    passes_tolerance: true,
    alignment: "exact",
    interpolated: false,
    shape_compatible: true,
    max_abs_delta: 0,
    max_abs_relative_delta: 0,
    mae: 0,
    rmse: 0,
    n_points: 301,
    valid_points: 301,
    non_finite_points: 0,
    warnings: [],
    note: null,
  };
  return {
    experiment_id: "exp-000000000000",
    verdict: "identical",
    numerical: "identical",
    tolerances: { rtol: 1e-9, atol: 1e-12 },
    provenance: {
      spec_hash_stored: "a".repeat(64),
      spec_hash_current: "a".repeat(64),
      spec_hash_match: true,
      model_hash_stored: "b".repeat(64),
      model_hash_current: "b".repeat(64),
      model_hash_match: true,
      environment_hash_stored: "c".repeat(64),
      environment_hash_current: "c".repeat(64),
      environment_hash_match: true,
      differences: [],
    },
    reference_run_ids: ["exp-000000000000-r0000", "exp-000000000000-r0001"],
    fresh_run_ids: ["exp-000000000000-r0000", "exp-000000000000-r0001"],
    runs: [
      {
        index: 0,
        label: "baseline",
        reference_run_id: "exp-000000000000-r0000",
        fresh_run_id: "exp-000000000000-r0000",
        reference_status: "succeeded",
        fresh_status: "succeeded",
        comparable: true,
        identical: true,
        passes_tolerance: true,
        outputs: [output],
        warnings: [],
      },
      {
        index: 1,
        label: "variant",
        reference_run_id: "exp-000000000000-r0001",
        fresh_run_id: "exp-000000000000-r0001",
        reference_status: "succeeded",
        fresh_status: "succeeded",
        comparable: true,
        identical: true,
        passes_tolerance: true,
        outputs: [output],
        warnings: [],
      },
    ],
    warnings: [],
    fresh_runs_persisted: false,
    ...overrides,
  };
}

export function uncertaintySummary(
  overrides: Partial<UncertaintySummary> = {},
): UncertaintySummary {
  return {
    schema_version: "1.0.0",
    sampling_method: "latin_hypercube",
    seed: 5,
    requested_variants: 3,
    valid_output_samples: 3,
    excluded_output_samples: 0,
    quantiles: [5, 50, 95],
    quantile_method: "linear",
    outputs: [
      {
        output: "peak_prey",
        unit: "count",
        requested_variants: 3,
        valid_samples: 3,
        excluded_samples: 0,
        exclusions: {},
        sufficient: true,
        mean: 2,
        std: 1,
        minimum: 1,
        maximum: 3,
        p05: 1.1,
        p50: 2,
        p95: 2.9,
        note: null,
      },
    ],
    note: null,
    descriptive_only: true,
    ...overrides,
  };
}

export function sobolReport(overrides: Partial<SobolReport> = {}): SobolReport {
  return {
    model_id: "predator-prey",
    output: "peak_prey",
    estimator: "saltelli2010_first_order+jansen1999_total_order",
    sample_count: 8,
    seed: 3,
    dimensions: 2,
    factors: ["alpha", "beta"],
    evaluations_requested: 32,
    evaluations_completed: 32,
    variance: 4.5,
    inconclusive: false,
    reasons: [],
    results: [
      { name: "alpha", s1: 0.4, st: 0.5, s1_ci: [0.3, 0.5], st_ci: [0.4, 0.6] },
      { name: "beta", s1: 0.3, st: 0.4, s1_ci: [0.2, 0.4], st_ci: [0.3, 0.5] },
    ],
    bootstrap_resamples: 20,
    independent_inputs_assumed: true,
    note: "finite-sample estimates; theoretical bounds are not imposed.",
    ...overrides,
  };
}

export function identifiabilityReport(
  overrides: Partial<IdentifiabilityReport> = {},
): IdentifiabilityReport {
  return {
    model_id: "predator-prey",
    experiment_id: "exp-000000000000",
    method: "central_finite_difference_sensitivity_svd",
    factors: ["beta", "predator0"],
    factors_detail: [
      {
        name: "beta", unit: "1/(count*s)", baseline_value: 0.4, step: 0.0004,
        lower: 0.05, upper: 2.0, plus_value: 0.4004, minus_value: 0.3996, valid: true, note: null,
      },
      {
        name: "predator0", unit: "count", baseline_value: 5.0, step: 0.005,
        lower: 0.1, upper: 50.0, plus_value: 5.005, minus_value: 4.995, valid: true, note: null,
      },
    ],
    targets: [
      {
        output: "prey", feature: "max", unit: "count", baseline_value: 13.67,
        scale: 13.67, informative: true, note: null,
      },
      {
        output: "prey", feature: "argmax_t", unit: "count", baseline_value: 9.9,
        scale: 9.9, informative: false, note: "no local response to the selected factors",
      },
    ],
    dimensions: 2,
    n_targets: 4,
    step_scale: 0.001,
    absolute_step: 0.000001,
    rank_tolerance: 0.00025,
    condition_threshold: 1_000_000,
    correlation_threshold: 0.9,
    evaluations_requested: 5,
    evaluations_completed: 5,
    singular_values: [83.4588, 7.39e-9],
    numerical_rank: 1,
    condition_number: null,
    directions: [
      {
        index: 0, singular_value: 83.4588, condition_index: 1.0, problematic: false,
        dominant: ["beta", "predator0"], weights: { beta: 0.971, predator0: 0.237 },
      },
      {
        index: 1, singular_value: 7.39e-9, condition_index: null, problematic: true,
        dominant: ["beta"], weights: { beta: 0.971, predator0: 0.237 },
      },
    ],
    factor_correlations: [{ first: "beta", second: "predator0", correlation: 1.0 }],
    verdict: "rank-deficient",
    inconclusive: false,
    reasons: [],
    normalized: true,
    local_only: true,
    note: "Local (linearised) structural identifiability at this baseline and these targets.",
    ...overrides,
  };
}

export function csvInspection(overrides: Partial<CsvInspection> = {}): CsvInspection {
  return {
    adapter_id: "csv",
    adapter_version: "1.0.0",
    filename: "lightcurve.csv",
    delimiter: ",",
    has_header: true,
    row_count: 3,
    columns: [
      {
        column: "time", index: 0, kind: "datetime", missing_count: 0, non_finite_count: 0,
        sample_values: ["2026-01-01T00:00:00Z"], suggested_role: "coordinate",
        suggested_name: "time", suggested_uncertainty_for: null, note: null,
      },
      {
        column: "flux", index: 1, kind: "float", missing_count: 0, non_finite_count: 0,
        sample_values: ["12.3"], suggested_role: "measurement",
        suggested_name: "flux", suggested_uncertainty_for: null, note: null,
      },
      {
        column: "flux_err", index: 2, kind: "float", missing_count: 0, non_finite_count: 0,
        sample_values: ["0.1"], suggested_role: "uncertainty",
        suggested_name: "flux_err", suggested_uncertainty_for: "flux", note: null,
      },
    ],
    preview: [{ time: "2026-01-01T00:00:00Z", flux: "12.3", flux_err: "0.1" }],
    diagnostics: [],
    advisory: "detections are advisory only",
    ...overrides,
  };
}

const HASH = "a".repeat(64);

export function datasetSummary(overrides: Partial<DatasetSummary> = {}): DatasetSummary {
  return {
    dataset_id: "ds-abcabcabcabc",
    content_hash: HASH,
    name: "lightcurve",
    created_at: "2026-01-01T00:00:00+00:00",
    source_kind: "file",
    ...overrides,
  };
}

export function datasetVerification(overrides: Partial<DatasetVerification> = {}): DatasetVerification {
  return {
    dataset_id: "ds-abcabcabcabc",
    content_hash: HASH,
    ok: true,
    errors: 0,
    checks: [{ name: "meta", status: "ok", message: "" }],
    extra_files: [],
    note: "verification is a consistency check",
    ...overrides,
  };
}

export function datasetDetail(overrides: Partial<DatasetDetail> = {}): DatasetDetail {
  return {
    ref: { dataset_id: "ds-abcabcabcabc", content_hash: HASH, name: "lightcurve", created_at: "2026-01-01T00:00:00+00:00" },
    dataset: {
      schema_version: "1.0.0",
      name: "lightcurve",
      description: "",
      labels: {},
      provenance: {
        source_kind: "file",
        imported_at: "2026-01-01T00:00:00+00:00",
        dataset_version: "1.0.0",
        adapter: { id: "csv", version: "1.0.0" },
        original_filename: "lightcurve.csv",
        source_sha256: "b".repeat(64),
        notes: "",
        license: null,
      },
      observation_set: {
        coordinates: ["time"],
        variables: [
          { name: "time", kind: "datetime", role: "coordinate", unit: null, depends_on: [], uncertainty: null, quality: null, description: "" },
          { name: "flux", kind: "float", role: "measurement", unit: "Jy", depends_on: ["time"], uncertainty: { type: "std", column: "flux_err" }, quality: null, description: "" },
        ],
        columns: { time: ["2026-01-01T00:00:00+00:00"], flux: [12.3] },
      },
      files: [],
      content_hash: HASH,
      dataset_id: "ds-abcabcabcabc",
    },
    verification: datasetVerification(),
    ...overrides,
  };
}

export function datasetImportResult(
  overrides: Partial<DatasetImportResult> = {},
): DatasetImportResult {
  return {
    ref: { dataset_id: "ds-abcabcabcabc", content_hash: HASH, name: "lightcurve", created_at: "2026-01-01T00:00:00+00:00" },
    dry_run: false,
    stored: true,
    verification: datasetVerification(),
    ...overrides,
  };
}

export function evaluationResult(overrides: Partial<EvaluationResult> = {}): EvaluationResult {
  return {
    eval_schema_version: "1.0.0",
    evaluation_hash: "e".repeat(64),
    dataset: {
      dataset_id: "ds-abcabcabcabc", content_hash: HASH, name: "lightcurve",
      created_at: "2026-01-01T00:00:00+00:00",
    },
    experiment_id: "exp-000000000000",
    run_id: "exp-000000000000-r0000",
    attempt: 1,
    model_ref: { model_id: "predator-prey", version: "1.0.0" },
    model_hash: "f".repeat(64),
    parameter_snapshot: {},
    mapping: {},
    mapping_hash: "a".repeat(64),
    config: { metrics: ["mean_residual", "mae", "rmse", "max_abs_error"] },
    pairs: [
      {
        observation: "peak_prey",
        output: "peak_prey",
        kind: "scalar",
        unit: "count",
        alignment: "exact",
        tolerance: 0,
        interpolated: false,
        points: [
          {
            observation_index: 0, model_index: null, coordinate: null, observed: 13.0,
            predicted: 14.0, residual: 1.0, relative_residual: null, sigma: null,
            normalized_residual: null,
          },
        ],
        exclusions: [{ observation_index: 1, reason: "missing", detail: "row 1 is missing" }],
        usable_count: 1,
        excluded_count: 1,
        exclusion_counts: { missing: 1 },
        metrics: { mean_residual: 1.0, mae: 1.0, rmse: 1.0, max_abs_error: 1.0 },
        diagnostics: [],
      },
    ],
    total_usable: 1,
    total_excluded: 1,
    ok: true,
    diagnostics: [],
    provenance: {
      spec_hash: "1".repeat(64), model_hash: "f".repeat(64), environment_hash: "2".repeat(64),
      dataset_content_hash: HASH, mapping_hash: "a".repeat(64),
    },
    ...overrides,
  };
}

export const defaultProject: Project = {
  project_id: "default",
  name: "Sample: predator-prey",
  description: "",
  model_id: "predator-prey",
  created_at: "2026-01-01T00:00:00+00:00",
};

export function calibrationResult(overrides: Partial<CalibrationResult> = {}): CalibrationResult {
  const candidate: CalibrationCandidate = {
    index: 0,
    parameters: { alpha: 1.1 },
    run_id: "exp-000000000000-r0000",
    run_status: "succeeded",
    evaluation_hash: "a".repeat(64),
    objective: 0.0,
    failure: null,
    n_used: 1,
    n_excluded: 0,
    duration_s: 0.01,
    diagnostics: [],
  };
  return {
    schema_version: "1.0.0",
    calibration_hash: "c".repeat(64),
    result_hash: "d".repeat(64),
    experiment_id: "exp-000000000000",
    status: "converged",
    stop_reason: "optimizer_converged",
    converged: true,
    best: candidate,
    objective: {
      metric: "rmse", observation: "peak_prey", output: "peak_prey", value: 0.0,
      invalid_objective_sentinel: "+inf",
    },
    evaluations_requested: 100,
    evaluations_completed: 3,
    evaluations_invalid: 0,
    iterations: 2,
    wall_seconds: 0.5,
    identifiability: null,
    history: [candidate],
    diagnostics: [],
    provenance: { scipy_version: "1.11.0" },
    config: {
      dataset: {
        dataset_id: "ds-abcabcabcabc", content_hash: HASH, name: "lightcurve",
        created_at: "2026-01-01T00:00:00+00:00",
      },
      mapping: {},
    },
    note: "Calibration reports a point estimate; not a statement of parameter uncertainty.",
    ...overrides,
  };
}

export function calibrationRef(overrides: Partial<CalibrationRef> = {}): CalibrationRef {
  return {
    calibration_id: "cal-dddddddddddd",
    result_hash: "d".repeat(64),
    experiment_id: "exp-000000000000",
    model_id: "predator-prey",
    status: "converged",
    created_at: "2026-01-01T00:00:00+00:00",
    ...overrides,
  };
}

export function validationRef(overrides: Partial<ValidationRef> = {}): ValidationRef {
  return {
    validation_id: "val-eeeeeeeeeeee",
    result_hash: "e".repeat(64),
    experiment_id: "exp-000000000000",
    model_id: "predator-prey",
    agreement_status: "evaluated",
    created_at: "2026-01-01T00:00:00+00:00",
    ...overrides,
  };
}

export function validationDatasetOutcome(
  overrides: Partial<ValidationDatasetOutcome> = {},
): ValidationDatasetOutcome {
  return {
    label: "held out",
    dataset: {
      dataset_id: "ds-abcabcabcabc", content_hash: "a".repeat(64), name: "lightcurve",
      created_at: "2026-01-01T00:00:00+00:00",
    },
    mapping_hash: "3".repeat(64),
    independence: {
      status: "verified",
      checks: [{ dimension: "dataset", state: "verified", message: "distinct" }],
      declaration: "",
      note: "every claimed independence dimension was verified mechanically.",
    },
    context: {
      coordinate_ranges: [],
      unseen_groups: [],
      regime: "",
      note: "Validation data lies within the calibration coordinate range.",
    },
    run_id: "exp-000000000000-r0000",
    run_status: "succeeded",
    evaluation_hash: "4".repeat(64),
    metrics: { rmse: 0.1, mae: 0.08, max_abs_error: 0.2 },
    n_used: 3,
    n_excluded: 0,
    exclusion_counts: {},
    calibration_metrics: { rmse: 0.05, mae: 0.04, max_abs_error: 0.1 },
    calibration_evaluation_hash: "5".repeat(64),
    acceptance: [
      {
        metric: "rmse", observation: null, output: null, op: "<=", threshold: 0.5,
        observed: 0.1, status: "met", message: "",
      },
    ],
    agreement: "evaluated",
    failure: null,
    diagnostics: [],
    ...overrides,
  };
}

export function validationOutcome(overrides: Partial<ValidationOutcome> = {}): ValidationOutcome {
  const snapshot = calibrationRef();
  return {
    schema_version: "1.0.0",
    validation_hash: "1".repeat(64),
    result_hash: "e".repeat(64),
    experiment_id: "exp-000000000000",
    model_ref: { model_id: "predator-prey", version: "1.0.0" },
    config: {
      experiment_id: "exp-000000000000",
      model_ref: { model_id: "predator-prey" },
      calibration: snapshot,
      datasets: [],
    },
    calibration: {
      calibration_id: snapshot.calibration_id,
      result_hash: snapshot.result_hash,
      calibration_hash: "c".repeat(64),
      model_id: "predator-prey",
      model_hash: "f".repeat(64),
      parameters: { alpha: 1.1 },
      dataset_content_hash: "a".repeat(64),
      dataset_science_hash: "2".repeat(64),
      mapping_hash: "3".repeat(64),
      evaluation_hash: null,
    },
    datasets: [validationDatasetOutcome()],
    agreement_status: "evaluated",
    acceptance_status: "met",
    independence_status: "verified",
    evaluations_requested: 10,
    evaluations_completed: 2,
    evaluations_failed: 0,
    wall_seconds: 0.4,
    descriptive: false,
    diagnostics: [],
    provenance: {
      experiment_id: "exp-000000000000",
      spec_hash: "a".repeat(64),
      model_id: "predator-prey",
      model_hash: "f".repeat(64),
      calibration_result_hash: snapshot.result_hash,
      calibration_hash: "c".repeat(64),
      calibration_dataset_content_hash: "a".repeat(64),
      calibration_dataset_science_hash: "2".repeat(64),
      calibration_mapping_hash: "3".repeat(64),
      calibration_evaluation_hash: null,
      validation_dataset_content_hashes: ["a".repeat(64)],
      validation_science_hashes: ["2".repeat(64)],
      mapping_hashes: ["3".repeat(64)],
      evaluation_config_hash: "6".repeat(64),
      evaluation_hashes: ["4".repeat(64)],
      environment_hash: "7".repeat(64),
      engine_schema_version: "1.0.0",
      scipy_version: "1.11.0",
      deterministic: true,
    },
    note: "Validation tests a frozen calibrated model against observations that were not used to fit it.",
    ...overrides,
  };
}

export const okValidation: ValidationResult = {
  ok: true,
  diagnostics: [],
  estimate: { method: "grid", baseline_runs: 1, variant_runs: 1, total_runs: 2, warnings: [] },
};

export function record(overrides: Partial<RunRecord> = {}): RunRecord {
  return {
    run_id: "exp-000000000000-r0000",
    label: "baseline",
    status: "succeeded",
    isolation: "subprocess",
    timed_out: false,
    attempt: 1,
    parent_run_id: null,
    inputs: { alpha: 1.1, prey0: 10 },
    metrics: { peak_prey: 13.67 },
    diagnostics: [],
    error: null,
    duration_s: 0.01,
    result: null,
    ...overrides,
  };
}

export function succeededData(): ExperimentData {
  return {
    experiment_id: "exp-000000000000",
    name: "sample",
    hypothesis: sampleSpec.hypothesis,
    model_ref: { model_id: "predator-prey", version: "1.0.0" },
    isolation: "subprocess",
    spec_hash: "a".repeat(64),
    model_hash: "b".repeat(64),
    environment: {},
    estimate: okValidation.estimate,
    warnings: [],
    runs: [record(), record({ run_id: "exp-000000000000-r0001", label: "variant" })],
    comparisons: [],
    started_at: null,
    finished_at: null,
  };
}

export function stubClient(overrides: Partial<DrwClient> = {}): DrwClient {
  const base: DrwClient = {
    listModels: vi.fn().mockResolvedValue([
      { model_id: "predator-prey", version: "1.0.0", description: "", n_parameters: 6, n_outputs: 3 },
    ]),
    describeModel: vi.fn().mockResolvedValue({ schema, model_hash: "model-hash" }),
    capabilities: vi.fn().mockResolvedValue(capabilities),
    sampleExperiment: vi.fn().mockResolvedValue(sampleSpec),
    validate: vi.fn().mockResolvedValue(okValidation),
    run: vi.fn().mockResolvedValue(succeededData()),
    jobStatus: vi.fn().mockResolvedValue({
      job_id: "job-0000000000000000",
      phase: "pending",
      terminal: false,
      completed_runs: 0,
      total_runs: null,
      status: null,
      events: [],
    }),
    listExperiments: vi.fn().mockResolvedValue([]),
    getExperiment: vi.fn(),
    evidence: vi.fn(),
    exportEvidence: vi.fn().mockResolvedValue({ zip: "evidence.zip", path: "/tmp/evidence.zip" }),
    sensitivity: vi.fn().mockResolvedValue({ metric: "peak_prey", perturbation: "+10%", ranking: [] }),
    uncertainty: vi.fn().mockResolvedValue(uncertaintySummary()),
    globalSensitivity: vi.fn().mockResolvedValue(sobolReport()),
    identifiability: vi.fn().mockResolvedValue(identifiabilityReport()),
    reproduceExperiment: vi.fn().mockResolvedValue(reproduceReport()),
    listProjects: vi.fn().mockResolvedValue([defaultProject]),
    createProject: vi.fn().mockResolvedValue({
      project_id: "proj-aaaaaaaaaaaa",
      name: "New study",
      description: "",
      model_id: null,
      created_at: "2026-01-02T00:00:00+00:00",
    }),
    planExperiment: vi.fn().mockResolvedValue({
      spec: null,
      assumptions: [],
      questions: ["What is the research question?"],
      diagnostics: [],
      validation_ok: true,
      provider: "rule-based",
      used_ai: false,
      rationale: "",
    }),
    plannerStatus: vi.fn().mockResolvedValue({
      llm_configured: false,
      provider: "rule-based",
      note: "No LLM provider is configured; the deterministic rule-based planner is used.",
    }),
    environment: vi.fn().mockResolvedValue({ environment: { python_version: "3.14.6" }, environment_hash: "env" }),
    listDatasetSources: vi.fn().mockResolvedValue([{ filename: "lightcurve.csv", size_bytes: 120 }]),
    inspectDataset: vi.fn().mockResolvedValue(csvInspection()),
    importDataset: vi.fn().mockResolvedValue(datasetImportResult()),
    listDatasets: vi.fn().mockResolvedValue([datasetSummary()]),
    describeDataset: vi.fn().mockResolvedValue(datasetDetail()),
    verifyDataset: vi.fn().mockResolvedValue(datasetVerification()),
    evaluate: vi.fn().mockResolvedValue(evaluationResult()),
    calibrate: vi.fn().mockResolvedValue({ calibration: calibrationResult() }),
    listCalibrations: vi.fn().mockResolvedValue([calibrationRef()]),
    getCalibration: vi.fn().mockResolvedValue({ calibration: calibrationResult(), ref: calibrationRef() }),
    runValidation: vi.fn().mockResolvedValue({ validation: validationOutcome(), ref: validationRef() }),
    listValidations: vi.fn().mockResolvedValue([validationRef()]),
    getValidation: vi.fn().mockResolvedValue({ validation: validationOutcome(), ref: validationRef() }),
    verifyValidation: vi.fn().mockResolvedValue({
      validation_id: "val-eeeeeeeeeeee",
      result_hash: "e".repeat(64),
      ok: true,
      checks: [{ name: "result_hash", status: "ok", message: "" }],
      errors: 0,
    }),
    checkValidationStaleness: vi.fn().mockResolvedValue({
      validation_id: "val-eeeeeeeeeeee",
      result_hash: "e".repeat(64),
      fresh: true,
      reasons: [],
      checks: [],
    }),
  };
  return { ...base, ...overrides };
}
