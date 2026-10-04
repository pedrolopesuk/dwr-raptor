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
  EnvironmentData,
  EvidenceData,
  ExperimentData,
  ExperimentSummary,
  ExperimentSpec,
  JobStatus,
  ModelCapabilities,
  ModelSchema,
  ModelSummary,
  PlanProposal,
  PlannerStatus,
  Project,
  SensitivityData,
  ValidationResult,
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
    listProjects: async () =>
      (await from<{ projects: Project[] }>(handlers.listProjects())).projects,
    createProject: async (name, modelId) =>
      (await from<{ project: Project }>(handlers.createProject(name, modelId))).project,
    planExperiment: (modelId, question, context) =>
      from<PlanProposal>(handlers.planExperiment(modelId, question, context)),
    plannerStatus: () => from<PlannerStatus>(handlers.plannerStatus()),
    environment: () => from<EnvironmentData>(handlers.environment()),
  };
}
