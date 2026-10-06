/**
 * Browser client for the DRW API.
 *
 * Thin wrapper over `fetch` that unwraps the bridge envelope and throws
 * `ApiError` on failure. No computation happens here.
 */

import type { ExperimentSpec } from "./types";
import type {
  CalibrationConfig,
  CalibrationRef,
  CalibrationResult,
  CsvImportConfig,
  CsvInspection,
  DatasetDetail,
  DatasetImportResult,
  DatasetSource,
  DatasetSummary,
  DatasetVerification,
  EnvironmentData,
  EvaluationConfig,
  EvaluationResult,
  EvidenceData,
  ExperimentData,
  ExperimentSummary,
  IdentifiabilityReport,
  JobStatus,
  ModelCapabilities,
  ModelSchema,
  ModelSummary,
  PlanProposal,
  PlannerStatus,
  Project,
  ReproduceReport,
  SensitivityData,
  SobolReport,
  UncertaintySummary,
  ValidationResult,
} from "./types";

export interface RunOptions {
  signal?: AbortSignal;
  projectId?: string;
  jobId?: string;
}

export interface LoadedExperiment {
  meta: ExperimentSummary;
  spec: ExperimentSpec;
  results: ExperimentData;
}

export interface DrwClient {
  listModels(): Promise<ModelSummary[]>;
  describeModel(modelId: string): Promise<{ schema: ModelSchema; model_hash: string }>;
  capabilities(modelId: string): Promise<ModelCapabilities>;
  sampleExperiment(modelId?: string): Promise<ExperimentSpec>;
  validate(spec: ExperimentSpec, options?: { signal?: AbortSignal }): Promise<ValidationResult>;
  run(spec: ExperimentSpec, options?: RunOptions): Promise<ExperimentData>;
  jobStatus(jobId: string): Promise<JobStatus>;
  listExperiments(projectId?: string): Promise<ExperimentSummary[]>;
  getExperiment(experimentId: string): Promise<LoadedExperiment>;
  evidence(experimentId: string): Promise<EvidenceData>;
  exportEvidence(experimentId: string): Promise<{ zip: string; path: string }>;
  sensitivity(experimentId: string): Promise<SensitivityData>;
  uncertainty(experimentId: string): Promise<UncertaintySummary>;
  globalSensitivity(
    experimentId: string,
    options?: { output?: string; factors?: string[]; sampleCount?: number; seed?: number },
  ): Promise<SobolReport>;
  identifiability(
    experimentId: string,
    options?: { factors?: string[]; outputs?: string[]; stepScale?: number; seed?: number },
  ): Promise<IdentifiabilityReport>;
  reproduceExperiment(experimentId: string, rtol: number, atol: number): Promise<ReproduceReport>;
  listProjects(): Promise<Project[]>;
  createProject(name: string, modelId?: string): Promise<Project>;
  planExperiment(modelId: string, question: string, context?: string): Promise<PlanProposal>;
  plannerStatus(): Promise<PlannerStatus>;
  environment(): Promise<EnvironmentData>;
  listDatasetSources(): Promise<DatasetSource[]>;
  inspectDataset(
    filename: string,
    options?: { delimiter?: string; hasHeader?: boolean; missingCodes?: string[] },
  ): Promise<CsvInspection>;
  importDataset(
    filename: string,
    config: CsvImportConfig,
    dryRun?: boolean,
  ): Promise<DatasetImportResult>;
  listDatasets(): Promise<DatasetSummary[]>;
  describeDataset(datasetId: string): Promise<DatasetDetail>;
  verifyDataset(datasetId: string): Promise<DatasetVerification>;
  evaluate(
    experimentId: string,
    options: { runId?: string; mapping: unknown; config?: EvaluationConfig },
  ): Promise<EvaluationResult>;
  calibrate(
    experimentId: string,
    options: { config: CalibrationConfig; persist?: boolean; jobId?: string },
  ): Promise<{ calibration: CalibrationResult; ref?: CalibrationRef }>;
}

export class ApiError extends Error {
  readonly code: string;
  readonly diagnostics: unknown[];

  constructor(code: string, message: string, diagnostics: unknown[] = []) {
    super(message);
    this.name = "ApiError";
    this.code = code;
    this.diagnostics = diagnostics;
  }
}

interface Envelope {
  ok?: boolean;
  data?: unknown;
  error?: { code?: string; message?: string; diagnostics?: unknown[] };
}

export function unwrap<T>(body: unknown): T {
  const envelope = body as Envelope | null;
  if (envelope && envelope.ok === true) {
    return envelope.data as T;
  }
  const error = envelope?.error ?? {};
  throw new ApiError(error.code ?? "error", error.message ?? "request failed", error.diagnostics ?? []);
}

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(url, init);
  } catch (cause) {
    throw new ApiError(
      "network_error",
      cause instanceof Error ? cause.message : "the request could not be sent",
    );
  }
  const body = await response.json().catch(() => null);
  return unwrap<T>(body);
}

function post(body: unknown, signal?: AbortSignal): RequestInit {
  return {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
    signal,
  };
}

