import { act, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { ApiError, type DrwClient } from "@/lib/client";
import type {
  ExperimentData,
  ExperimentSummary,
  ModelCapabilities,
  ModelSummary,
  PlanProposal,
  ValidationResult,
} from "@/lib/types";
import {
  defaultProject,
  lorenzCapabilities,
  multiModelClient,
  okValidation,
  record,
  sampleSpec,
  stubClient,
  succeededData,
} from "@/test/stubClient";
import { __getPath } from "@/test/next-navigation";
import { renderApp } from "@/test/renderApp";

type User = ReturnType<typeof userEvent.setup>;

const INV = "/projects/default/investigations";

function summary(overrides: Partial<ExperimentSummary> = {}): ExperimentSummary {
  return {
    experiment_id: "exp-000000000000",
    project_id: "default",
    name: "sample",
    hypothesis: sampleSpec.hypothesis,
    model_id: "predator-prey",
    isolation: "subprocess",
    spec_hash: "a".repeat(64),
    n_runs: 2,
    n_succeeded: 2,
    n_failed: 0,
    created_at: "2026-02-01T10:00:00+00:00",
    warnings: [],
    ...overrides,
  };
}

/** Starts the sample as a draft and opens its Configuration page. */
async function configureSample(user: User, client: DrwClient) {
  renderApp(client, `${INV}/draft/overview`);
  await user.click(await screen.findByTestId("open-sample"));
  await screen.findByTestId("investigation-overview");
  await user.click(
    within(screen.getByRole("navigation", { name: "Investigation" })).getByRole("link", {
      name: "Experiments",
    }),
  );
  await user.click(await screen.findByRole("link", { name: "Configuration" }));
  await screen.findByTestId("experiment-configure");
}

async function validateOk(user: User) {
  await user.click(screen.getByTestId("validate-button"));
  await waitFor(() => expect(screen.getByTestId("validation-verdict")).toHaveTextContent(/^valid$/));
}

describe("project level", () => {
  it("opens on the project overview with SI first and what exists", async () => {
    const client = stubClient({
      listExperiments: vi.fn().mockResolvedValue([summary()]),
    });
    renderApp(client);
    expect(await screen.findByRole("heading", { name: "What are you investigating?" })).toBeInTheDocument();
    expect(await screen.findByTestId("project-name")).toHaveTextContent(defaultProject.name);
    expect(screen.getByTestId("mode-si")).toHaveAttribute("aria-selected", "true");
    const activity = await screen.findByTestId("recent-activity");
    expect(activity).toHaveTextContent("2/2 runs");
    expect(
      within(screen.getByRole("list", { name: "Project contents" })).getByRole("link", { name: /Experiments/ }),
    ).toBeInTheDocument();
  });

  it("navigates between project pages from the sidebar", async () => {
    const user = userEvent.setup();
    renderApp(stubClient());
    await screen.findByTestId("project-overview");
    const nav = screen.getByRole("navigation", { name: "Project" });
    await user.click(within(nav).getByRole("link", { name: "Investigations" }));
    expect(await screen.findByTestId("investigations-index")).toBeInTheDocument();
    expect(__getPath()).toBe("/projects/default/investigations");
    await user.click(within(nav).getByRole("link", { name: "Models" }));
    expect(await screen.findByTestId("models-list")).toBeInTheDocument();
    await user.click(within(nav).getByRole("link", { name: "Data" }));
    expect(await screen.findByTestId("data-page")).toBeInTheDocument();
  });

  it("says so when the project does not exist", async () => {
    renderApp(stubClient(), "/projects/nope");
    expect(await screen.findByTestId("project-not-found")).toBeInTheDocument();
  });

  it("lists investigations as questions with model and status", async () => {
    renderApp(stubClient({ listExperiments: vi.fn().mockResolvedValue([summary()]) }), INV);
    const list = await screen.findByTestId("investigations-list");
    expect(within(list).getByRole("link", { name: sampleSpec.hypothesis })).toHaveAttribute(
      "href",
      `${INV}/exp-000000000000/overview`,
    );
    expect(list).toHaveTextContent("predator-prey");
    expect(list).toHaveTextContent("Baseline run completed");
  });

  it("shows an honest empty state with no investigations", async () => {
    renderApp(stubClient(), INV);
    expect(await screen.findByTestId("investigations-empty")).toBeInTheDocument();
  });

  it("switches project from the header and reloads that project's experiments", async () => {
    const user = userEvent.setup();
    const second = { ...defaultProject, project_id: "proj-aaaaaaaaaaaa", name: "Second study" };
    const listExperiments = vi.fn().mockResolvedValue([]);
    renderApp(stubClient({ listProjects: vi.fn().mockResolvedValue([defaultProject, second]), listExperiments }));
    await screen.findByTestId("project-overview");
    await user.click(screen.getByTestId("project-switcher"));
    await user.click(await screen.findByRole("button", { name: "Second study" }));
    await waitFor(() => expect(__getPath()).toBe("/projects/proj-aaaaaaaaaaaa"));
    await waitFor(() => expect(listExperiments).toHaveBeenCalledWith("proj-aaaaaaaaaaaa"));
  });

  it("creates a project from the switcher and opens it", async () => {
    const user = userEvent.setup();
    const createProject = vi.fn().mockResolvedValue({
      project_id: "proj-bbbbbbbbbbbb",
      name: "Fresh",
      description: "",
      model_id: null,
      created_at: "2026-01-03T00:00:00+00:00",
    });
    renderApp(stubClient({ createProject }));
    await screen.findByTestId("project-overview");
    await user.click(screen.getByTestId("project-switcher"));
    await user.click(await screen.findByRole("button", { name: "New project" }));
    await user.type(screen.getByLabelText("New project name"), "Fresh");
    await user.click(screen.getByRole("button", { name: "Create" }));
    await waitFor(() => expect(createProject).toHaveBeenCalledWith("Fresh", undefined));
    await waitFor(() => expect(__getPath()).toBe("/projects/proj-bbbbbbbbbbbb"));
  });

  it("starts an investigation from a registered model", async () => {
    const user = userEvent.setup();
    renderApp(multiModelClient(), "/projects/default/models");
    const button = await screen.findByTestId("start-oscillator");
    await waitFor(() => expect(button).toBeEnabled());
    await user.click(button);
    await waitFor(() => expect(__getPath()).toBe(`${INV}/draft/overview`));
    expect(await screen.findByTestId("investigation-overview")).toBeInTheDocument();
  });

  it("disables models the engine cannot configure and says why", async () => {
    const models: ModelSummary[] = [
      { model_id: "toy", version: "1.0.0", description: "noise", n_parameters: 1, n_outputs: 1 },
    ];
    const toy: ModelCapabilities = {
      ...lorenzCapabilities,
      model_id: "toy",
      parameter_names: ["mode"],
      factorable_parameters: [],
      fixed_parameters: [],
      timeseries_outputs: [],
      scalar_outputs: [],
    };
    renderApp(
      stubClient({
        listModels: vi.fn().mockResolvedValue(models),
        capabilities: vi.fn().mockResolvedValue(toy),
      }),
      "/projects/default/models",
    );
    const button = await screen.findByTestId("start-toy");
    await waitFor(() => expect(button).toBeDisabled());
    expect(screen.getByTestId("models-list")).toHaveTextContent(/no numeric parameter/);
  });
});

describe("investigation workspace", () => {
  it("explains there is no draft and offers to start one", async () => {
    renderApp(stubClient(), `${INV}/draft/overview`);
    expect(await screen.findByTestId("no-draft")).toBeInTheDocument();
    expect(screen.getByTestId("open-sample")).toBeInTheDocument();
  });

  it("opens a draft with scientific state that does not overclaim", async () => {
    const user = userEvent.setup();
    renderApp(stubClient(), `${INV}/draft/overview`);
    await user.click(await screen.findByTestId("open-sample"));
    expect(await screen.findByTestId("investigation-question")).toHaveTextContent(sampleSpec.hypothesis);
    const state = screen.getByTestId("scientific-state");
    expect(within(state).getByRole("row", { name: /Baseline/ })).toHaveTextContent("Draft: not run");
    expect(within(state).getByRole("row", { name: /Validation/ })).toHaveTextContent(
      "Not implemented in this version",
    );
    expect(screen.getByTestId("investigation-conclusion")).toHaveTextContent("Not established");
  });

  it("keeps analysis, evidence and validation honest before anything has run", async () => {
    const user = userEvent.setup();
    renderApp(stubClient(), `${INV}/draft/overview`);
    await user.click(await screen.findByTestId("open-sample"));
    await screen.findByTestId("investigation-overview");
    const nav = screen.getByRole("navigation", { name: "Investigation" });

    await user.click(within(nav).getByRole("link", { name: "Analysis" }));
    expect(await screen.findByTestId("analysis-index")).toBeInTheDocument();
    await user.click(screen.getByRole("link", { name: /^Identifiability/ }));
    expect(await screen.findByTestId("needs-run")).toBeInTheDocument();

    await user.click(within(nav).getByRole("link", { name: "Evidence" }));
    expect(await screen.findByTestId("evidence-empty")).toBeInTheDocument();

    await user.click(within(nav).getByRole("link", { name: "Validation" }));
    expect(await screen.findByTestId("validation-unavailable")).toHaveTextContent(
      "Not implemented in this version",
    );
  });

  it("shows the model on its own page with parameters and outputs", async () => {
    const user = userEvent.setup();
    renderApp(stubClient(), `${INV}/draft/overview`);
    await user.click(await screen.findByTestId("open-sample"));
    await screen.findByTestId("investigation-overview");
    await user.click(
      within(screen.getByRole("navigation", { name: "Investigation" })).getByRole("link", { name: "Model" }),
    );
    expect(await screen.findByTestId("investigation-model")).toBeInTheDocument();
    await user.click(screen.getByRole("tab", { name: "Parameters" }));
    expect(await screen.findByRole("cell", { name: /alpha/ })).toBeInTheDocument();
    await user.click(screen.getByRole("tab", { name: "Outputs" }));
    expect(await screen.findByRole("table", { name: "Model outputs" })).toBeInTheDocument();
  });

  it("opens a stored investigation straight from its URL", async () => {
    const results = succeededData();
    const getExperiment = vi.fn().mockResolvedValue({ meta: summary(), spec: sampleSpec, results });
    renderApp(stubClient({ getExperiment }), `${INV}/exp-000000000000/overview`);
    expect(await screen.findByTestId("investigation-question")).toHaveTextContent(sampleSpec.hypothesis);
    expect(getExperiment).toHaveBeenCalledWith("exp-000000000000");
    const state = screen.getByTestId("scientific-state");
    expect(within(state).getByRole("row", { name: /Baseline/ })).toHaveTextContent("2/2 runs succeeded");
  });

  it("reports an investigation that cannot be opened", async () => {
    const getExperiment = vi.fn().mockRejectedValue(new ApiError("not_found", "no such experiment"));
    renderApp(stubClient({ getExperiment }), `${INV}/exp-ffffffffffff/overview`);
    expect(await screen.findByTestId("investigation-unavailable")).toBeInTheDocument();
    expect(screen.getByTestId("error-message")).toHaveTextContent("no such experiment");
  });

  it("shows the evidence chain with hashes and unrecorded steps stated plainly", async () => {
    const results = { ...succeededData(), evidence: { manifest: { spec_hash: "x" }, report: "r", files: [] } };
    const getExperiment = vi.fn().mockResolvedValue({ meta: summary(), spec: sampleSpec, results });
    const evidence = vi.fn().mockResolvedValue(results.evidence);
    renderApp(stubClient({ getExperiment, evidence }), `${INV}/exp-000000000000/evidence`);
    const chain = await screen.findByTestId("evidence-chain");
    expect(within(chain).getByTestId("spec-hash-full")).toHaveTextContent("a".repeat(64));
    expect(within(chain).getByTestId("model-hash")).toHaveTextContent("b".repeat(64));
    expect(chain).toHaveTextContent("No dataset is linked to this experiment");
    expect(chain).toHaveTextContent("Not implemented in this version");
    expect(chain).toHaveTextContent("Not established");
  });
});

describe("configure and run", () => {
  it("configures the sample and keeps Run disabled before validation", async () => {
    const user = userEvent.setup();
    await configureSample(user, stubClient());
    expect(screen.getByTestId("status-value")).toHaveTextContent("idle");
    expect(screen.getByTestId("demo-seed-note")).toHaveTextContent(/demonstration/i);
    expect(screen.getByTestId("run-button")).toBeDisabled();
    expect(screen.getByTestId("run-blocked")).toBeInTheDocument();
  });

  it("shows actionable validation errors and keeps run disabled", async () => {
    const user = userEvent.setup();
    const client = stubClient({
      validate: vi.fn().mockResolvedValue({
        ok: false,
        diagnostics: [
          {
            level: "error",
            code: "factor_out_of_bounds",
            message: "factor 'alpha' reaches 999 above declared upper bound 3",
          },
        ],
        estimate: okValidation.estimate,
      } satisfies ValidationResult),
    });
    await configureSample(user, client);
    await user.click(screen.getByTestId("validate-button"));
    expect(await screen.findByTestId("validation-verdict")).toHaveTextContent(/^invalid$/);
    expect(screen.getByText(/factor_out_of_bounds/)).toBeInTheDocument();
    expect(screen.getByTestId("run-button")).toBeDisabled();
  });

  it("runs, stores the investigation under its experiment id, and lists the runs", async () => {
    const user = userEvent.setup();
    const getExperiment = vi.fn();
    const client = stubClient({ run: vi.fn().mockResolvedValue(succeededData()), getExperiment });
    await configureSample(user, client);
    await validateOk(user);
    await user.click(screen.getByTestId("run-button"));

    await waitFor(() => expect(__getPath()).toBe(`${INV}/exp-000000000000/experiments`));
    expect(await screen.findByTestId("runs-list")).toBeInTheDocument();
    expect(screen.getByTestId("status-value")).toHaveTextContent(/^succeeded$/);
    // The in-session result is reused: the stored experiment is not fetched again.
    expect(getExperiment).not.toHaveBeenCalled();

    // Analyses are now available for this investigation.
    await user.click(
      within(screen.getByRole("navigation", { name: "Investigation" })).getByRole("link", { name: "Analysis" }),
    );
    await user.click(await screen.findByRole("link", { name: /^Sensitivity/ }));
    expect(await screen.findByTestId("sobol-panel")).toBeInTheDocument();
  });

  it("frames results as observed simulation output, not scientific proof", async () => {
    const user = userEvent.setup();
    await configureSample(user, stubClient({ run: vi.fn().mockResolvedValue(succeededData()) }));
    await validateOk(user);
    await user.click(screen.getByTestId("run-button"));
    await waitFor(() => expect(__getPath()).toBe(`${INV}/exp-000000000000/experiments`));
    await user.click(await screen.findByRole("link", { name: "Results" }));
    expect(await screen.findByTestId("observation-caveat")).toHaveTextContent(
      /not an established scientific conclusion/i,
    );
  });

  it("never claims success when the run fails", async () => {
    const user = userEvent.setup();
    const client = stubClient({
      run: vi.fn().mockRejectedValue(new ApiError("validation_error", "the run was rejected")),
    });
    await configureSample(user, client);
    await validateOk(user);
    await user.click(screen.getByTestId("run-button"));
    await waitFor(() => expect(screen.getByTestId("status-value")).toHaveTextContent("failed"));
    expect(__getPath()).toBe(`${INV}/draft/experiments/configure`);
    expect(screen.getByTestId("error-message")).toHaveTextContent("the run was rejected");
  });

  it("reports cancellation", async () => {
    const user = userEvent.setup();
    const client = stubClient({
      run: vi.fn().mockRejectedValue(new ApiError("cancelled", "the request was cancelled")),
    });
    await configureSample(user, client);
    await validateOk(user);
    await user.click(screen.getByTestId("run-button"));
    await waitFor(() => expect(screen.getByTestId("status-value")).toHaveTextContent("cancelled"));
  });

  it("reports a timeout accurately", async () => {
    const user = userEvent.setup();
    const timedOut = succeededData();
    timedOut.runs = [record({ status: "failed", timed_out: true, error: "timeout" })];
    await configureSample(user, stubClient({ run: vi.fn().mockResolvedValue(timedOut) }));
    await validateOk(user);
    await user.click(screen.getByTestId("run-button"));
    await waitFor(() => expect(screen.getByTestId("status-value")).toHaveTextContent("timed_out"));
  });

  it("writes the execution timeout into the spec", async () => {
    const user = userEvent.setup();
    await configureSample(user, stubClient());
    const timeout = screen.getByLabelText(/Execution timeout/);
    await user.clear(timeout);
    await user.type(timeout, "0.25");
    await waitFor(() =>
      expect(screen.getByTestId("spec-preview").textContent).toContain('"timeout_s": 0.25'),
    );
  });

  it("sends the route's project id and a job id, and shows measured progress", async () => {
    const user = userEvent.setup();
    let resolveRun: ((value: ExperimentData) => void) | undefined;
    const pending = new Promise<ExperimentData>((resolve) => {
      resolveRun = resolve;
    });
    const run = vi.fn().mockReturnValue(pending);
    const jobStatus = vi.fn().mockResolvedValue({
      job_id: "job-0000000000000000",
      phase: "running",
      terminal: false,
      completed_runs: 1,
      total_runs: 2,
      status: null,
      events: [],
    });
    await configureSample(user, stubClient({ run, jobStatus }));
    await validateOk(user);
    await user.click(screen.getByTestId("run-button"));

    await waitFor(
      () => expect(screen.getByTestId("status-banner")).toHaveTextContent("1 of 2 runs completed"),
      { timeout: 4000 },
    );
    const call = run.mock.calls[0] as [unknown, { projectId?: string; jobId?: string }];
    expect(call[1].projectId).toBe("default");
    expect(call[1].jobId).toMatch(/^job-[0-9a-f]{16}$/);

    await act(async () => {
      resolveRun?.(succeededData());
    });
    await waitFor(() => expect(screen.getByTestId("status-value")).toHaveTextContent(/^succeeded$/));
  });
});

describe("SI", () => {
  const proposal: PlanProposal = {
    spec: sampleSpec,
    assumptions: ["baseline set to nominal"],
    questions: [],
    diagnostics: [],
    validation_ok: true,
    provider: "rule-based",
    used_ai: false,
    rationale: "Proposed varying alpha by 10%.",
  };

  it("asks from the project overview and continues in the investigation's SI page", async () => {
    const user = userEvent.setup();
    const planExperiment = vi.fn().mockResolvedValue(proposal);
    renderApp(stubClient({ planExperiment }));
    await waitFor(() => expect(screen.getByTestId("si-model")).toHaveValue("predator-prey"));
    await user.type(screen.getByTestId("si-input"), "increase alpha by 10%");
    await user.click(screen.getByTestId("si-send"));

    await waitFor(() => expect(__getPath()).toBe(`${INV}/draft/si`));
    expect(await screen.findByTestId("si-plan")).toHaveTextContent("Proposed experiment");
    expect(planExperiment).toHaveBeenCalledWith("predator-prey", "increase alpha by 10%");
  });

  it("proposes, never runs, and opens the proposal in Manual configuration", async () => {
    const user = userEvent.setup();
    const run = vi.fn().mockResolvedValue(succeededData());
    renderApp(stubClient({ planExperiment: vi.fn().mockResolvedValue(proposal), run }), `${INV}/draft/si`);
    await waitFor(() => expect(screen.getByTestId("si-model")).toHaveValue("predator-prey"));
    await user.type(screen.getByTestId("si-input"), "increase alpha by 10%");
    await user.click(screen.getByTestId("si-send"));
    await screen.findByTestId("si-plan");

    await user.click(screen.getByTestId("si-review-in-manual"));
    await waitFor(() => expect(__getPath()).toBe(`${INV}/draft/experiments/configure`));
    await waitFor(() => expect(screen.getByLabelText("Hypothesis")).toHaveValue(sampleSpec.hypothesis));
    expect(screen.getByTestId("status-value")).toHaveTextContent("idle");
    expect(screen.getByTestId("mode-manual")).toHaveAttribute("aria-selected", "true");
    expect(run).not.toHaveBeenCalled();
  });

  it("asks for more information instead of guessing", async () => {
    const user = userEvent.setup();
    const questions: PlanProposal = {
      ...proposal,
      spec: null,
      questions: ["Which parameter should change?"],
    };
    renderApp(stubClient({ planExperiment: vi.fn().mockResolvedValue(questions) }), `${INV}/draft/si`);
    await waitFor(() => expect(screen.getByTestId("si-model")).toHaveValue("predator-prey"));
    await user.type(screen.getByTestId("si-input"), "vary it");
    await user.click(screen.getByTestId("si-send"));
    expect(await screen.findByTestId("si-questions")).toHaveTextContent("Which parameter should change?");
    expect(screen.queryByTestId("si-review-in-manual")).toBeNull();
  });

  it("surfaces unsupported-capability errors from the planner", async () => {
    const user = userEvent.setup();
    const planExperiment = vi
      .fn()
      .mockRejectedValue(new ApiError("unsupported_capability", "no bounded numeric parameter to vary", []));
    renderApp(stubClient({ planExperiment }), `${INV}/draft/si`);
    await waitFor(() => expect(screen.getByTestId("si-model")).toHaveValue("predator-prey"));
    await user.type(screen.getByTestId("si-input"), "vary the categorical parameter");
    await user.click(screen.getByTestId("si-send"));
    expect(await screen.findByTestId("si-error")).toHaveTextContent(/no bounded numeric/);
    expect(screen.queryByTestId("si-plan")).toBeNull();
  });

  it("toggles between SI and Manual without losing the investigation", async () => {
    const user = userEvent.setup();
    const getExperiment = vi.fn().mockResolvedValue({ meta: summary(), spec: sampleSpec, results: succeededData() });
    renderApp(stubClient({ getExperiment }), `${INV}/exp-000000000000/si`);
    await screen.findByTestId("si-view");
    await user.click(screen.getByTestId("mode-manual"));
    expect(__getPath()).toBe(`${INV}/exp-000000000000/overview`);
    await user.click(await screen.findByTestId("mode-si"));
    expect(__getPath()).toBe(`${INV}/exp-000000000000/si`);
  });
});
