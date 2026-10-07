"use client";

import { useMemo, useRef, useState } from "react";

import { useRouter } from "next/navigation";

import { Add } from "@carbon/icons-react";
import { Button, InlineLoading } from "@carbon/react";

import { DatasetImportPanel } from "@/components/DatasetImportPanel";
import { DatasetsPanel } from "@/components/DatasetsPanel";
import { StartExperiment } from "@/components/ExperimentsSidebar";
import { EmptyState, Page, StateMark } from "@/components/page/Page";
import { NavLink } from "@/components/shell/NavLink";
import { Composer, PROJECT_SUGGESTIONS, Suggestions } from "@/components/si/SiView";
import { useWorkspace } from "@/components/workspace/WorkspaceProvider";
import { modelViability } from "@/lib/experiment";
import { formatWhen, investigationStage, investigationTitle, newestFirst } from "@/lib/investigation";
import { DRAFT_ID, paths } from "@/lib/routes";

/* ------------------------------------------------------------------ overview */

export function ProjectOverviewView() {
  const ws = useWorkspace();
  const router = useRouter();
  const [draft, setDraft] = useState("");
  const areaRef = useRef<HTMLTextAreaElement>(null);
  const project = ws.projects.find((p) => p.project_id === ws.projectId);
  const recent = newestFirst(ws.experiments).slice(0, 4);

  function ask(): void {
    const question = draft.trim();
    if (!question || !ws.selectedModelId) return;
    void ws.askSi(DRAFT_ID, question, ws.selectedModelId);
    setDraft("");
    router.push(paths.investigation(ws.projectId, DRAFT_ID, "si"));
  }

  function pick(item: { prompt: string | null }): void {
    if (item.prompt === null) {
      router.push(paths.projectSection(ws.projectId, "data"));
      return;
    }
    setDraft(item.prompt);
    areaRef.current?.focus();
  }

  const quick: { label: string; count: number; href: string }[] = [
    { label: "Data", count: ws.datasets.length, href: paths.projectSection(ws.projectId, "data") },
    { label: "Models", count: ws.models.length, href: paths.projectSection(ws.projectId, "models") },
    {
      label: "Experiments",
      count: ws.experiments.length,
      href: paths.projectSection(ws.projectId, "experiments"),
    },
    {
      label: "Evidence",
      count: ws.experiments.filter((e) => e.n_succeeded > 0).length,
      href: paths.projectSection(ws.projectId, "evidence"),
    },
  ];

  return (
    <div className="drw-overview" data-testid="project-overview">
      <section className="si si--home" aria-label="Ask SI about this project">
        <div className="si__welcome">
          <p className="drw-eyebrow" data-testid="project-name">
            {project?.name ?? "Project"}
          </p>
          <h1 className="si__title">What are you investigating?</h1>
          <p className="si__sub">
            Ask SI to analyze your models, observations, experiments, or hypotheses.
          </p>
        </div>
        <div className="si__dock">
          <div className="si__column">
            <Composer
              value={draft}
              onChange={setDraft}
              onSubmit={ask}
              busy={false}
              models={ws.models}
              selectedModelId={ws.selectedModelId}
              onSelectModel={ws.setSelectedModelId}
              placeholder="Ask SI about this project..."
              rows={4}
              onAttach={() => router.push(paths.projectSection(ws.projectId, "data"))}
              inputRef={areaRef}
            />
            <Suggestions items={PROJECT_SUGGESTIONS} onPick={pick} />
          </div>
        </div>
      </section>

      <div className="drw-overview__rest">
        <div className="drw-overview__col">
          <h2 className="drw-eyebrow">Recent investigations</h2>
          {ws.listLoading ? <InlineLoading description="Loading" /> : null}
          {!ws.listLoading && recent.length === 0 ? (
            <p className="drw-hint">
              None yet. Ask SI above, or start one from{" "}
              <NavLink href={paths.projectSection(ws.projectId, "investigations")} className="si-link">
                Investigations
              </NavLink>
              .
            </p>
          ) : null}
          <ul className="drw-rows">
            {recent.map((experiment) => (
              <li key={experiment.experiment_id}>
                <NavLink
                  href={paths.investigation(ws.projectId, experiment.experiment_id, "overview")}
                  className="drw-row-link"
                >
                  <span className="drw-row-link__main">{investigationTitle(experiment)}</span>
                  <span className="drw-row-link__meta">{experiment.model_id}</span>
                </NavLink>
              </li>
            ))}
          </ul>
        </div>

        <div className="drw-overview__col">
          <h2 className="drw-eyebrow">Recent activity</h2>
          {recent.length === 0 ? <p className="drw-hint">Nothing has run in this project yet.</p> : null}
          <ul className="drw-activity" data-testid="recent-activity">
            {recent.map((experiment) => {
              const stage = investigationStage(experiment);
              return (
                <li key={experiment.experiment_id}>
                  <StateMark kind={stage.kind} />
                  <span>
                    {stage.label}: {experiment.n_succeeded}/{experiment.n_runs} runs
                    <span className="drw-row-link__meta"> · {formatWhen(experiment.created_at)}</span>
                  </span>
                </li>
              );
            })}
          </ul>
        </div>
      </div>

      <h2 className="drw-eyebrow">Library</h2>
      <ul className="drw-quick" aria-label="Project Library">
        {quick.map((item) => (
          <li key={item.label}>
            <NavLink href={item.href} className="drw-quick__item">
              <span className="drw-quick__count">{item.count}</span>
              <span>{item.label}</span>
            </NavLink>
          </li>
        ))}
      </ul>
    </div>
  );
}

