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
