"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";

import { useRouter } from "next/navigation";

import { ApiError, createFetchClient, type DrwClient } from "@/lib/client";
import {
  buildSpec,
  factorDraftsFromSpec,
  parseDraftFactors,
  runIssues,
  statusFromResult,
  type BaselineValue,
  type FactorDraft,
  type UiStatus,
} from "@/lib/experiment";
import { DRAFT_ID, paths } from "@/lib/routes";
import type {
  DatasetSummary,
  Diagnostic,
  EnvironmentData,
  ExperimentData,
  ExperimentSpec,
  ExperimentSummary,
  JobStatus,
  ModelCapabilities,
  ModelSchema,
  ModelSummary,
  PlanProposal,
  PlannerStatus,
  Project,
  SensitivityData,
  ValidationResult,
} from "@/lib/types";

export type SiMessage =
  | { id: number; role: "user"; text: string }
  | { id: number; role: "si"; kind: "plan"; modelId: string; proposal: PlanProposal }
  | { id: number; role: "si"; kind: "error"; text: string; questions: string[] };

type CarbonTheme = "g10" | "g100";
const THEME_STORAGE_KEY = "drw-theme";

function newJobId(): string {
  const bytes = new Uint8Array(8);
  if (typeof crypto !== "undefined" && typeof crypto.getRandomValues === "function") {
    crypto.getRandomValues(bytes);
  } else {
    for (let index = 0; index < bytes.length; index += 1) {
      bytes[index] = Math.floor(Math.random() * 256);
    }
  }
  return "job-" + Array.from(bytes).map((b) => b.toString(16).padStart(2, "0")).join("");
}

export interface Workspace {
  api: DrwClient;
  projectId: string;
  theme: CarbonTheme;
  toggleTheme: () => void;

  projects: Project[];
  projectsLoaded: boolean;
  models: ModelSummary[];
  capabilitiesById: Record<string, ModelCapabilities>;
  selectedModelId: string;
  setSelectedModelId: (modelId: string) => void;
  experiments: ExperimentSummary[];
  listLoading: boolean;
  datasets: DatasetSummary[];
  datasetsRefresh: number;
  bumpDatasets: () => void;
  environment: EnvironmentData | null;

  /** The investigation currently loaded: a stored experiment id, DRAFT_ID, or null. */
  activeId: string | null;
  hasDraft: boolean;
  schema: ModelSchema | null;
  modelHash: string | null;
  spec: ExperimentSpec | null;
  seededModelId: string | null;
  reopened: boolean;
  startingExperiment: boolean;
  loadingInvestigation: boolean;

  hypothesis: string;
  setHypothesis: (value: string) => void;
  baseline: Record<string, BaselineValue>;
  setBaselineValue: (name: string, value: BaselineValue) => void;
  factors: FactorDraft[];
  setFactors: (factors: FactorDraft[]) => void;
  timeoutS: number;
  setTimeoutS: (value: number) => void;
  parsedFactorErrors: string[];
  canValidate: boolean;
  canRun: boolean;

  validation: ValidationResult | null;
  status: UiStatus;
  detail: string | null;
  progress: { completed: number; total: number } | null;
  errorMessage: string | null;
  errorDiagnostics: Diagnostic[];
  clearError: () => void;

  result: ExperimentData | null;
  sensitivity: SensitivityData | null;
  sensitivityError: string | null;
  exporting: boolean;
  exportMessage: string | null;

  startInvestigation: (modelId: string) => Promise<void>;
  openSample: () => Promise<void>;
  openInvestigation: (experimentId: string) => Promise<void>;
  validate: () => Promise<void>;
  run: () => Promise<void>;
  cancel: () => void;
  exportEvidence: () => Promise<void>;
  createProject: (name: string) => Promise<void>;
  selectProject: (projectId: string) => void;
  reviewProposal: (spec: ExperimentSpec, modelId: string) => Promise<void>;
  runProposal: (spec: ExperimentSpec, modelId: string) => Promise<void>;

  plannerNote: PlannerStatus | null;
  conversation: (investigationId: string) => { messages: SiMessage[]; busy: boolean };
  ask: (investigationId: string, question: string, modelId: string) => Promise<void>;
}

const Ctx = createContext<Workspace | null>(null);

export function useWorkspace(): Workspace {
  const value = useContext(Ctx);
  if (!value) throw new Error("useWorkspace must be used inside WorkspaceProvider");
  return value;
}

