"use client";

import { useState } from "react";

import { Add, Launch } from "@carbon/icons-react";
import { Button, InlineLoading, Select, SelectItem, TextInput } from "@carbon/react";

import { NewExperimentPanel } from "@/components/NewExperimentPanel";
import type { ExperimentSummary, ModelCapabilities, ModelSummary, Project } from "@/lib/types";

export function ExperimentsSidebar({
  experiments,
  projects,
  models,
  modelCapabilities,
  selectedModelId,
  activeProjectId,
  activeId,
  startingExperiment,
  onOpen,
  onOpenSample,
  onSelectModel,
  onStartExperiment,
  onSelectProject,
  onCreateProject,
  loading,
}: {
  experiments: ExperimentSummary[];
  projects: Project[];
  models: ModelSummary[];
  modelCapabilities: Record<string, ModelCapabilities>;
  selectedModelId: string;
  activeProjectId: string | null;
  activeId: string | null;
  startingExperiment: boolean;
  onOpen: (experimentId: string) => void;
  onOpenSample: () => void;
  onSelectModel: (modelId: string) => void;
  onStartExperiment: (modelId: string) => void;
  onSelectProject: (projectId: string) => void;
  onCreateProject: (name: string) => void;
  loading: boolean;
}) {
  const [newProject, setNewProject] = useState("");

  return (
    <aside className="drw-sidebar" aria-label="Projects and experiments">
      <div className="drw-sidebar__section drw-stack-tight">
        <h2 className="drw-sidebar__heading">Project</h2>
        <Select
          id="project-select"
          data-testid="project-select"
          labelText="Active project"
          hideLabel
          value={activeProjectId ?? ""}
          onChange={(event) => onSelectProject(event.target.value)}
        >
          {projects.map((project) => (
            <SelectItem key={project.project_id} value={project.project_id} text={project.name} />
          ))}
        </Select>

        <TextInput
          id="new-project-name"
          data-testid="new-project-name"
          labelText="New project"
          placeholder="Project name"
          value={newProject}
          onChange={(event) => setNewProject(event.target.value)}
        />
        <Button
          kind="tertiary"
          size="md"
          renderIcon={Add}
          data-testid="create-project"
          disabled={newProject.trim().length === 0}
          onClick={() => {
            onCreateProject(newProject.trim());
            setNewProject("");
          }}
        >
          Create project
        </Button>
      </div>

      <NewExperimentPanel
        models={models}
        capabilities={modelCapabilities}
        selectedModelId={selectedModelId}
        onSelectModel={onSelectModel}
        onStart={onStartExperiment}
        starting={startingExperiment}
      />

      <div className="drw-sidebar__section">
        <Button
          data-testid="open-sample"
          renderIcon={Launch}
          onClick={onOpenSample}
          className="drw-fill"
        >
          Open sample project (predator-prey)
        </Button>
      </div>

      <nav aria-label="Saved experiments">
        <h2 className="drw-sidebar__heading drw-sidebar__section drw-sidebar__section--flush">
          Saved experiments
        </h2>
        {loading ? (
          <div className="drw-sidebar__section">
            <InlineLoading description="Loading experiments" />
          </div>
        ) : null}
        {!loading && experiments.length === 0 ? (
          <p className="drw-hint drw-sidebar__section drw-sidebar__section--flush">
            None in this project yet. Run the sample experiment to create one.
          </p>
        ) : null}
        <ul className="drw-sidebar__list" data-testid="experiments-list">
          {experiments.map((experiment) => (
            <li key={experiment.experiment_id}>
              <button
                type="button"
                className="drw-experiment"
                onClick={() => onOpen(experiment.experiment_id)}
                aria-current={activeId === experiment.experiment_id ? "true" : undefined}
              >
                <span className="drw-experiment__id" title={experiment.experiment_id}>
                  {experiment.experiment_id}
                </span>
                <span className="drw-experiment__meta">
                  {experiment.model_id} · {experiment.n_succeeded}/{experiment.n_runs} runs
                  {experiment.n_failed > 0 ? ` · ${experiment.n_failed} failed` : ""}
                </span>
              </button>
            </li>
          ))}
        </ul>
      </nav>
    </aside>
  );
}
