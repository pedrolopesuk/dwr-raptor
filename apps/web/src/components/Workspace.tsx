"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { ArrowRight, Asleep, Light } from "@carbon/icons-react";
import {
  Button,
  Header,
  HeaderGlobalAction,
  HeaderGlobalBar,
  HeaderName,
  InlineNotification,
  Theme,
} from "@carbon/react";

import { Diagnostics } from "@/components/Diagnostics";
import { ExperimentEditor } from "@/components/ExperimentEditor";
import { ExperimentsSidebar } from "@/components/ExperimentsSidebar";
import { ModelPanel } from "@/components/ModelPanel";
import { PlannerPanel } from "@/components/PlannerPanel";
import { ResultsView } from "@/components/ResultsView";
import { ReviewPanel } from "@/components/ReviewPanel";
import { Section } from "@/components/Section";
import { StatusBanner } from "@/components/StatusBanner";
import { ValidationPanel } from "@/components/ValidationPanel";
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
import type {
  Diagnostic,
  EnvironmentData,
  ExperimentData,
  ExperimentSpec,
  ExperimentSummary,
  JobStatus,
  ModelCapabilities,
  ModelSchema,
  ModelSummary,
  Project,
  SensitivityData,
  ValidationResult,
} from "@/lib/types";

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

