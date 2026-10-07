"use client";

import type { ReactNode } from "react";

import { useRouter } from "next/navigation";

import { ArrowRight } from "@carbon/icons-react";
import { Button, InlineNotification, Tab, TabList, TabPanel, TabPanels, Tabs, Tag } from "@carbon/react";

import { CalibrationPanel } from "@/components/CalibrationPanel";
import { EvaluationPanel } from "@/components/EvaluationPanel";
import { ExperimentEditor } from "@/components/ExperimentEditor";
import { GlobalSensitivityPanel } from "@/components/GlobalSensitivityPanel";
import { IdentifiabilityPanel } from "@/components/IdentifiabilityPanel";
import { Page, EmptyState, StateMark, SubNav, type StateKind } from "@/components/page/Page";
import { ScientificStatus } from "@/components/page/ScientificStatus";
import { ReproducePanel } from "@/components/ReproducePanel";
import { ResultsView } from "@/components/ResultsView";
import { ReviewPanel } from "@/components/ReviewPanel";
import { Section } from "@/components/Section";
import { NavLink } from "@/components/shell/NavLink";
import { InvestigationSi } from "@/components/si/SiView";
import { StatusBanner } from "@/components/StatusBanner";
import { ValidationPanel } from "@/components/ValidationPanel";
import { ValidationRunPanel } from "@/components/ValidationRunPanel";
import { useWorkspace } from "@/components/workspace/WorkspaceProvider";
import { formatDuration, formatScalar, shortHash } from "@/lib/format";
import { formatWhen } from "@/lib/investigation";
import { DRAFT_ID, paths, useRoute } from "@/lib/routes";

function useInvestigation() {
  const ws = useWorkspace();
  const route = useRoute();
  const router = useRouter();
  const id = route.investigationId ?? DRAFT_ID;
  const href = (rest = "") => paths.investigation(ws.projectId, id, rest);
  const stored = id !== DRAFT_ID && ws.activeId === id;
  return { ws, route, router, id, href, stored, isDraft: id === DRAFT_ID };
}

/* ------------------------------------------------------------------------- SI */

export function InvestigationSiView() {
  const { id, router, href } = useInvestigation();
  return (
    <InvestigationSi
      investigationId={id}
      onAttach={() => router.push(href("data"))}
      onSuggestionNav={() => router.push(href("data"))}
    />
  );
}

/* ------------------------------------------------------------------- overview */

interface StateRow {
  label: string;
  kind: StateKind;
  note: string;
  href?: string;
}

