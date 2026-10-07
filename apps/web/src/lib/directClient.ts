/**
 * In-process `DrwClient` that calls the route handlers directly.
 *
 * Used by integration and end-to-end tests so they exercise the real UI + the
 * real handler logic + the real Python bridge without booting an HTTP server.
 * It is not used by the running application.
 */

import { unwrap, type DrwClient, type LoadedExperiment, type RunOptions } from "./client";
import { handlers, type HandlerResult } from "./handlers";
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
  ExperimentSpec,
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
  ValidationConfig,
  ValidationOutcome,
  ValidationRef,
  ValidationResult,
  ValidationStaleness,
  ValidationVerification,
} from "./types";

async function from<T>(result: Promise<HandlerResult>): Promise<T> {
  return unwrap<T>((await result).body);
}

export function createDirectClient(): DrwClient {
  return {
    listModels: async () =>
      (await from<{ models: ModelSummary[] }>(handlers.listModels())).models,
    describeModel: (modelId) =>
      from<{ schema: ModelSchema; model_hash: string }>(handlers.describeModel(modelId)),
    capabilities: async (modelId) =>
      (await from<{ capabilities: ModelCapabilities }>(handlers.capabilities(modelId)))
        .capabilities,
    sampleExperiment: async (modelId) =>
      (await from<{ spec: ExperimentSpec }>(handlers.sampleExperiment(modelId))).spec,
    validate: (spec: ExperimentSpec, options) =>
      from<ValidationResult>(handlers.validate(spec, options?.signal)),
    run: (spec: ExperimentSpec, options?: RunOptions) =>
      from<ExperimentData>(handlers.run(spec, options)),
    jobStatus: (jobId) => from<JobStatus>(handlers.jobStatus(jobId)),
    listExperiments: async (projectId) =>
      (await from<{ experiments: ExperimentSummary[] }>(handlers.listExperiments(projectId)))
        .experiments,
    getExperiment: async (experimentId) =>
      (await from<{ experiment: LoadedExperiment }>(handlers.getExperiment(experimentId)))
        .experiment,
    evidence: async (experimentId) =>
      (await from<{ evidence: EvidenceData }>(handlers.evidence(experimentId))).evidence,
    exportEvidence: (experimentId) =>
      from<{ zip: string; path: string }>(handlers.exportEvidence(experimentId)),
    sensitivity: (experimentId) => from<SensitivityData>(handlers.sensitivity(experimentId)),
    uncertainty: (experimentId) => from<UncertaintySummary>(handlers.uncertainty(experimentId)),
    globalSensitivity: async (experimentId, options) => {
      const params: Record<string, unknown> = {};
      if (options?.output) params.output = options.output;
      if (options?.factors && options.factors.length > 0) params.factors = options.factors;
      if (options?.sampleCount !== undefined) params.sample_count = options.sampleCount;
      if (options?.seed !== undefined) params.seed = options.seed;
      return (
        await from<{ report: SobolReport }>(handlers.globalSensitivity(experimentId, params))
      ).report;
    },
    identifiability: async (experimentId, options) => {
      const params: Record<string, unknown> = {};
      if (options?.factors && options.factors.length > 0) params.factors = options.factors;
      if (options?.outputs && options.outputs.length > 0) params.outputs = options.outputs;
      if (options?.stepScale !== undefined) params.step_scale = options.stepScale;
      if (options?.seed !== undefined) params.seed = options.seed;
      return (
        await from<{ report: IdentifiabilityReport }>(
          handlers.identifiability(experimentId, params),
        )
      ).report;
    },
    reproduceExperiment: async (experimentId, rtol, atol) =>
      (
        await from<{ report: ReproduceReport }>(
          handlers.reproduceExperiment(experimentId, rtol, atol),
        )
      ).report,
    listProjects: async () =>
      (await from<{ projects: Project[] }>(handlers.listProjects())).projects,
    createProject: async (name, modelId) =>
      (await from<{ project: Project }>(handlers.createProject(name, modelId))).project,
    planExperiment: (modelId, question, context) =>
      from<PlanProposal>(handlers.planExperiment(modelId, question, context)),
    plannerStatus: () => from<PlannerStatus>(handlers.plannerStatus()),
    environment: () => from<EnvironmentData>(handlers.environment()),
    listDatasetSources: async () =>
      (await from<{ sources: DatasetSource[] }>(handlers.listDatasetSources())).sources,
    inspectDataset: async (filename, options) => {
      const params: Record<string, unknown> = { filename };
      if (options?.delimiter) params.delimiter = options.delimiter;
      if (options?.hasHeader !== undefined) params.has_header = options.hasHeader;
      if (options?.missingCodes && options.missingCodes.length > 0) {
        params.missing_codes = options.missingCodes;
      }
      return (await from<{ inspection: CsvInspection }>(handlers.inspectDataset(params))).inspection;
    },
    importDataset: (filename, config: CsvImportConfig, dryRun) =>
      from<DatasetImportResult>(
        handlers.importDataset({ filename, config, dry_run: dryRun ?? false }),
      ),
    listDatasets: async () =>
      (await from<{ datasets: DatasetSummary[] }>(handlers.listDatasets())).datasets,
    describeDataset: (datasetId) =>
      from<DatasetDetail>(handlers.describeDataset(datasetId)),
    verifyDataset: async (datasetId) =>
      (await from<{ verification: DatasetVerification }>(handlers.verifyDataset(datasetId)))
        .verification,
    evaluate: async (experimentId, options) =>
      (
        await from<{ evaluation: EvaluationResult }>(
          handlers.evaluateExperiment(experimentId, {
            run_id: options.runId,
            mapping: options.mapping,
            config: options.config as EvaluationConfig | undefined,
          }),
        )
      ).evaluation,
    calibrate: (experimentId, options) =>
      from<{ calibration: CalibrationResult; ref?: CalibrationRef }>(
        handlers.calibrateExperiment(experimentId, {
          config: options.config as unknown as CalibrationConfig,
          persist: options.persist,
          job_id: options.jobId,
        }),
      ),
    listCalibrations: async () =>
      (await from<{ calibrations: CalibrationRef[] }>(handlers.listCalibrations())).calibrations,
    getCalibration: (calibrationId) =>
      from<{ calibration: CalibrationResult; ref: CalibrationRef }>(
        handlers.getCalibration(calibrationId),
      ),
    runValidation: (experimentId, options) =>
      from<{ validation: ValidationOutcome; ref?: ValidationRef }>(
        handlers.runValidation(experimentId, {
          config: options.config as unknown as ValidationConfig,
          persist: options.persist,
          job_id: options.jobId,
        }),
      ),
    listValidations: async () =>
      (await from<{ validations: ValidationRef[] }>(handlers.listValidations())).validations,
    getValidation: (validationId) =>
      from<{ validation: ValidationOutcome; ref: ValidationRef }>(
        handlers.getValidation(validationId),
      ),
    verifyValidation: async (validationId) =>
      (
        await from<{ verification: ValidationVerification }>(
          handlers.verifyValidation(validationId),
        )
      ).verification,
    checkValidationStaleness: async (validationId) =>
      (
        await from<{ staleness: ValidationStaleness }>(
          handlers.checkValidationStaleness(validationId),
        )
      ).staleness,
  };
}