export function createFetchClient(): DrwClient {
  return {
    listModels: async () => (await request<{ models: ModelSummary[] }>("/api/models")).models,
    describeModel: (modelId) =>
      request<{ schema: ModelSchema; model_hash: string }>(
        `/api/models/${encodeURIComponent(modelId)}`,
      ),
    capabilities: async (modelId) =>
      (
        await request<{ capabilities: ModelCapabilities }>(
          `/api/models/${encodeURIComponent(modelId)}/capabilities`,
        )
      ).capabilities,
    sampleExperiment: async (modelId) =>
      (
        await request<{ spec: ExperimentSpec }>(
          "/api/experiments/sample",
          post(modelId ? { model_id: modelId } : {}),
        )
      ).spec,
    validate: (spec, options) =>
      request<ValidationResult>("/api/validate", post({ spec }, options?.signal)),
    run: (spec, options) =>
      request<ExperimentData>(
        "/api/experiments",
        post(
          { spec, project_id: options?.projectId, job_id: options?.jobId },
          options?.signal,
        ),
      ),
    jobStatus: (jobId) =>
      request<JobStatus>(`/api/jobs/${encodeURIComponent(jobId)}`),
    listExperiments: async (projectId) => {
      const query = projectId ? `?project_id=${encodeURIComponent(projectId)}` : "";
      return (await request<{ experiments: ExperimentSummary[] }>(`/api/experiments${query}`))
        .experiments;
    },
    getExperiment: async (experimentId) =>
      (
        await request<{ experiment: LoadedExperiment }>(
          `/api/experiments/${encodeURIComponent(experimentId)}`,
        )
      ).experiment,
    evidence: async (experimentId) =>
      (
        await request<{ evidence: EvidenceData }>(
          `/api/experiments/${encodeURIComponent(experimentId)}/evidence`,
        )
      ).evidence,
    exportEvidence: (experimentId) =>
      request<{ zip: string; path: string }>(
        `/api/experiments/${encodeURIComponent(experimentId)}/evidence`,
        post({}),
      ),
    sensitivity: (experimentId) =>
      request<SensitivityData>(`/api/experiments/${encodeURIComponent(experimentId)}/sensitivity`),
    uncertainty: async (experimentId) =>
      (
        await request<{ uncertainty: UncertaintySummary }>(
          `/api/experiments/${encodeURIComponent(experimentId)}/uncertainty`,
        )
      ).uncertainty,
    globalSensitivity: async (experimentId, options) => {
      const params: Record<string, unknown> = {};
      if (options?.output) params.output = options.output;
      if (options?.factors && options.factors.length > 0) params.factors = options.factors;
      if (options?.sampleCount !== undefined) params.sample_count = options.sampleCount;
      if (options?.seed !== undefined) params.seed = options.seed;
      const body = await request<{ report: SobolReport }>(
        `/api/experiments/${encodeURIComponent(experimentId)}/global-sensitivity`,
        post(params),
      );
      return body.report;
    },
    identifiability: async (experimentId, options) => {
      const params: Record<string, unknown> = {};
      if (options?.factors && options.factors.length > 0) params.factors = options.factors;
      if (options?.outputs && options.outputs.length > 0) params.outputs = options.outputs;
      if (options?.stepScale !== undefined) params.step_scale = options.stepScale;
      if (options?.seed !== undefined) params.seed = options.seed;
      const body = await request<{ report: IdentifiabilityReport }>(
        `/api/experiments/${encodeURIComponent(experimentId)}/identifiability`,
        post(params),
      );
      return body.report;
    },
    reproduceExperiment: async (experimentId, rtol, atol) =>
      (
        await request<{ report: ReproduceReport }>(
          `/api/experiments/${encodeURIComponent(experimentId)}/reproduce`,
          post({ rtol, atol }),
        )
      ).report,
    listProjects: async () =>
      (await request<{ projects: Project[] }>("/api/projects")).projects,
    createProject: async (name, modelId) =>
      (
        await request<{ project: Project }>(
          "/api/projects",
          post(modelId ? { name, model_id: modelId } : { name }),
        )
      ).project,
    planExperiment: (modelId, question, context) =>
      request<PlanProposal>(
        "/api/plan",
        post(context ? { model_id: modelId, question, context } : { model_id: modelId, question }),
      ),
    plannerStatus: () => request<PlannerStatus>("/api/planner"),
    environment: (): Promise<EnvironmentData> => request<EnvironmentData>("/api/environment"),
    listDatasetSources: async () =>
      (await request<{ sources: DatasetSource[] }>("/api/datasets/sources")).sources,
    inspectDataset: async (filename, options) => {
      const params: Record<string, unknown> = { filename };
      if (options?.delimiter) params.delimiter = options.delimiter;
      if (options?.hasHeader !== undefined) params.has_header = options.hasHeader;
      if (options?.missingCodes && options.missingCodes.length > 0) {
        params.missing_codes = options.missingCodes;
      }
      return (await request<{ inspection: CsvInspection }>("/api/datasets/inspect", post(params)))
        .inspection;
    },
    importDataset: (filename, config, dryRun) =>
      request<DatasetImportResult>(
        "/api/datasets/import",
        post({ filename, config, dry_run: dryRun ?? false }),
      ),
    listDatasets: async () =>
      (await request<{ datasets: DatasetSummary[] }>("/api/datasets")).datasets,
    describeDataset: (datasetId) =>
      request<DatasetDetail>(`/api/datasets/${encodeURIComponent(datasetId)}`),
    verifyDataset: async (datasetId) =>
      (
        await request<{ verification: DatasetVerification }>(
          `/api/datasets/${encodeURIComponent(datasetId)}/verify`,
        )
      ).verification,
    evaluate: async (experimentId, options) =>
      (
        await request<{ evaluation: EvaluationResult }>(
          `/api/experiments/${encodeURIComponent(experimentId)}/evaluate`,
          post({ run_id: options.runId, mapping: options.mapping, config: options.config }),
        )
      ).evaluation,
    calibrate: (experimentId, options) =>
      request<{ calibration: CalibrationResult; ref?: CalibrationRef }>(
        `/api/experiments/${encodeURIComponent(experimentId)}/calibrate`,
        post({ config: options.config, persist: options.persist, job_id: options.jobId }),
      ),
  };
}