export function InvestigationOverviewView() {
  const { ws, href, isDraft } = useInvestigation();
  const schema = ws.schema;
  const result = ws.result;
  const onDemand = "Computed on demand under Analysis; DRW does not store it.";

  const baselineKind: StateKind = ws.status === "running"
    ? "running"
    : result
      ? ws.status === "succeeded"
        ? "done"
        : "failed"
      : "pending";

  const rows: StateRow[] = [
    {
      label: "Model",
      kind: schema ? "done" : "pending",
      note: schema ? `${schema.model_id} v${schema.version}` : "No model loaded",
      href: href("model"),
    },
    {
      label: "Observations",
      kind: ws.datasets.length > 0 ? "done" : "pending",
      note:
        ws.datasets.length > 0
          ? `${ws.datasets.length} dataset(s) in this workspace (shared; link one under Data)`
          : "No dataset imported",
      href: href("data"),
    },
    {
      label: "Baseline",
      kind: baselineKind,
      note: result
        ? `${result.runs.filter((r) => r.status === "succeeded").length}/${result.runs.length} runs succeeded`
        : isDraft
          ? "Draft: not run"
          : "No result",
      href: href("experiments"),
    },
    {
      label: "Evaluation",
      kind: "pending",
      note: onDemand,
      href: href("analysis/evaluation"),
    },
    {
      label: "Sensitivity (local)",
      kind: ws.sensitivity ? "done" : ws.sensitivityError ? "failed" : "pending",
      note: ws.sensitivity ? "One-at-a-time ranking computed" : (ws.sensitivityError ?? "Needs a stored run"),
      href: href("analysis/sensitivity"),
    },
    {
      label: "Identifiability",
      kind: "pending",
      note: onDemand,
      href: href("analysis/identifiability"),
    },
    {
      label: "Calibration",
      kind: "pending",
      note: onDemand,
      href: href("analysis/calibration"),
    },
    {
      label: "Validation",
      kind: "pending",
      note: "Tests the frozen calibrated model on independent observations (run under Validation)",
      href: href("validation"),
    },
  ];

  const first = result?.runs[0];

  return (
    <Page
      title="Overview"
      purpose="Where we are scientifically."
      testId="investigation-overview"
    >
      <section className="drw-block" aria-labelledby="q-heading">
        <h2 id="q-heading" className="drw-eyebrow">
          Question
        </h2>
        <p className="drw-question" data-testid="investigation-question">
          {ws.hypothesis || "No hypothesis written yet."}
        </p>
        <NavLink href={href("experiments/configure")} className="si-link">
          Edit in Configuration
        </NavLink>
      </section>

      <section className="drw-block" aria-labelledby="state-heading">
        <h2 id="state-heading" className="drw-eyebrow">
          Current scientific state
        </h2>
        <table className="drw-table drw-table--state" data-testid="scientific-state">
          <tbody>
            {rows.map((row) => (
              <tr key={row.label}>
                <th scope="row">{row.label}</th>
                <td>
                  <StateMark kind={row.kind} />
                </td>
                <td className="drw-table__note">{row.note}</td>
                <td>
                  {row.href ? (
                    <NavLink href={row.href} className="si-link">
                      Open
                    </NavLink>
                  ) : null}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>

      <section className="drw-block" aria-labelledby="concl-heading">
        <h2 id="concl-heading" className="drw-eyebrow">
          Current conclusion
        </h2>
        <p className="drw-conclusion" data-testid="investigation-conclusion">
          Not established.
        </p>
        <ScientificStatus level="descriptive">
          DRW does not record conclusions. A conclusion should follow from the evidence, not from
          this page.
        </ScientificStatus>
      </section>

      <section className="drw-block" aria-labelledby="evsum-heading">
        <h2 id="evsum-heading" className="drw-eyebrow">
          Evidence summary
        </h2>
        {result ? (
          <dl className="drw-kv drw-kv--tight">
            <div>
              <dt>Experiment</dt>
              <dd className="drw-mono">{result.experiment_id}</dd>
            </div>
            <div>
              <dt>Runs</dt>
              <dd>
                {result.runs.filter((r) => r.status === "succeeded").length}/{result.runs.length}{" "}
                succeeded
              </dd>
            </div>
            <div>
              <dt>Comparisons</dt>
              <dd>{result.comparisons.length}</dd>
            </div>
            <div>
              <dt>First run</dt>
              <dd>{first ? `${first.label}, ${formatDuration(first.duration_s)}` : "—"}</dd>
            </div>
            <div>
              <dt>Calibration</dt>
              <dd>Computed on demand (not stored)</dd>
            </div>
            <div>
              <dt>Validation</dt>
              <dd>Computed on demand under Validation (not stored in the evidence package)</dd>
            </div>
          </dl>
        ) : (
          <p className="drw-hint">No evidence yet. Run the experiment to produce some.</p>
        )}
      </section>
    </Page>
  );
}

/* ---------------------------------------------------------------------- model */

export function InvestigationModelView() {
  const { ws } = useInvestigation();
  const schema = ws.schema;
  if (!schema) return null;
  const caps = ws.capabilitiesById[schema.model_id];
  const initial = schema.parameters.filter((p) => p.role === "state" || p.role === "control");
  const params = schema.parameters.filter((p) => p.role === "input");

  const paramTable = (items: typeof schema.parameters, label: string) => (
    <table className="drw-table" aria-label={label}>
      <thead>
        <tr>
          <th scope="col">name</th>
          <th scope="col">type</th>
          <th scope="col">role</th>
          <th scope="col">unit</th>
          <th scope="col" className="drw-num">nominal</th>
          <th scope="col" className="drw-num">lower</th>
          <th scope="col" className="drw-num">upper</th>
        </tr>
      </thead>
      <tbody>
        {items.map((param) => (
          <tr key={param.name}>
            <td>
              <span className="drw-mono">{param.name}</span>
              {param.description ? <span className="drw-table__sub">{param.description}</span> : null}
            </td>
            <td>{param.type}</td>
            <td>
              <Tag type={param.role === "state" ? "teal" : "cool-gray"} size="sm">
                {param.role}
              </Tag>
            </td>
            <td>{param.unit}</td>
            <td className="drw-num">{formatScalar(param.nominal)}</td>
            <td className="drw-num">{param.lower === null ? "—" : formatScalar(param.lower)}</td>
            <td className="drw-num">{param.upper === null ? "—" : formatScalar(param.upper)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );

  const panels: ReactNode[] = [
    <div key="overview" className="drw-stack-tight">
      <p>{schema.description}</p>
      <dl className="drw-kv drw-kv--tight">
        <div>
          <dt>Model</dt>
          <dd className="drw-mono">{schema.model_id}</dd>
        </div>
        <div>
          <dt>Version</dt>
          <dd>v{schema.version}</dd>
        </div>
        <div>
          <dt>Runtime</dt>
          <dd>{schema.runtime}</dd>
        </div>
        <div>
          <dt>Model hash</dt>
          <dd className="drw-mono">{shortHash(ws.modelHash)}</dd>
        </div>
      </dl>
      {caps ? (
        <div className="drw-stack-tight">
          <p className="drw-hint">
            Technical eligibility only. It is <strong>not</strong> a claim that any configuration is
            scientifically meaningful.
          </p>
          <dl className="drw-kv">
            <div>
              <dt>Factorable parameters</dt>
              <dd className="drw-mono" data-testid="cap-factorable">
                {caps.factorable_parameters.map((p) => p.name).join(", ") || "none"}
              </dd>
            </div>
            <div>
              <dt>Outputs</dt>
              <dd className="drw-mono" data-testid="cap-outputs">
                {[...caps.timeseries_outputs, ...caps.scalar_outputs].join(", ") || "none"}
              </dd>
            </div>
          </dl>
          {caps.limitations.length > 0 ? (
            <ul className="drw-stack-tight" data-testid="cap-limitations">
              {caps.limitations.map((limitation) => (
                <li key={limitation} className="drw-hint">
                  {limitation}
                </li>
              ))}
            </ul>
          ) : null}
        </div>
      ) : null}
    </div>,
    paramTable(params, "Model parameters"),
    paramTable(initial, "Initial conditions and controls"),
    <table key="outputs" className="drw-table" aria-label="Model outputs">
      <thead>
        <tr>
          <th scope="col">name</th>
          <th scope="col">kind</th>
          <th scope="col">unit</th>
          <th scope="col">description</th>
        </tr>
      </thead>
      <tbody>
        {schema.outputs.map((output) => (
          <tr key={output.name}>
            <td className="drw-mono">{output.name}</td>
            <td>{output.kind}</td>
            <td>{output.unit}</td>
            <td>{output.description || "—"}</td>
          </tr>
        ))}
      </tbody>
    </table>,
    <dl key="execution" className="drw-kv">
      <div>
        <dt>Runtime</dt>
        <dd>{schema.runtime}</dd>
      </div>
      <div>
        <dt>Isolation</dt>
        <dd>{caps?.isolation ?? ws.result?.isolation ?? "—"}</dd>
      </div>
      <div>
        <dt>Timeout per run</dt>
        <dd>{ws.timeoutS} s</dd>
      </div>
      <div>
        <dt>Sampling methods</dt>
        <dd>{caps?.sampling_methods.join(", ") || "—"}</dd>
      </div>
      <div>
        <dt>Analysis methods</dt>
        <dd>{caps?.analysis_methods.join(", ") || "—"}</dd>
      </div>
    </dl>,
    <div key="versions" className="drw-stack-tight">
      <p>
        <span className="drw-mono">{schema.model_id}</span> v{schema.version} ·{" "}
        <span className="drw-mono">{shortHash(ws.modelHash, 16)}</span>
      </p>
      <p className="drw-hint">
        Only the registered version is available. DRW does not keep a version history for models.
      </p>
    </div>,
  ];
  const labels = ["Overview", "Parameters", "Inputs", "Outputs", "Execution", "Versions"];

  return (
    <Page title="Model" purpose="What we are modeling." testId="investigation-model">
      <Tabs>
        <TabList aria-label="Model sections" contained>
          {labels.map((label) => (
            <Tab key={label}>{label}</Tab>
          ))}
        </TabList>
        <TabPanels>
          {labels.map((label, index) => (
            <TabPanel key={label} className="drw-tabpanel">
              {panels[index]}
            </TabPanel>
          ))}
        </TabPanels>
      </Tabs>
    </Page>
  );
}

/* ---------------------------------------------------------------- experiments */

export function InvestigationExperimentsView() {
  const { ws, route, href, id, stored } = useInvestigation();
  const view = route.sub[0] ?? "runs";

  const nav = (
    <SubNav
      label="Experiment sections"
      items={[
        { href: href("experiments"), label: "Runs", current: view === "runs" },
        { href: href("experiments/configure"), label: "Configuration", current: view === "configure" },
        { href: href("experiments/results"), label: "Results", current: view === "results" },
      ]}
    />
  );

  if (view === "configure") {
    return (
      <Page title="Configuration" purpose="Edit, validate and run this experiment." testId="experiment-configure">
        {nav}
        <StatusBanner status={ws.status} detail={ws.detail} progress={ws.progress} />
        {ws.seededModelId ? (
          <div data-testid="demo-seed-note">
            <InlineNotification
              kind="info"
              lowContrast
              hideCloseButton
              title="Demonstration configuration"
              subtitle={`Started from ${ws.seededModelId}: a +10% intervention on the model's first input. This is a demonstration, not a scientifically justified experiment - review the hypothesis, baseline and intervention before validating.`}
            />
          </div>
        ) : null}
        {ws.reopened ? (
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
        {ws.schema && ws.spec ? (
          <div className="drw-split">
            <ExperimentEditor
              schema={ws.schema}
              hypothesis={ws.hypothesis}
              onHypothesisChange={ws.setHypothesis}
              baseline={ws.baseline}
              onBaselineChange={ws.setBaselineValue}
              factors={ws.factors}
              onFactorsChange={ws.setFactors}
            />
            <div className="drw-stack">
              <ValidationPanel
                validation={ws.validation}
                clientErrors={ws.parsedFactorErrors}
                validating={ws.status === "validating"}
                onValidate={() => void ws.validate()}
                canValidate={ws.canValidate}
              />
              <ReviewPanel
                spec={ws.spec}
                estimate={ws.validation?.estimate ?? null}
                clientErrors={ws.parsedFactorErrors}
                canRun={ws.canRun}
                running={ws.status === "running"}
                timeoutS={ws.timeoutS}
                onTimeoutChange={ws.setTimeoutS}
                onRun={() => void ws.run()}
                onCancel={ws.cancel}
              />
            </div>
          </div>
        ) : null}
      </Page>
    );
  }

  if (view === "results") {
    return (
      <Page title="Results" purpose="Outputs and metrics of this experiment." testId="experiment-results">
        {nav}
        <StatusBanner status={ws.status} detail={ws.detail} progress={ws.progress} />
        {ws.result ? (
          <ResultsView
            data={ws.result}
            sensitivity={ws.sensitivity}
            sensitivityError={ws.sensitivityError}
            environment={ws.environment}
            onExport={() => void ws.exportEvidence()}
            exporting={ws.exporting}
            exportMessage={ws.exportMessage}
          />
        ) : (
          <EmptyState title="No results yet" testId="results-empty">
            Validate and run the configuration to produce results.
          </EmptyState>
        )}
      </Page>
    );
  }

  const runs = ws.result?.runs ?? [];
  return (
    <Page
      title="Experiments"
      purpose="What we ran."
      testId="investigation-experiments"
      actions={
        <NavLink href={href("experiments/configure")} className="drw-btnlink">
          Configure and run
        </NavLink>
      }
    >
      {nav}
      <StatusBanner status={ws.status} detail={ws.detail} progress={ws.progress} />
      {runs.length === 0 ? (
        <EmptyState title="Nothing has run yet" testId="runs-empty">
          {id === DRAFT_ID
            ? "This is an unsaved draft. Configure it and run it to store an experiment."
            : "This experiment has no stored runs."}
        </EmptyState>
      ) : (
        <table className="drw-table" data-testid="runs-list">
          <thead>
            <tr>
              <th scope="col">Run</th>
              <th scope="col">Status</th>
              <th scope="col">Duration</th>
              <th scope="col">Inputs</th>
            </tr>
          </thead>
          <tbody>
            {runs.map((run) => (
              <tr key={run.run_id}>
                <td>
                  <span className="drw-table__link">{run.label}</span>
                  <span className="drw-table__sub drw-mono">{run.run_id}</span>
                </td>
                <td>
                  <StateMark kind={run.status === "succeeded" ? "done" : "failed"} /> {run.status}
                </td>
                <td>{formatDuration(run.duration_s)}</td>
                <td className="drw-mono drw-table__note">
                  {Object.entries(run.inputs)
                    .slice(0, 4)
                    .map(([k, v]) => `${k}=${formatScalar(v)}`)
                    .join(", ")}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {stored && ws.result ? (
        <div>
          <NavLink href={href("experiments/results")} className="si-link">
            View results <ArrowRight size={14} />
          </NavLink>
        </div>
      ) : null}
    </Page>
  );
}

/* ------------------------------------------------------------------- analysis */

function NeedsStoredRun({ children }: { children: ReactNode }) {
  const { ws, stored, href } = useInvestigation();
  if (stored && ws.schema) return <>{children}</>;
  return (
    <EmptyState
      title="Run the experiment first"
      testId="needs-run"
      action={
        <NavLink href={href("experiments/configure")} className="si-link">
          Open Configuration
        </NavLink>
      }
    >
      Analyses work on a stored experiment. This investigation is still an unsaved draft.
    </EmptyState>
  );
}

export function InvestigationAnalysisView() {
  const { ws, route, href, id } = useInvestigation();
  const view = route.sub[0];
  const schema = ws.schema;

  const back = (
    <NavLink href={href("analysis")} className="si-link">
      ← Analysis
    </NavLink>
  );

  if (view === "sensitivity") {
    return (
      <Page title="Sensitivity" purpose="What matters." testId="analysis-sensitivity">
        {back}
        <NeedsStoredRun>
          <GlobalSensitivityPanel
            client={ws.api}
            experimentId={id}
            capabilities={schema ? (ws.capabilitiesById[schema.model_id] ?? null) : null}
          />
          <p className="drw-hint">
            The one-at-a-time ranking is part of{" "}
            <NavLink href={href("experiments/results")} className="si-link">
              Results
            </NavLink>
            .
          </p>
        </NeedsStoredRun>
      </Page>
    );
  }
  if (view === "identifiability") {
    return (
      <Page title="Identifiability" purpose="Can parameters be distinguished?" testId="analysis-identifiability">
        {back}
        <NeedsStoredRun>
          <IdentifiabilityPanel
            client={ws.api}
            experimentId={id}
            capabilities={schema ? (ws.capabilitiesById[schema.model_id] ?? null) : null}
          />
        </NeedsStoredRun>
      </Page>
    );
  }
  if (view === "calibration") {
    return (
      <Page title="Calibration" purpose="What parameters best fit the observations?" testId="analysis-calibration">
        {back}
        <NeedsStoredRun>
          {schema ? (
            <CalibrationPanel
              client={ws.api}
              experimentId={id}
              schema={schema}
              refreshToken={ws.datasetsRefresh}
            />
          ) : null}
        </NeedsStoredRun>
      </Page>
    );
  }
  if (view === "evaluation") {
    return (
      <Page title="Evaluation" purpose="How does the model compare with observations?" testId="analysis-evaluation">
        {back}
        <NeedsStoredRun>
          {schema ? (
            <EvaluationPanel
              client={ws.api}
              experimentId={id}
              modelId={schema.model_id}
              refreshToken={ws.datasetsRefresh}
              runs={(ws.result?.runs ?? []).map((record) => ({
                run_id: record.run_id,
                label: record.label,
              }))}
            />
          ) : null}
        </NeedsStoredRun>
      </Page>
    );
  }

  const entries: { key: string; title: string; text: string; state: StateKind; stateNote: string }[] = [
    {
      key: "sensitivity",
      title: "Sensitivity",
      text: "Local one-at-a-time ranking, and Sobol global indices on demand.",
      state: ws.sensitivity ? "done" : "pending",
      stateNote: ws.sensitivity ? "Local ranking computed" : "Not computed",
    },
    {
      key: "identifiability",
      title: "Identifiability",
      text: "Local rank, condition number and poorly distinguishable parameter directions.",
      state: "pending",
      stateNote: "Computed on demand, not stored",
    },
    {
      key: "calibration",
      title: "Calibration",
      text: "Fit bounded parameters to an imported dataset with a chosen objective and optimizer.",
      state: "pending",
      stateNote: "Computed on demand, not stored",
    },
    {
      key: "evaluation",
      title: "Evaluation",
      text: "Compare a stored run with an observation dataset through an explicit mapping.",
      state: "pending",
      stateNote: "Computed on demand, not stored",
    },
  ];

  return (
    <Page title="Analysis" purpose="What the computation tells us." testId="analysis-index">
      <ul className="drw-rows drw-rows--spaced">
        {entries.map((entry) => (
          <li key={entry.key}>
            <NavLink href={href(`analysis/${entry.key}`)} className="drw-row-link drw-row-link--block">
              <span className="drw-row-link__main">{entry.title}</span>
              <span className="drw-row-link__text">{entry.text}</span>
              <span className="drw-row-link__meta">
                <StateMark kind={entry.state} /> {entry.stateNote}
              </span>
            </NavLink>
          </li>
        ))}
      </ul>
    </Page>
  );
}

/* ----------------------------------------------------------------- validation */

export function InvestigationValidationView() {
  const { ws, id, href } = useInvestigation();
  const schema = ws.schema;
  return (
    <Page
      title="Validation"
      purpose="Does it generalize to independent evidence?"
      testId="investigation-validation"
    >
      <NeedsStoredRun>
        {schema ? (
          <ValidationRunPanel
            client={ws.api}
            experimentId={id}
            modelId={schema.model_id}
            refreshToken={ws.datasetsRefresh}
          />
        ) : null}
      </NeedsStoredRun>

      <ScientificStatus level="not_validated" testId="validation-note">
        Validation tests a <strong>frozen</strong> calibrated model against observations that were
        not used to fit it. Agreement, independence and any acceptance criterion are reported
        separately; agreement here does not establish that the model is correct, and an accepted
        threshold is a user decision rule - not scientific truth.
      </ScientificStatus>

      <section className="drw-block">
        <h2 className="drw-eyebrow">What validation is not</h2>
        <ul className="drw-stack-tight">
          <li>Not another calibration: the parameters are frozen and cannot be refit.</li>
          <li>Not model selection, and not proof that the model is true.</li>
          <li>
            Need a calibration first?{" "}
            <NavLink href={href("analysis/calibration")} className="si-link">
              Calibrate
            </NavLink>{" "}
            parameters and persist the result.
          </li>
        </ul>
      </section>
    </Page>
  );
}

/* ------------------------------------------------------------------- evidence */

function Step({
  title,
  state,
  summary,
  children,
  open,
}: {
  title: string;
  state: StateKind;
  summary: string;
  children?: ReactNode;
  open?: boolean;
}) {
  return (
    <li className="drw-chain__step" data-state={state}>
      <details open={open} className="drw-chain__details">
        <summary>
          <StateMark kind={state} />
          <span className="drw-chain__title">{title}</span>
          <span className="drw-chain__summary">{summary}</span>
        </summary>
        {children ? <div className="drw-chain__body">{children}</div> : null}
      </details>
    </li>
  );
}

export function InvestigationEvidenceView() {
  const { ws, id, stored } = useInvestigation();
  const result = ws.result;
  const schema = ws.schema;

  if (!stored || !result) {
    return (
      <Page title="Evidence" purpose="Can we trace and reproduce the conclusion?" testId="investigation-evidence">
        <EmptyState title="No evidence yet" testId="evidence-empty">
          Evidence is recorded when the experiment runs.
        </EmptyState>
      </Page>
    );
  }

  const evidence = result.evidence;
  const envEntries = Object.entries(result.environment ?? {});

  return (
    <Page title="Evidence" purpose="Can we trace and reproduce the conclusion?" testId="investigation-evidence">
      <ol className="drw-chain" data-testid="evidence-chain">
        <Step
          title="Question"
          state={ws.hypothesis ? "done" : "pending"}
          summary={ws.hypothesis || "No hypothesis recorded"}
        >
          <p>{ws.hypothesis}</p>
          <p className="drw-hint">
            DRW stores one hypothesis per experiment; the question and hypothesis are the same text.
          </p>
        </Step>
        <Step
          title="Model"
          state="done"
          summary={`${result.model_ref.model_id} ${result.model_ref.version ? `v${result.model_ref.version}` : ""}`}
        >
          <dl className="drw-kv drw-kv--tight">
            <div>
              <dt>Model</dt>
              <dd className="drw-mono">{result.model_ref.model_id}</dd>
            </div>
            <div>
              <dt>Version</dt>
              <dd>{result.model_ref.version ?? "—"}</dd>
            </div>
            <div>
              <dt>Model hash</dt>
              <dd className="drw-mono" data-testid="model-hash">
                {result.model_hash}
              </dd>
            </div>
            <div>
              <dt>Runtime</dt>
              <dd>{schema?.runtime ?? "—"}</dd>
            </div>
          </dl>
        </Step>
        <Step
          title="Dataset"
          state="pending"
          summary="No dataset is linked to this experiment"
        >
          <p className="drw-hint">
            Datasets enter an investigation through Evaluation and Calibration, which are not
            stored. {ws.datasets.length} dataset(s) exist in this workspace.
          </p>
        </Step>
        <Step
          title="Experiment"
          state={ws.status === "succeeded" ? "done" : "failed"}
          summary={`${result.experiment_id} · ${result.runs.filter((r) => r.status === "succeeded").length}/${result.runs.length} runs`}
          open
        >
          <dl className="drw-kv drw-kv--tight">
            <div>
              <dt>Experiment</dt>
              <dd className="drw-mono">{result.experiment_id}</dd>
            </div>
            <div>
              <dt>Specification hash</dt>
              <dd className="drw-mono" data-testid="spec-hash-full">
                {result.spec_hash}
              </dd>
            </div>
            <div>
              <dt>Isolation</dt>
              <dd>{result.isolation}</dd>
            </div>
            <div>
              <dt>Started</dt>
              <dd>{formatWhen(result.started_at)}</dd>
            </div>
            <div>
              <dt>Finished</dt>
              <dd>{formatWhen(result.finished_at)}</dd>
            </div>
          </dl>

          <h3 className="drw-subheading">Configuration</h3>
          <pre className="drw-pre" tabIndex={0} data-testid="spec-preview">
            {JSON.stringify(ws.spec, null, 2)}
          </pre>

          {envEntries.length > 0 ? (
            <>
              <h3 className="drw-subheading">Environment</h3>
              <dl className="drw-kv drw-kv--tight">
                {envEntries.map(([key, value]) => (
                  <div key={key}>
                    <dt>{key}</dt>
                    <dd className="drw-mono">{String(value)}</dd>
                  </div>
                ))}
              </dl>
            </>
          ) : null}

          {evidence ? (
            <>
              <h3 className="drw-subheading">Artifacts and integrity</h3>
              <table className="drw-table" aria-label="Evidence artifacts">
                <thead>
                  <tr>
                    <th scope="col">path</th>
                    <th scope="col">kind</th>
                    <th scope="col">sha256</th>
                    <th scope="col" className="drw-num">bytes</th>
                  </tr>
                </thead>
                <tbody>
                  {evidence.files.map((file) => (
                    <tr key={file.path}>
                      <td className="drw-mono">{file.path}</td>
                      <td>{file.kind}</td>
                      <td className="drw-mono" title={file.sha256}>
                        {shortHash(file.sha256, 16)}
                      </td>
                      <td className="drw-num">{file.size_bytes}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <h3 className="drw-subheading">Manifest</h3>
              <pre className="drw-pre" tabIndex={0}>
                {JSON.stringify(evidence.manifest, null, 2)}
              </pre>
            </>
          ) : (
            <p className="drw-hint">Evidence files are loading or unavailable.</p>
          )}

          <div className="drw-row drw-row--center">
            <Button
              kind="tertiary"
              size="md"
              onClick={() => void ws.exportEvidence()}
              disabled={ws.exporting}
              data-testid="export-button"
            >
              {ws.exporting ? "Exporting..." : "Export evidence bundle"}
            </Button>
            {ws.exportMessage ? (
              <span className="drw-hint" data-testid="export-message">
                {ws.exportMessage}
              </span>
            ) : null}
          </div>

          <h3 className="drw-subheading">Reproducibility</h3>
          <ReproducePanel client={ws.api} experimentId={id} />
        </Step>
        <Step title="Evaluation" state="pending" summary="Not recorded: computed on demand under Analysis" />
        <Step title="Calibration" state="pending" summary="Not recorded: computed on demand under Analysis" />
        <Step title="Validation" state="pending" summary="Computed on demand under Validation" />
        <Step title="Conclusion" state="pending" summary="Not established" />
      </ol>
    </Page>
  );
}

export { Section };