export function WorkspaceProvider({
  client,
  projectId,
  children,
}: {
  client?: DrwClient;
  projectId: string;
  children: ReactNode;
}) {
  const router = useRouter();
  const fallback = useMemo(() => createFetchClient(), []);
  const api = client ?? fallback;

  const [theme, setTheme] = useState<CarbonTheme>("g10");
  const [models, setModels] = useState<ModelSummary[]>([]);
  const [capabilitiesById, setCapabilitiesById] = useState<Record<string, ModelCapabilities>>({});
  const [selectedModelId, setSelectedModelId] = useState("");
  const [startingExperiment, setStartingExperiment] = useState(false);
  const [loadingInvestigation, setLoadingInvestigation] = useState(false);
  const [projects, setProjects] = useState<Project[]>([]);
  const [projectsLoaded, setProjectsLoaded] = useState(false);
  const [experiments, setExperiments] = useState<ExperimentSummary[]>([]);
  const [listLoading, setListLoading] = useState(true);
  const [datasets, setDatasets] = useState<DatasetSummary[]>([]);

  const [schema, setSchema] = useState<ModelSchema | null>(null);
  const [modelHash, setModelHash] = useState<string | null>(null);
  const [baseSpec, setBaseSpec] = useState<ExperimentSpec | null>(null);

  const [hypothesis, setHypothesis] = useState("");
  const [baseline, setBaseline] = useState<Record<string, BaselineValue>>({});
  const [factors, setFactors] = useState<FactorDraft[]>([]);
  const [timeoutS, setTimeoutS] = useState(60);

  const [validation, setValidation] = useState<ValidationResult | null>(null);
  const [status, setStatus] = useState<UiStatus>("idle");
  const [detail, setDetail] = useState<string | null>(null);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [errorDiagnostics, setErrorDiagnostics] = useState<Diagnostic[]>([]);

  const [result, setResult] = useState<ExperimentData | null>(null);
  const [sensitivity, setSensitivity] = useState<SensitivityData | null>(null);
  const [sensitivityError, setSensitivityError] = useState<string | null>(null);
  const [environment, setEnvironment] = useState<EnvironmentData | null>(null);
  const [jobStatus, setJobStatus] = useState<JobStatus | null>(null);
  const [exporting, setExporting] = useState(false);
  const [exportMessage, setExportMessage] = useState<string | null>(null);

  const [activeId, setActiveId] = useState<string | null>(null);
  const [reopened, setReopened] = useState(false);
  const [seededModelId, setSeededModelId] = useState<string | null>(null);
  const [datasetsRefresh, setDatasetsRefresh] = useState(0);
  const abortRef = useRef<AbortController | null>(null);

  const [plannerNote, setPlannerNote] = useState<PlannerStatus | null>(null);
  const [threads, setThreads] = useState<Record<string, SiMessage[]>>({});
  const [busyThreads, setBusyThreads] = useState<Record<string, boolean>>({});
  const nextMessageId = useRef(1);

  // Restore the saved theme after mount (avoids a hydration mismatch).
  useEffect(() => {
    try {
      const saved = window.localStorage.getItem(THEME_STORAGE_KEY);
      if (saved === "g10" || saved === "g100") setTheme(saved);
    } catch {
      /* storage unavailable */
    }
  }, []);

  const toggleTheme = useCallback(() => {
    setTheme((current) => {
      const next: CarbonTheme = current === "g10" ? "g100" : "g10";
      try {
        window.localStorage.setItem(THEME_STORAGE_KEY, next);
      } catch {
        /* storage unavailable */
      }
      return next;
    });
  }, []);

  const parsedFactors = useMemo(() => parseDraftFactors(factors), [factors]);
  const spec = useMemo(
    () =>
      baseSpec
        ? buildSpec(baseSpec, { hypothesis, baseline, factors: parsedFactors.factors, timeoutS })
        : null,
    [baseSpec, hypothesis, baseline, parsedFactors.factors, timeoutS],
  );
  const canValidate = Boolean(spec) && parsedFactors.errors.length === 0;
  const canRun =
    Boolean(validation?.ok) && parsedFactors.errors.length === 0 && status !== "running";

  const refreshExperiments = useCallback(
    async (pid: string) => {
      try {
        setExperiments(await api.listExperiments(pid));
      } catch {
        setExperiments([]);
      } finally {
        setListLoading(false);
      }
    },
    [api],
  );

  const loadEnvironment = useCallback(async () => {
    try {
      setEnvironment(await api.environment());
    } catch {
      setEnvironment(null);
    }
  }, [api]);

  useEffect(() => {
    void (async () => {
      try {
        const list = await api.listModels();
        setModels(list);
        setSelectedModelId((current) => current || list[0]?.model_id || "");
        const entries = await Promise.all(
          list.map(async (model) => {
            try {
              return [model.model_id, await api.capabilities(model.model_id)] as const;
            } catch {
              return [model.model_id, null] as const;
            }
          }),
        );
        const byId: Record<string, ModelCapabilities> = {};
        for (const [modelId, caps] of entries) {
          if (caps) byId[modelId] = caps;
        }
        setCapabilitiesById(byId);
      } catch {
        setModels([]);
      }
      try {
        setProjects(await api.listProjects());
      } catch {
        setProjects([]);
      } finally {
        setProjectsLoaded(true);
      }
      try {
        setPlannerNote(await api.plannerStatus());
      } catch {
        setPlannerNote(null);
      }
      await loadEnvironment();
    })();
  }, [api, loadEnvironment]);

  useEffect(() => {
    setListLoading(true);
    void refreshExperiments(projectId);
  }, [projectId, refreshExperiments]);

  useEffect(() => {
    void (async () => {
      try {
        setDatasets(await api.listDatasets());
      } catch {
        setDatasets([]);
      }
    })();
  }, [api, datasetsRefresh]);

  const applySpec = useCallback((next: ExperimentSpec, nextSchema: ModelSchema, hash: string) => {
    setBaseSpec(next);
    setHypothesis(next.hypothesis);
    setBaseline({ ...(next.baseline as Record<string, BaselineValue>) });
    setFactors(factorDraftsFromSpec(next));
    setTimeoutS(next.execution?.timeout_s ?? 60);
    setSchema(nextSchema);
    setModelHash(hash);
    setValidation(null);
  }, []);

  const describeError = useCallback((error: unknown): void => {
    if (error instanceof ApiError) {
      setErrorMessage(error.message);
      setErrorDiagnostics(
        (error.diagnostics as Diagnostic[]).filter(
          (d) => d && typeof d === "object" && "message" in d,
        ),
      );
    } else {
      setErrorMessage(error instanceof Error ? error.message : String(error));
      setErrorDiagnostics([]);
    }
  }, []);

  const clearError = useCallback(() => {
    setErrorMessage(null);
    setErrorDiagnostics([]);
  }, []);

  const resetOutcome = useCallback(() => {
    setResult(null);
    setSensitivity(null);
    setSensitivityError(null);
    setExportMessage(null);
  }, []);

  const openDraft = useCallback(
    (next: ExperimentSpec, nextSchema: ModelSchema, hash: string, seeded: string | null) => {
      applySpec(next, nextSchema, hash);
      setSeededModelId(seeded);
      resetOutcome();
      setActiveId(DRAFT_ID);
      setReopened(false);
      setStatus("idle");
    },
    [applySpec, resetOutcome],
  );

  const startInvestigation = useCallback(
    async (modelId: string): Promise<void> => {
      clearError();
      setDetail(null);
      setStartingExperiment(true);
      try {
        const [sample, described] = await Promise.all([
          api.sampleExperiment(modelId),
          api.describeModel(modelId),
        ]);
        openDraft(sample, described.schema, described.model_hash, modelId);
        setSelectedModelId(modelId);
        router.push(paths.investigation(projectId, DRAFT_ID, "overview"));
      } catch (error) {
        describeError(error);
      } finally {
        setStartingExperiment(false);
      }
    },
    [api, clearError, describeError, openDraft, projectId, router],
  );

  const openSample = useCallback(() => startInvestigation("predator-prey"), [startInvestigation]);

  const loadSensitivity = useCallback(
    async (experimentId: string): Promise<void> => {
      setSensitivity(null);
      setSensitivityError(null);
      try {
        setSensitivity(await api.sensitivity(experimentId));
      } catch (error) {
        setSensitivityError(error instanceof Error ? error.message : String(error));
      }
    },
    [api],
  );

  /** Loads a stored experiment as the active investigation. Does not navigate. */
  const openInvestigation = useCallback(
    async (experimentId: string): Promise<void> => {
      clearError();
      setLoadingInvestigation(true);
      try {
        const loaded = await api.getExperiment(experimentId);
        const described = await api.describeModel(loaded.spec.model_ref.model_id);
        applySpec(loaded.spec, described.schema, described.model_hash);
        setResult(loaded.results);
        setStatus(statusFromResult(loaded.results));
        setActiveId(experimentId);
        setReopened(true);
        setSeededModelId(null);
        setDetail("reopened from saved experiment - the stored configuration is unchanged");
        void loadSensitivity(experimentId);
        void (async () => {
          try {
            const evidence = await api.evidence(experimentId);
            setResult((current) =>
              current && current.experiment_id === experimentId ? { ...current, evidence } : current,
            );
          } catch {
            /* evidence is optional for display */
          }
        })();
      } catch (error) {
        describeError(error);
        setActiveId(null);
      } finally {
        setLoadingInvestigation(false);
      }
    },
    [api, applySpec, clearError, describeError, loadSensitivity],
  );

  const validate = useCallback(async (): Promise<void> => {
    if (!spec) return;
    clearError();
    setStatus("validating");
    try {
      const outcome = await api.validate(spec);
      setValidation(outcome);
      setStatus("idle");
      setDetail(null);
    } catch (error) {
      describeError(error);
      setValidation(null);
      setStatus("idle");
    }
  }, [api, clearError, describeError, spec]);

  const performRun = useCallback(
    async (runSpec: ExperimentSpec): Promise<void> => {
      const controller = new AbortController();
      abortRef.current = controller;
      const jobId = newJobId();
      setJobStatus(null);
      setStatus("running");
      setDetail("starting...");
      clearError();
      resetOutcome();

      const timer = window.setInterval(() => {
        void (async () => {
          try {
            setJobStatus(await api.jobStatus(jobId));
          } catch {
            /* progress is best-effort; the run request is authoritative */
          }
        })();
      }, 700);

      try {
        const data = await api.run(runSpec, { signal: controller.signal, projectId, jobId });
        const derived = statusFromResult(data);
        setResult(data);
        setStatus(derived);
        setActiveId(data.experiment_id);
        setReopened(false);
        const failed = data.runs.filter((record) => record.status !== "succeeded");
        setDetail(
          derived === "succeeded"
            ? `${data.comparisons.length} comparison(s) from ${data.runs.length} run(s)`
            : failed.flatMap((record) => runIssues(record)).join("; ") || "run incomplete",
        );
        // The investigation now has a stored identity; carry its SI thread across.
        setThreads((current) => {
          const draft = current[DRAFT_ID];
          if (!draft) return current;
          const { [DRAFT_ID]: _moved, ...rest } = current;
          return { ...rest, [data.experiment_id]: [...(rest[data.experiment_id] ?? []), ...draft] };
        });
        router.replace(paths.investigation(projectId, data.experiment_id, "experiments"));
        await refreshExperiments(projectId);
        await loadEnvironment();
        void loadSensitivity(data.experiment_id);
      } catch (error) {
        if (error instanceof ApiError && error.code === "cancelled") {
          setStatus("cancelled");
          setDetail("stopped by the researcher");
        } else {
          describeError(error);
          setStatus("failed");
          setDetail(error instanceof Error ? error.message : "run failed");
        }
      } finally {
        window.clearInterval(timer);
        abortRef.current = null;
      }
    },
    [
      api,
      clearError,
      describeError,
      loadEnvironment,
      loadSensitivity,
      projectId,
      refreshExperiments,
      resetOutcome,
      router,
    ],
  );

  const run = useCallback(async (): Promise<void> => {
    if (!spec || !validation?.ok) return;
    await performRun(spec);
  }, [performRun, spec, validation]);

  /** Stages an SI proposal into Manual, validates it, and runs it only if valid. */
  const runProposal = useCallback(
    async (next: ExperimentSpec, modelId: string): Promise<void> => {
      clearError();
      try {
        const described = await api.describeModel(modelId);
        openDraft(next, described.schema, described.model_hash, null);
        setSelectedModelId(modelId);
        const outcome = await api.validate(next);
        setValidation(outcome);
        if (!outcome.ok) {
          setDetail(
            "SI proposal loaded into Manual; the engine found problems - correct them before running",
          );
          router.push(paths.investigation(projectId, DRAFT_ID, "experiments/configure"));
          return;
        }
        await performRun(next);
      } catch (error) {
        describeError(error);
        setStatus("failed");
      }
    },
    [api, clearError, describeError, openDraft, performRun, projectId, router],
  );

  const cancel = useCallback(() => abortRef.current?.abort(), []);

  const createProject = useCallback(
    async (name: string): Promise<void> => {
      try {
        const project = await api.createProject(name, schema?.model_id);
        setProjects((current) => [...current, project]);
        router.push(paths.project(project.project_id));
      } catch (error) {
        describeError(error);
      }
    },
    [api, describeError, router, schema?.model_id],
  );

  const selectProject = useCallback(
    (next: string) => {
      if (next !== projectId) router.push(paths.project(next));
    },
    [projectId, router],
  );

  /** Loads an SI proposal as a draft investigation. Nothing runs. */
  const reviewProposal = useCallback(
    async (next: ExperimentSpec, modelId: string): Promise<void> => {
      clearError();
      try {
        const described = await api.describeModel(modelId);
        openDraft(next, described.schema, described.model_hash, null);
        setSelectedModelId(modelId);
        setDetail("SI proposal loaded into Manual; validate and run when ready");
        router.push(paths.investigation(projectId, DRAFT_ID, "experiments/configure"));
      } catch (error) {
        describeError(error);
      }
    },
    [api, clearError, describeError, openDraft, projectId, router],
  );

  const exportEvidence = useCallback(async (): Promise<void> => {
    if (!activeId || activeId === DRAFT_ID) return;
    setExporting(true);
    setExportMessage(null);
    try {
      const exported = await api.exportEvidence(activeId);
      setExportMessage(`wrote ${exported.zip}`);
    } catch (error) {
      setExportMessage(error instanceof Error ? `export failed: ${error.message}` : "export failed");
    } finally {
      setExporting(false);
    }
  }, [activeId, api]);

  const ask = useCallback(
    async (investigationId: string, question: string, modelId: string): Promise<void> => {
      const userId = nextMessageId.current++;
      setThreads((current) => ({
        ...current,
        [investigationId]: [
          ...(current[investigationId] ?? []),
          { id: userId, role: "user", text: question },
        ],
      }));
      setBusyThreads((current) => ({ ...current, [investigationId]: true }));
      const push = (message: SiMessage) =>
        setThreads((current) => ({
          ...current,
          [investigationId]: [...(current[investigationId] ?? []), message],
        }));
      try {
        const proposal = await api.planExperiment(modelId, question);
        push({ id: nextMessageId.current++, role: "si", kind: "plan", modelId, proposal });
      } catch (caught) {
        let text = caught instanceof Error ? caught.message : String(caught);
        let questions: string[] = [];
        if (caught instanceof ApiError) {
          text = caught.message;
          const first = (caught.diagnostics as { questions?: string[] }[])[0];
          if (first && Array.isArray(first.questions)) questions = first.questions;
        }
        push({ id: nextMessageId.current++, role: "si", kind: "error", text, questions });
      } finally {
        setBusyThreads((current) => ({ ...current, [investigationId]: false }));
      }
    },
    [api],
  );

  const conversation = useCallback(
    (investigationId: string) => ({
      messages: threads[investigationId] ?? [],
      busy: busyThreads[investigationId] ?? false,
    }),
    [threads, busyThreads],
  );

  const progress =
    status === "running" && jobStatus && jobStatus.total_runs !== null
      ? { completed: jobStatus.completed_runs, total: jobStatus.total_runs }
      : null;

  const value: Workspace = {
    api,
    projectId,
    theme,
    toggleTheme,
    projects,
    projectsLoaded,
    models,
    capabilitiesById,
    selectedModelId,
    setSelectedModelId,
    experiments,
    listLoading,
    datasets,
    datasetsRefresh,
    bumpDatasets: () => setDatasetsRefresh((current) => current + 1),
    environment,
    activeId,
    hasDraft: activeId === DRAFT_ID,
    schema,
    modelHash,
    spec,
    seededModelId,
    reopened,
    startingExperiment,
    loadingInvestigation,
    hypothesis,
    setHypothesis,
    baseline,
    setBaselineValue: (name, next) => setBaseline((current) => ({ ...current, [name]: next })),
    factors,
    setFactors,
    timeoutS,
    setTimeoutS,
    parsedFactorErrors: parsedFactors.errors,
    canValidate,
    canRun,
    validation,
    status,
    detail,
    progress,
    errorMessage,
    errorDiagnostics,
    clearError,
    result,
    sensitivity,
    sensitivityError,
    exporting,
    exportMessage,
    startInvestigation,
    openSample,
    openInvestigation,
    validate,
    run,
    cancel,
    exportEvidence,
    createProject,
    selectProject,
    reviewProposal,
    runProposal,
    plannerNote,
    conversation,
    ask,
  };

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}