/* ------------------------------------------------------------- investigations */

export function InvestigationsIndexView() {
  const ws = useWorkspace();
  const [query, setQuery] = useState("");
  const [creating, setCreating] = useState(false);

  const rows = useMemo(() => {
    const needle = query.trim().toLowerCase();
    const sorted = newestFirst(ws.experiments);
    return needle
      ? sorted.filter((e) =>
          `${investigationTitle(e)} ${e.model_id}`.toLowerCase().includes(needle),
        )
      : sorted;
  }, [ws.experiments, query]);

  return (
    <Page
      title="Investigations"
      purpose="Scientific questions in this project. Each is addressed by a stored experiment."
      testId="investigations-index"
      actions={
        <Button
          size="md"
          renderIcon={Add}
          data-testid="new-investigation"
          onClick={() => setCreating((current) => !current)}
        >
          New investigation
        </Button>
      }
    >
      {creating ? (
        <StartExperiment
          models={ws.models}
          modelCapabilities={ws.capabilitiesById}
          selectedModelId={ws.selectedModelId}
          startingExperiment={ws.startingExperiment}
          onOpenSample={() => void ws.openSample()}
          onSelectModel={ws.setSelectedModelId}
          onStartExperiment={(modelId) => void ws.startInvestigation(modelId)}
        />
      ) : null}

      {ws.hasDraft ? (
        <NavLink
          href={paths.investigation(ws.projectId, DRAFT_ID, "overview")}
          className="drw-draftbar"
          data-testid="draft-link"
        >
          Unsaved draft in progress: {ws.hypothesis || "Untitled investigation"}
          <span className="drw-row-link__meta"> · model {ws.schema?.model_id}</span>
        </NavLink>
      ) : null}

      <div className="drw-filter">
        <input
          className="drw-filter__input"
          type="search"
          aria-label="Filter investigations"
          placeholder="Filter by question or model"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
        />
      </div>

      {ws.listLoading ? <InlineLoading description="Loading investigations" /> : null}
      {!ws.listLoading && ws.experiments.length === 0 ? (
        <EmptyState title="No investigations yet" testId="investigations-empty">
          Start one with New investigation, or ask SI from the project overview. An investigation
          is stored once its experiment has run.
        </EmptyState>
      ) : null}

      {rows.length > 0 ? (
        <table className="drw-table" data-testid="investigations-list">
          <thead>
            <tr>
              <th scope="col">Question</th>
              <th scope="col">Model</th>
              <th scope="col">Status</th>
              <th scope="col">Updated</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((experiment) => {
              const stage = investigationStage(experiment);
              return (
                <tr key={experiment.experiment_id}>
                  <td>
                    <NavLink
                      href={paths.investigation(ws.projectId, experiment.experiment_id, "overview")}
                      className="drw-table__link"
                    >
                      {investigationTitle(experiment)}
                    </NavLink>
                    <span className="drw-table__sub drw-mono">{experiment.experiment_id}</span>
                  </td>
                  <td className="drw-mono">{experiment.model_id}</td>
                  <td>
                    <StateMark kind={stage.kind} /> {stage.label} ({experiment.n_succeeded}/
                    {experiment.n_runs})
                  </td>
                  <td>{formatWhen(experiment.created_at)}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      ) : null}
      <p className="drw-hint">
        Datasets are shared across the whole workspace (they are not scoped to a project) and are linked to an investigation only when you evaluate or
        calibrate with them, so they are not listed here.
      </p>
    </Page>
  );
}

/* ----------------------------------------------------------------------- data */

export function DataView({ scope }: { scope: "project" | "investigation" }) {
  const ws = useWorkspace();
  return (
    <Page
      title="Data"
      purpose={
        scope === "project"
          ? "The datasets in this project's Library. Datasets are shared across the workspace and can be used by any investigation."
          : "The observations this investigation uses. Datasets are shared across the workspace; one becomes part of an investigation when you evaluate or calibrate with it."
      }
      testId="data-page"
    >
      <p className="drw-context" data-testid="data-context">
        {scope === "project" ? "Project · Library · Data" : "Investigation · Data"}
      </p>
      <DatasetImportPanel client={ws.api} onImported={ws.bumpDatasets} />
      <DatasetsPanel client={ws.api} refreshToken={ws.datasetsRefresh} />
    </Page>
  );
}

/* --------------------------------------------------------------------- models */

export function ProjectModelsView() {
  const ws = useWorkspace();
  return (
    <Page
      title="Models"
      purpose="Registered computational models available to this project."
      testId="models-page"
    >
      {ws.models.length === 0 ? <InlineLoading description="Loading models" /> : null}
      {ws.models.length > 0 ? (
        <table className="drw-table" data-testid="models-list">
          <thead>
            <tr>
              <th scope="col">Model</th>
              <th scope="col">Version</th>
              <th scope="col">Parameters</th>
              <th scope="col">Outputs</th>
              <th scope="col">
                <span className="drw-sr">Action</span>
              </th>
            </tr>
          </thead>
          <tbody>
            {ws.models.map((model) => {
              const viability = modelViability(ws.capabilitiesById[model.model_id]);
              return (
                <tr key={model.model_id}>
                  <td>
                    <span className="drw-table__link drw-mono">{model.model_id}</span>
                    <span className="drw-table__sub">{model.description}</span>
                    {!viability.eligible && viability.reason ? (
                      <span className="drw-table__sub drw-error-text">{viability.reason}</span>
                    ) : null}
                  </td>
                  <td>v{model.version}</td>
                  <td>{model.n_parameters}</td>
                  <td>{model.n_outputs}</td>
                  <td className="drw-table__action">
                    <Button
                      kind="tertiary"
                      size="sm"
                      disabled={!viability.eligible || ws.startingExperiment}
                      data-testid={`start-${model.model_id}`}
                      onClick={() => void ws.startInvestigation(model.model_id)}
                    >
                      Start investigation
                    </Button>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      ) : null}
      <p className="drw-hint">
        Starting an investigation seeds a <strong>demonstration</strong> configuration (+10% on the
        first input), not a scientifically justified experiment. Technical eligibility is not
        scientific validity.
      </p>
    </Page>
  );
}

/* ---------------------------------------------------------------- experiments */

export function ProjectExperimentsView() {
  const ws = useWorkspace();
  const rows = newestFirst(ws.experiments);
  return (
    <Page
      title="Experiments"
      purpose="Every computational experiment stored in this project."
      testId="project-experiments"
    >
      {ws.listLoading ? <InlineLoading description="Loading experiments" /> : null}
      {!ws.listLoading && rows.length === 0 ? (
        <EmptyState title="No experiments yet">
          Experiments are stored when an investigation's configuration is run.
        </EmptyState>
      ) : null}
      {rows.length > 0 ? (
        <table className="drw-table" data-testid="experiments-list">
          <thead>
            <tr>
              <th scope="col">Experiment</th>
              <th scope="col">Model</th>
              <th scope="col">Runs</th>
              <th scope="col">Isolation</th>
              <th scope="col">Spec hash</th>
              <th scope="col">Created</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((experiment) => (
              <tr key={experiment.experiment_id}>
                <td>
                  <NavLink
                    href={paths.investigation(ws.projectId, experiment.experiment_id, "experiments")}
                    className="drw-table__link drw-mono"
                  >
                    {experiment.experiment_id}
                  </NavLink>
                  <span className="drw-table__sub">{investigationTitle(experiment)}</span>
                </td>
                <td className="drw-mono">{experiment.model_id}</td>
                <td>
                  {experiment.n_succeeded}/{experiment.n_runs}
                  {experiment.n_failed > 0 ? ` · ${experiment.n_failed} failed` : ""}
                </td>
                <td>{experiment.isolation}</td>
                <td className="drw-mono">{experiment.spec_hash.slice(0, 12)}</td>
                <td>{formatWhen(experiment.created_at)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : null}
    </Page>
  );
}

/* ------------------------------------------------------------------- evidence */

export function ProjectEvidenceView() {
  const ws = useWorkspace();
  const rows = newestFirst(ws.experiments).filter((e) => e.n_runs > 0);
  return (
    <Page
      title="Evidence"
      purpose="Experiments with stored evidence. Open one to trace and reproduce it."
      testId="project-evidence"
    >
      {!ws.listLoading && rows.length === 0 ? (
        <EmptyState title="No evidence yet" testId="evidence-empty">
          Evidence is recorded when an experiment runs.
        </EmptyState>
      ) : null}
      {rows.length > 0 ? (
        <ul className="drw-rows">
          {rows.map((experiment) => (
            <li key={experiment.experiment_id}>
              <NavLink
                href={paths.investigation(ws.projectId, experiment.experiment_id, "evidence")}
                className="drw-row-link"
              >
                <span className="drw-row-link__main">{investigationTitle(experiment)}</span>
                <span className="drw-row-link__meta">
                  {experiment.experiment_id} · spec {experiment.spec_hash.slice(0, 12)} ·{" "}
                  {formatWhen(experiment.created_at)}
                </span>
              </NavLink>
            </li>
          ))}
        </ul>
      ) : null}
    </Page>
  );
}
