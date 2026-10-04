/**
 * TypeScript mirror of the DRW `ExperimentSpec` contract.
 *
 * IMPORTANT: the Python Pydantic models in `packages/core` are the single source
 * of truth. These types mirror them for the web/TS side, and the generated JSON
 * Schemas under `./schema` are produced by `scripts/export_schemas.py`.
 *
 * `validateExperimentSpecShape` is a deliberately minimal client-side guard to
 * fail fast in the UI. It is NOT a substitute for the authoritative Python
 * validator (`drw.schema.experiment.validate_experiment`).
 */

export const EXPERIMENT_SPEC_SCHEMA_VERSION = "1.0.0";

export interface ModelRef {
  model_id: string;
  version?: string | null;
}

export type SamplingMethod = "grid" | "random" | "latin_hypercube" | "sobol";

export type AnalysisMethod =
  | "delta"
  | "relative_delta"
  | "sensitivity"
  | "uncertainty"
  | "optimization";

export type SolverChoice = "auto" | "explicit" | "stiff";

/** Process boundary used by the run engine. `subprocess` enforces `timeout_s`. */
export type IsolationMode = "in_process" | "subprocess";

export interface FactorSpec {
  parameter: string;
  values?: number[];
  lower?: number | null;
  upper?: number | null;
  steps?: number | null;
}

export interface SamplingSpec {
  method: SamplingMethod;
  n_samples?: number | null;
  seed?: number;
}

export interface ConstraintSpec {
  parameter: string;
  op: "<=" | "<" | ">=" | ">" | "==";
  value: number;
}

export interface AnalysisSpec {
  method: AnalysisMethod;
  config?: Record<string, unknown>;
  outputs?: string[];
}

export interface ExecutionSpec {
  solver?: SolverChoice;
  timeout_s?: number;
  max_runs?: number;
  isolation?: IsolationMode;
  workdir?: string | null;
}

export interface VerificationSpec {
  rtol?: number;
  atol?: number;
  relative_epsilon?: number;
  checks?: string[];
}

export interface ReportingSpec {
  title?: string;
  template?: string;
  formats?: string[];
}

export type ScalarValue = number | boolean | string;

export interface ExperimentSpec {
  schema_version?: string;
  name?: string;
  hypothesis: string;
  model_ref: ModelRef;
  baseline: Record<string, ScalarValue>;
  factors?: FactorSpec[];
  outputs?: string[];
  sampling?: SamplingSpec;
  constraints?: ConstraintSpec[];
  analyses?: AnalysisSpec[];
  execution?: ExecutionSpec;
  verification?: VerificationSpec;
  reporting?: ReportingSpec;
}

export interface ValidationIssue {
  code: string;
  message: string;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

/**
 * Minimal structural check. Returns an array of issues; empty means the object
 * has the required top-level shape.
 */
export function validateExperimentSpecShape(spec: unknown): ValidationIssue[] {
  const issues: ValidationIssue[] = [];
  if (!isRecord(spec)) {
    return [{ code: "not_an_object", message: "experiment spec must be a JSON object" }];
  }
  if (typeof spec.hypothesis !== "string" || spec.hypothesis.trim() === "") {
    issues.push({ code: "missing_hypothesis", message: "hypothesis must be a non-empty string" });
  }
  if (!isRecord(spec.model_ref) || typeof spec.model_ref.model_id !== "string") {
    issues.push({
      code: "missing_model_ref",
      message: "model_ref must be an object with a string model_id",
    });
  }
  if (!isRecord(spec.baseline)) {
    issues.push({ code: "missing_baseline", message: "baseline must be an object" });
  }
  if (spec.factors !== undefined && !Array.isArray(spec.factors)) {
    issues.push({ code: "invalid_factors", message: "factors must be an array" });
  }
  return issues;
}
