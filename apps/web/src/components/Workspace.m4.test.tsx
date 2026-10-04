import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { Workspace } from "@/components/Workspace";
import { ApiError, type DrwClient } from "@/lib/client";
import { defaultProject, sampleSpec, stubClient, succeededData } from "@/test/stubClient";
import type { ExperimentData, PlanProposal } from "@/lib/types";

async function openSample(user: ReturnType<typeof userEvent.setup>, client: DrwClient) {
  render(<Workspace client={client} />);
  await user.click(await screen.findByTestId("start-sample"));
  await screen.findByRole("cell", { name: "alpha" });
}

async function validateOk(user: ReturnType<typeof userEvent.setup>) {
  await user.click(screen.getByTestId("validate-button"));
  await waitFor(() =>
    expect(screen.getByTestId("validation-verdict")).toHaveTextContent(/^valid$/),
  );
}

describe("projects", () => {
  it("lists projects and reloads experiments when the project changes", async () => {
    const user = userEvent.setup();
    const second = { ...defaultProject, project_id: "proj-aaaaaaaaaaaa", name: "Second study" };
    const listExperiments = vi.fn().mockResolvedValue([]);
    const client = stubClient({
      listProjects: vi.fn().mockResolvedValue([defaultProject, second]),
      listExperiments,
    });
    await openSample(user, client);

    const select = await screen.findByTestId("project-select");
    expect(select).toHaveValue("default");
    await user.selectOptions(select, "proj-aaaaaaaaaaaa");
    await waitFor(() => expect(listExperiments).toHaveBeenCalledWith("proj-aaaaaaaaaaaa"));
  });

  it("creates a project and selects it", async () => {
    const user = userEvent.setup();
    const createProject = vi.fn().mockResolvedValue({
      project_id: "proj-bbbbbbbbbbbb",
      name: "Fresh",
      description: "",
      model_id: null,
      created_at: "2026-01-03T00:00:00+00:00",
    });
    const client = stubClient({ createProject });
    await openSample(user, client);

    await user.type(screen.getByTestId("new-project-name"), "Fresh");
    await user.click(screen.getByTestId("create-project"));
    await waitFor(() => expect(createProject).toHaveBeenCalledWith("Fresh", "predator-prey"));
    await waitFor(() => expect(screen.getByTestId("project-select")).toHaveValue("proj-bbbbbbbbbbbb"));
  });
});

describe("execution controls and measured progress", () => {
  it("writes the execution timeout into the spec", async () => {
    const user = userEvent.setup();
    await openSample(user, stubClient());
    const timeout = screen.getByLabelText(/Execution timeout/);
    await user.clear(timeout);
    await user.type(timeout, "0.25");
    await waitFor(() =>
      expect(screen.getByTestId("spec-preview").textContent).toContain('"timeout_s": 0.25'),
    );
  });

  it("sends a job id and polls measured per-run progress", async () => {
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
    const client = stubClient({ run, jobStatus });
    await openSample(user, client);
    await validateOk(user);
    await user.click(screen.getByTestId("run-button"));

    await waitFor(() => expect(jobStatus).toHaveBeenCalled(), { timeout: 4000 });
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

describe("AI planner", () => {
  it("is available with no LLM provider and reports that", async () => {
    const user = userEvent.setup();
    await openSample(user, stubClient());
    expect(screen.getByTestId("planner-provider-note")).toHaveTextContent(/No LLM provider/);
  });

  it("asks for more information instead of guessing", async () => {
    const user = userEvent.setup();
    await openSample(user, stubClient());
    await user.type(screen.getByTestId("planner-question"), "vary it");
    await user.click(screen.getByTestId("planner-propose"));
    expect(await screen.findByTestId("planner-questions")).toBeInTheDocument();
    expect(screen.queryByTestId("planner-apply")).toBeNull();
  });

  it("proposes a spec, applies it to the editor, and does not run it", async () => {
    const user = userEvent.setup();
    const proposal: PlanProposal = {
      spec: sampleSpec,
      assumptions: ["baseline set to nominal", "proposal must be approved by the user"],
      questions: [],
      diagnostics: [],
      validation_ok: true,
      provider: "rule-based",
      used_ai: false,
      rationale: "Proposed varying alpha by 10%.",
    };
    const run = vi.fn().mockResolvedValue(succeededData());
    const client = stubClient({ planExperiment: vi.fn().mockResolvedValue(proposal), run });
    await openSample(user, client);

    await user.type(
      screen.getByTestId("planner-question"),
      "increase alpha by 10% and compare the prey peak",
    );
    await user.click(screen.getByTestId("planner-propose"));

    expect(await screen.findByTestId("planner-proposal")).toBeInTheDocument();
    expect(screen.getByTestId("planner-validation")).toHaveTextContent(/passes validation/i);
    expect(screen.getByTestId("planner-assumptions")).toBeInTheDocument();

    await user.click(screen.getByTestId("planner-apply"));
    // Applied to the editor...
    await waitFor(() =>
      expect(screen.getByLabelText("Hypothesis")).toHaveValue(sampleSpec.hypothesis),
    );
    // ...but never executed, and success is not claimed.
    expect(run).not.toHaveBeenCalled();
    expect(screen.getByTestId("status-value")).toHaveTextContent("idle");
    expect(screen.queryByTestId("export-button")).toBeNull();
  });

  it("surfaces unsupported-capability errors", async () => {
    const user = userEvent.setup();
    const client = stubClient({
      planExperiment: vi
        .fn()
        .mockRejectedValue(
          new ApiError("unsupported_capability", "this model has no bounded numeric parameter"),
        ),
    });
    await openSample(user, client);
    await user.type(screen.getByTestId("planner-question"), "vary the categorical parameter");
    await user.click(screen.getByTestId("planner-propose"));
    expect(await screen.findByTestId("planner-error")).toHaveTextContent(/no bounded numeric/);
    expect(screen.queryByTestId("planner-proposal")).toBeNull();
  });
});
