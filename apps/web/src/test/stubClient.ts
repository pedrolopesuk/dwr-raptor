/**
 * Shared test fixtures and an in-memory `DrwClient` stub.
 *
 * Test-only: not imported by application code. Lets component tests exercise the
 * UI states (validation, failure, timeout, planner, projects) without Python.
 */

import { vi } from "vitest";

import type { DrwClient } from "@/lib/client";
import type {
  ExperimentData,
  ExperimentSpec,
  ModelCapabilities,
  ModelSchema,
  ModelSummary,
  Project,
  RunRecord,
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

export const defaultProject: Project = {
  project_id: "default",
  name: "Sample: predator-prey",
  description: "",
  model_id: "predator-prey",
  created_at: "2026-01-01T00:00:00+00:00",
};

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
  };
  return { ...base, ...overrides };
}
