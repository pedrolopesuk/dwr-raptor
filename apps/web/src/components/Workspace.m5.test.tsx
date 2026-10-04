import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { Workspace } from "@/components/Workspace";
import {
  lorenzCapabilities,
  multiModelClient,
  okValidation,
  stubClient,
  succeededData,
} from "@/test/stubClient";
import type {
  Comparison,
  ExperimentData,
  ModelCapabilities,
  ModelSummary,
  ValidationResult,
} from "@/lib/types";

function comparison(overrides: Partial<Comparison> = {}): Comparison {
  return {
    reference_run_id: "exp-x-r0000",
    variant_run_id: "exp-x-r0001",
    label: "variant",
    output: "x",
    unit: "m",
    method: "delta",
    alignment: "exact",
    interpolated: false,
    axis: [0, 1],
    reference: [1, 0.5],
    variant: [1.1, 0.4],
    delta: [0.1, -0.1],
    relative_delta: [0.1, -0.2],
    metrics: { max_abs_delta: 0.1, mae: 0.1 },
    warnings: [],
    ...overrides,
  };
}

async function selectModel(user: ReturnType<typeof userEvent.setup>, modelId: string) {
  const select = await screen.findByTestId("model-select");
  // Options start disabled until each model's capabilities are fetched; wait for
  // this model's option to become eligible before selecting it.
  await waitFor(() =>
    expect(within(select).getByRole("option", { name: new RegExp(modelId) })).toBeEnabled(),
  );
  await user.selectOptions(select, modelId);
  await waitFor(() => expect(screen.getByTestId("create-experiment")).toBeEnabled());
}

describe("model-agnostic experiment creation", () => {
  it("lists every registered model in the picker", async () => {
    render(<Workspace client={multiModelClient()} />);
    const select = await screen.findByTestId("model-select");
    const options = within(select)
      .getAllByRole("option")
      .map((option) => option.textContent ?? "");
    expect(options.join(" ")).toMatch(/predator-prey/);
    expect(options.join(" ")).toMatch(/oscillator/);
    expect(options.join(" ")).toMatch(/lorenz/);
  });

  it("starts an experiment from a selected non-sample model using its authoritative metadata", async () => {
    const user = userEvent.setup();
    render(<Workspace client={multiModelClient()} />);
    await selectModel(user, "oscillator");
    await user.click(screen.getByTestId("create-experiment"));

    // The parameters, units and descriptions come from the model's schema.
    expect(await screen.findByTestId("cap-factorable")).toHaveTextContent("m");
    expect(screen.getByRole("cell", { name: "kg" })).toBeInTheDocument();
    expect(screen.getByRole("cell", { name: "Mass." })).toBeInTheDocument();
    expect(screen.getByTestId("cap-outputs")).toHaveTextContent("x");
  });

  it("labels the seeded +10% configuration as a demonstration, not a justified experiment", async () => {
    const user = userEvent.setup();
    render(<Workspace client={multiModelClient()} />);
    await selectModel(user, "oscillator");
    await user.click(screen.getByTestId("create-experiment"));

    const note = await screen.findByTestId("demo-seed-note");
    expect(note).toHaveTextContent(/demonstration/i);
    expect(note).toHaveTextContent(/not a scientifically justified experiment/i);
  });

  it("explains why an ineligible model cannot create an experiment", async () => {
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
    const client = stubClient({
      listModels: vi.fn().mockResolvedValue(models),
      capabilities: vi.fn().mockResolvedValue(toy),
    });
    render(<Workspace client={client} />);

    const select = await screen.findByTestId("model-select");
    await waitFor(() =>
      expect(screen.getByTestId("model-eligibility-note")).toHaveTextContent(/no numeric parameter/),
    );
    expect(within(select).getByRole("option", { name: /toy/ })).toBeDisabled();
    expect(screen.getByTestId("create-experiment")).toBeDisabled();
  });

  it("surfaces a model-specific validation failure and keeps Run disabled", async () => {
    const user = userEvent.setup();
    const client = multiModelClient({
      validate: vi.fn().mockResolvedValue({
        ok: false,
        diagnostics: [
          {
            level: "error",
            code: "factor_out_of_bounds",
            message: "factor 'm' reaches 999 above declared upper bound 10; extrapolation is not allowed",
          },
        ],
        estimate: okValidation.estimate,
      } satisfies ValidationResult),
    });
    render(<Workspace client={client} />);
    await selectModel(user, "oscillator");
    await user.click(screen.getByTestId("create-experiment"));
    await screen.findByTestId("cap-factorable");

    await user.click(screen.getByTestId("validate-button"));
    expect(await screen.findByTestId("validation-verdict")).toHaveTextContent(/^invalid$/);
    expect(screen.getByText(/factor_out_of_bounds/)).toBeInTheDocument();
    expect(screen.getByTestId("run-button")).toBeDisabled();
  });

  it("renders results for a non-sample model and frames them as observations", async () => {
    const user = userEvent.setup();
    const oscillatorResult: ExperimentData = {
      ...succeededData(),
      model_ref: { model_id: "oscillator", version: "1.0.0" },
      comparisons: [comparison()],
    };
    const run = vi.fn().mockResolvedValue(oscillatorResult);
    const client = multiModelClient({ run });
    render(<Workspace client={client} />);
    await selectModel(user, "oscillator");
    await user.click(screen.getByTestId("create-experiment"));
    await screen.findByTestId("cap-factorable");

    await user.click(screen.getByTestId("validate-button"));
    await waitFor(() => expect(screen.getByTestId("run-button")).toBeEnabled());
    await user.click(screen.getByTestId("run-button"));

    await waitFor(() => expect(screen.getByTestId("status-value")).toHaveTextContent(/^succeeded$/));
    expect(run).toHaveBeenCalledTimes(1);
    expect(run.mock.calls[0]?.[0]).toMatchObject({ model_ref: { model_id: "oscillator" } });

    // Results are framed as observed simulation output, not scientific proof.
    expect(screen.getByTestId("observation-caveat")).toHaveTextContent(
      /not an established scientific conclusion/i,
    );

    await user.click(screen.getByRole("tab", { name: "Metrics" }));
    expect((await screen.findAllByText("max_abs_delta")).length).toBeGreaterThan(0);
  });
});

describe("preserved sample workflow", () => {
  it("still opens the predator-prey sample with its declared parameters", async () => {
    const user = userEvent.setup();
    render(<Workspace client={multiModelClient()} />);
    await user.click(await screen.findByTestId("start-sample"));
    expect(await screen.findByRole("cell", { name: "alpha" })).toBeInTheDocument();
    expect(screen.getByTestId("demo-seed-note")).toHaveTextContent(/predator-prey/);
  });
});