export function Workspace({ client }: { client?: DrwClient }) {
  const fallback = useMemo(() => createFetchClient(), []);
  const api = client ?? fallback;

  const [theme, setTheme] = useState<CarbonTheme>("g10");
  const [models, setModels] = useState<ModelSummary[]>([]);
  const [capabilitiesById, setCapabilitiesById] = useState<Record<string, ModelCapabilities>>({});
  const [selectedModelId, setSelectedModelId] = useState("");
  const [startingExperiment, setStartingExperiment] = useState(false);
  const [projects, setProjects] = useState<Project[]>([]);
  const [projectId, setProjectId] = useState<string | null>(null);
  const [experiments, setExperiments] = useState<ExperimentSummary[]>([]);
  const [listLoading, setListLoading] = useState(true);

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
  const abortRef = useRef<AbortController | null>(null);

  // Restore the saved theme after mount (avoids a hydration mismatch).
  useEffect(() => {
    try {
      const saved = window.localStorage.getItem(THEME_STORAGE_KEY);
      if (saved === "g10" || saved === "g100") setTheme(saved);
    } catch {
      /* storage unavailable */
    }
  }, []);

  function toggleTheme(): void {
    setTheme((current) => {
      const next: CarbonTheme = current === "g10" ? "g100" : "g10";
      try {
        window.localStorage.setItem(THEME_STORAGE_KEY, next);
      } catch {
        /* storage unavailable */
      }
      return next;
    });
  }

  const parsedFactors = useMemo(() => parseDraftFactors(factors), [factors]);
  const spec = useMemo(
    () =>
      baseSpec
        ? buildSpec(baseSpec, { hypothesis, baseline, factors: parsedFactors.factors, timeoutS })
        : null,
    [baseSpec, hypothesis, baseline, parsedFactors.factors, timeoutS],
  );
  const canValidate = Boolean(spec) && parsedFactors.errors.length === 0;
  const canRun = Boolean(validation?.ok) && parsedFactors.errors.length === 0 && status !== "running";

  const refreshExperiments = useCallback(
    async (pid?: string) => {
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
        const list = await api.listProjects();
        setProjects(list);
        const first = list[0];
        if (first) setProjectId(first.project_id);
      } catch {
        setProjects([]);
      }
      await loadEnvironment();
    })();
  }, [api, loadEnvironment]);

  useEffect(() => {
    if (!projectId) return;
    void refreshExperiments(projectId);
  }, [projectId, refreshExperiments]);

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

  async function openModel(modelId: string): Promise<void> {
    setErrorMessage(null);
    setErrorDiagnostics([]);
    setDetail(null);
    setStartingExperiment(true);
    try {
      const [sample, described] = await Promise.all([
        api.sampleExperiment(modelId),
        api.describeModel(modelId),
      ]);
      applySpec(sample, described.schema, described.model_hash);
      setSelectedModelId(modelId);
      setSeededModelId(modelId);
      setResult(null);
      setSensitivity(null);
      setSensitivityError(null);
      setActiveId(null);
      setReopened(false);
      setStatus("idle");
    } catch (error) {
      describeError(error);
    } finally {
      setStartingExperiment(false);
    }
  }

  async function openSample(): Promise<void> {
    await openModel("predator-prey");
  }

  async function openExperiment(experimentId: string): Promise<void> {
    setErrorMessage(null);
    setErrorDiagnostics([]);
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
      if (loaded.meta.project_id) setProjectId(loaded.meta.project_id);
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
    }
  }

  async function validate(): Promise<void> {
    if (!spec) return;
    setErrorMessage(null);
    setErrorDiagnostics([]);
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
  }

  async function loadSensitivity(experimentId: string): Promise<void> {
    setSensitivity(null);
    setSensitivityError(null);
    try {
      setSensitivity(await api.sensitivity(experimentId));
    } catch (error) {
      setSensitivityError(error instanceof Error ? error.message : String(error));
    }
  }

  async function run(): Promise<void> {
    if (!spec || !validation?.ok) return;
    const controller = new AbortController();
    abortRef.current = controller;
    const jobId = newJobId();
    setJobStatus(null);
    setStatus("running");
    setDetail("starting...");
    setErrorMessage(null);
    setErrorDiagnostics([]);
    setResult(null);
    setSensitivity(null);
    setSensitivityError(null);
    setExportMessage(null);

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
      const data = await api.run(spec, {
        signal: controller.signal,
        projectId: projectId ?? undefined,
        jobId,
      });
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
      await refreshExperiments(projectId ?? undefined);
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
  }

  function cancel(): void {
    abortRef.current?.abort();
  }

  async function createProject(name: string): Promise<void> {
    try {
      const project = await api.createProject(name, schema?.model_id);
      setProjects((current) => [...current, project]);
      setProjectId(project.project_id);
      setDetail(`created project ${project.name}`);
    } catch (error) {
      describeError(error);
    }
  }

  function applyProposal(next: ExperimentSpec): void {
    if (!schema) return;
    applySpec(next, schema, modelHash ?? "");
    setSeededModelId(null);
    setResult(null);
    setSensitivity(null);
    setSensitivityError(null);
    setStatus("idle");
    setDetail("proposal applied to the editor; validate and run when ready");
  }

  async function exportEvidence(): Promise<void> {
    if (!activeId) return;
    setExporting(true);
    setExportMessage(null);
    try {
      const exported = await api.exportEvidence(activeId);
      setExportMessage(`wrote ${exported.zip}`);
    } catch (error) {
      setExportMessage(
        error instanceof Error ? `export failed: ${error.message}` : "export failed",
      );
    } finally {
      setExporting(false);
    }
  }

  const progress =
    status === "running" && jobStatus && jobStatus.total_runs !== null
      ? { completed: jobStatus.completed_runs, total: jobStatus.total_runs }
      : null;

  const projectName = projectId
    ? (projects.find((p) => p.project_id === projectId)?.name ?? projectId)
    : "loading projects…";

  return (
    <Theme theme={theme} className="drw-app">
      <a className="cds--skip-to-content" href="#main-content">
        Skip to main content
      </a>
      <Header aria-label="Differential Research Workbench">
        <HeaderName href="#" prefix="DRW">
          Workbench
        </HeaderName>
        <HeaderGlobalBar>
          <HeaderGlobalAction
            aria-label={theme === "g10" ? "Switch to dark theme" : "Switch to light theme"}
            onClick={toggleTheme}
            tooltipAlignment="end"
          >
            {theme === "g10" ? <Asleep size={20} /> : <Light size={20} />}
          </HeaderGlobalAction>
        </HeaderGlobalBar>
      </Header>

      <div className="drw-shell">
        <ExperimentsSidebar
          experiments={experiments}
          projects={projects}
          models={models}
          modelCapabilities={capabilitiesById}
          selectedModelId={selectedModelId}
          activeProjectId={projectId}
          activeId={activeId}
          startingExperiment={startingExperiment}
          onOpen={(id) => void openExperiment(id)}
          onOpenSample={() => void openSample()}
          onSelectModel={setSelectedModelId}
          onStartExperiment={(modelId) => void openModel(modelId)}
          onSelectProject={setProjectId}
          onCreateProject={(name) => void createProject(name)}
          loading={listLoading}
        />

        <main id="main-content" className="drw-main" tabIndex={-1}>
          <div className="drw-page drw-stack">
            <div className="drw-page-header">
              <h1 className="drw-page-title">Researcher workspace</h1>
              <p className="drw-page-subtitle" data-testid="workspace-context">
                {models.length} registered model(s) · {projectName}
              </p>
            </div>

            <StatusBanner status={status} detail={detail} progress={progress} />

            {errorMessage ? (
              <section aria-labelledby="error-heading" className="drw-stack-tight">
                <h2 id="error-heading" className="drw-subheading">
                  Error
                </h2>
                <div data-testid="error-message">
                  <InlineNotification
                    kind="error"
                    lowContrast
                    hideCloseButton
                    title="Request failed"
                    subtitle={errorMessage}
                  />
                </div>
                {errorDiagnostics.length > 0 ? (
                  <Diagnostics diagnostics={errorDiagnostics} />
                ) : null}
              </section>
            ) : null}

            {!schema || !spec ? (
              <Section
                id="start-heading"
                title="Start here"
                description="Choose any registered model in the sidebar to create a new experiment, or open the sample project to load the predator-prey model and a baseline-vs-intervention configuration."
              >
                <div className="drw-stack-tight">
                  <div>
                    <Button
                      renderIcon={ArrowRight}
                      onClick={() => void openSample()}
                      data-testid="start-sample"
                    >
                      Open sample project (predator-prey)
                    </Button>
                  </div>
                  <p className="drw-hint">
                    A new experiment starts from a demonstration configuration (+10% on the model's
                    first input). It is a starting point to review and adjust, not a validated
                    experiment.
                  </p>
                </div>
              </Section>
            ) : (
              <>
                {seededModelId ? (
                  <div data-testid="demo-seed-note">
                    <InlineNotification
                      kind="info"
                      lowContrast
                      hideCloseButton
                      title="Demonstration configuration"
                      subtitle={`Started from ${seededModelId}: a +10% intervention on the model's first input. This is a demonstration, not a scientifically justified experiment - review the hypothesis, baseline and intervention before validating.`}
                    />
                  </div>
                ) : null}

                <ModelPanel
                  schema={schema}
                  modelHash={modelHash}
                  capabilities={capabilitiesById[schema.model_id] ?? null}
                />

                <div className="drw-split">
                  <ExperimentEditor
                    schema={schema}
                    hypothesis={hypothesis}
                    onHypothesisChange={setHypothesis}
                    baseline={baseline}
                    onBaselineChange={(name, value) =>
                      setBaseline((current) => ({ ...current, [name]: value }))
                    }
                    factors={factors}
                    onFactorsChange={setFactors}
                  />
                  <div className="drw-stack">
                    <ValidationPanel
                      validation={validation}
                      clientErrors={parsedFactors.errors}
                      validating={status === "validating"}
                      onValidate={() => void validate()}
                      canValidate={canValidate}
                    />
                    <ReviewPanel
                      spec={spec}
                      estimate={validation?.estimate ?? null}
                      clientErrors={parsedFactors.errors}
                      canRun={canRun}
                      running={status === "running"}
                      timeoutS={timeoutS}
                      onTimeoutChange={setTimeoutS}
                      onRun={() => void run()}
                      onCancel={cancel}
                    />
                  </div>
                </div>

                <PlannerPanel client={api} modelId={schema.model_id} onApply={applyProposal} />

                {reopened ? (
                  <div data-testid="reopened-note">
                    <InlineNotification
                      kind="info"
                      lowContrast
                      hideCloseButton
                      title="Reopened from a saved experiment"
                      subtitle="Editing and running creates a new record; the saved configuration is not modified."
                    />
                  </div>
                ) : null}

                {result ? (
                  <ResultsView
                    data={result}
                    sensitivity={sensitivity}
                    sensitivityError={sensitivityError}
                    environment={environment}
                    onExport={() => void exportEvidence()}
                    exporting={exporting}
                    exportMessage={exportMessage}
                  />
                ) : null}
              </>
            )}
          </div>
        </main>
      </div>
    </Theme>
  );
}
