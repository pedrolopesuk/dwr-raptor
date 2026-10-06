/**
 * Request handlers shared by the Next.js route handlers and the tests.
 *
 * Handlers return a plain `{ status, body }` (not a `Response`) so they can be
 * exercised directly in tests without a running HTTP server. The route files are
 * thin adapters that turn a `HandlerResult` into a `Response`.
 */

import { callBridge } from "./bridge";
import type { BridgeResponse } from "./types";

export interface HandlerResult {
  status: number;
  body: BridgeResponse<unknown>;
}

const STATUS_BY_CODE: Record<string, number> = {
  bad_request: 400,
  invalid_spec: 400,
  validation_error: 400,
  unknown_op: 400,
  unsupported_capability: 422,
  question_too_short: 422,
  not_found: 404,
  cancelled: 499,
  bridge_error: 502,
  internal_error: 500,
};

async function dispatch(
  op: string,
  params: Record<string, unknown>,
  signal?: AbortSignal,
): Promise<HandlerResult> {
  const body = await callBridge({ op, params }, { signal });
  if (body.ok) return { status: 200, body };
  const status = STATUS_BY_CODE[body.error.code] ?? 500;
  return { status, body };
}

export const handlers = {
  listModels: () => dispatch("list_models", {}),
  describeModel: (modelId: string) => dispatch("describe_model", { model_id: modelId }),
  capabilities: (modelId: string) => dispatch("capabilities", { model_id: modelId }),
  sampleExperiment: (modelId?: string) =>
    dispatch("sample_experiment", modelId ? { model_id: modelId } : {}),
  validate: (spec: unknown, signal?: AbortSignal) => dispatch("validate", { spec }, signal),
  run: (spec: unknown, options?: { signal?: AbortSignal; projectId?: string; jobId?: string }) =>
    dispatch(
      "run",
      {
        spec,
        ...(options?.projectId ? { project_id: options.projectId } : {}),
        ...(options?.jobId ? { job_id: options.jobId } : {}),
      },
      options?.signal,
    ),
  jobStatus: (jobId: string) => dispatch("job_status", { job_id: jobId }),
  listExperiments: (projectId?: string) =>
    dispatch("list_experiments", projectId ? { project_id: projectId } : {}),
  getExperiment: (experimentId: string) =>
    dispatch("get_experiment", { experiment_id: experimentId }),
  evidence: (experimentId: string) => dispatch("evidence", { experiment_id: experimentId }),
  exportEvidence: (experimentId: string) =>
    dispatch("export_evidence", { experiment_id: experimentId }),
  sensitivity: (experimentId: string) =>
    dispatch("sensitivity", { experiment_id: experimentId }),
  uncertainty: (experimentId: string) =>
    dispatch("uncertainty", { experiment_id: experimentId }),
  globalSensitivity: (experimentId: string, params: Record<string, unknown>) =>
    // The URL experiment id is authoritative: a caller-supplied body field may
    // not override it (the spread is ordered so that the path id wins).
    dispatch("global_sensitivity", { ...params, experiment_id: experimentId }),
  identifiability: (experimentId: string, params: Record<string, unknown>) =>
    // Same rule: the path experiment id wins over any body field.
    dispatch("identifiability", { ...params, experiment_id: experimentId }),
  reproduceExperiment: (experimentId: string, rtol: unknown, atol: unknown) =>
    dispatch("reproduce_experiment", { experiment_id: experimentId, rtol, atol }),
  listProjects: () => dispatch("list_projects", {}),
  createProject: (name: string, modelId?: string) =>
    dispatch("create_project", modelId ? { name, model_id: modelId } : { name }),
  planExperiment: (modelId: string, question: string, context?: string) =>
    dispatch("plan_experiment", context ? { model_id: modelId, question, context } : { model_id: modelId, question }),
  plannerStatus: () => dispatch("planner_status", {}),
  environment: () => dispatch("environment", {}),
  listDatasetSources: () => dispatch("list_dataset_sources", {}),
  inspectDataset: (params: Record<string, unknown>) => dispatch("inspect_dataset", params),
  importDataset: (params: Record<string, unknown>) => dispatch("import_dataset", params),
  listDatasets: () => dispatch("list_datasets", {}),
  describeDataset: (datasetId: string) => dispatch("describe_dataset", { dataset_id: datasetId }),
  verifyDataset: (datasetId: string) => dispatch("verify_dataset", { dataset_id: datasetId }),
  evaluateExperiment: (experimentId: string, params: Record<string, unknown>) =>
    // The URL experiment id is authoritative: a body field may not override it.
    dispatch("evaluate", { ...params, experiment_id: experimentId }),
  calibrateExperiment: (experimentId: string, params: Record<string, unknown>) =>
    // The URL experiment id is authoritative: a body field may not override it.
    dispatch("calibrate", { ...params, experiment_id: experimentId }),
};
