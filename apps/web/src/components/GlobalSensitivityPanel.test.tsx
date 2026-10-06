import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { GlobalSensitivityPanel } from "@/components/GlobalSensitivityPanel";
import { ApiError, type DrwClient } from "@/lib/client";
import type { ModelCapabilities } from "@/lib/types";
import { capabilities, oscillatorCapabilities, sobolReport, stubClient } from "@/test/stubClient";

function panelClient(overrides: Partial<DrwClient> = {}): DrwClient {
  return stubClient(overrides);
}

// The predator-prey fixture declares one bounded parameter; the oscillator
// fixture declares two. Both are the authoritative `factorable_parameters`
// metadata the backend uses for the default factor selection.
describe("GlobalSensitivityPanel", () => {
  it("runs a study and renders the indices with the independence caveat", async () => {
    const user = userEvent.setup();
    const globalSensitivity = vi.fn().mockResolvedValue(sobolReport());
    render(
      <GlobalSensitivityPanel
        client={panelClient({ globalSensitivity })}
        experimentId="exp-000000000000"
        capabilities={capabilities}
      />,
    );

    expect(screen.getByTestId("sobol-caveat")).toHaveTextContent(/independent inputs/i);
    await user.click(screen.getByTestId("sobol-run"));

    expect(await screen.findByTestId("sobol-verdict")).toHaveTextContent(/estimated/i);
    const table = screen.getByTestId("sobol-table");
    expect(within(table).getByRole("cell", { name: "alpha" })).toBeInTheDocument();
    expect(within(table).getByRole("cell", { name: "beta" })).toBeInTheDocument();
    expect(globalSensitivity).toHaveBeenCalledWith(
      "exp-000000000000",
      expect.objectContaining({ sampleCount: 32, seed: 0 }),
    );
  });

  it("renders an inconclusive study with its reasons", async () => {
    const user = userEvent.setup();
    const client = panelClient({
      globalSensitivity: vi.fn().mockResolvedValue(
        sobolReport({
          inconclusive: true,
          variance: null,
          results: [],
          reasons: ["output variance is zero or non-finite; the indices are undefined"],
        }),
      ),
    });
    render(
      <GlobalSensitivityPanel
        client={client}
        experimentId="exp-000000000000"
        capabilities={capabilities}
      />,
    );
    await user.click(screen.getByTestId("sobol-run"));

    expect(await screen.findByTestId("sobol-verdict")).toHaveTextContent(/inconclusive/i);
    expect(screen.getByTestId("sobol-report")).toHaveTextContent(/variance is zero/i);
  });

  it("surfaces request errors", async () => {
    const user = userEvent.setup();
    const client = panelClient({
      globalSensitivity: vi
        .fn()
        .mockRejectedValue(new ApiError("bad_request", "unknown factor 'nope'")),
    });
    render(
      <GlobalSensitivityPanel
        client={client}
        experimentId="exp-000000000000"
        capabilities={capabilities}
      />,
    );
    await user.click(screen.getByTestId("sobol-run"));

    expect(await screen.findByTestId("sobol-error")).toHaveTextContent(/unknown factor/i);
  });

  it("disables the run button for an invalid sample size", async () => {
    const user = userEvent.setup();
    render(
      <GlobalSensitivityPanel
        client={panelClient()}
        experimentId="exp-000000000000"
        capabilities={capabilities}
      />,
    );
    await user.clear(screen.getByTestId("sobol-n"));
    await user.type(screen.getByTestId("sobol-n"), "1");
    expect(screen.getByTestId("sobol-run")).toBeDisabled();
  });

  it("estimates the cost from the backend default factor selection when factors are blank", () => {
    render(
      <GlobalSensitivityPanel
        client={panelClient()}
        experimentId="exp-000000000000"
        capabilities={oscillatorCapabilities}
      />,
    );
    // 2 default bounded factors at the backend default N=32 -> 32 * (2 + 2) = 128.
    const cost = screen.getByTestId("sobol-cost");
    expect(cost).toHaveTextContent(/Estimated model evaluations:\s*128/);
    expect(cost).toHaveTextContent(/d = 2/);
    expect(cost).toHaveTextContent(/default bounded factor/i);
    expect(cost).toHaveTextContent(/Default N = 32/);
    expect(cost).toHaveTextContent(/Maximum 4096 evaluations/);
  });

  it("uses the backend-provided study limits instead of hard-coded values", async () => {
    const user = userEvent.setup();
    const customLimits: ModelCapabilities = {
      ...oscillatorCapabilities,
      global_sensitivity: { default_sample_count: 16, max_evaluations: 1000 },
    };
    render(
      <GlobalSensitivityPanel
        client={panelClient()}
        experimentId="exp-000000000000"
        capabilities={customLimits}
      />,
    );
    // The default N and cap come from capabilities, not from a UI constant.
    const cost = screen.getByTestId("sobol-cost");
    expect(cost).toHaveTextContent(/Estimated model evaluations:\s*64/); // 16 * (2 + 2)
    expect(cost).toHaveTextContent(/Default N = 16/);
    expect(cost).toHaveTextContent(/Maximum 1000 evaluations/);

    await user.clear(screen.getByTestId("sobol-n"));
    await user.type(screen.getByTestId("sobol-n"), "300");
    // 300 * (2 + 2) = 1200 > 1000 -> capped by the backend-provided limit.
    expect(screen.getByTestId("sobol-cap")).toHaveTextContent(/1200/);
    expect(screen.getByTestId("sobol-run")).toBeDisabled();
  });

  it("uses the explicit factor selection for the estimate", async () => {
    const user = userEvent.setup();
    render(
      <GlobalSensitivityPanel
        client={panelClient()}
        experimentId="exp-000000000000"
        capabilities={oscillatorCapabilities}
      />,
    );
    await user.type(screen.getByTestId("sobol-factors"), "alpha, beta, delta");
    // Explicit selection of 3 factors -> 32 * (3 + 2) = 160.
    const cost = screen.getByTestId("sobol-cost");
    expect(cost).toHaveTextContent(/Estimated model evaluations:\s*160/);
    expect(cost).toHaveTextContent(/d = 3/);
    expect(cost).toHaveTextContent(/selected factor/i);
  });

  it("updates the estimate when the sample size changes", async () => {
    const user = userEvent.setup();
    render(
      <GlobalSensitivityPanel
        client={panelClient()}
        experimentId="exp-000000000000"
        capabilities={oscillatorCapabilities}
      />,
    );
    await user.clear(screen.getByTestId("sobol-n"));
    await user.type(screen.getByTestId("sobol-n"), "64");
    // 64 * (2 + 2) = 256.
    expect(screen.getByTestId("sobol-cost")).toHaveTextContent(/Estimated model evaluations:\s*256/);
  });

  it("pre-validates the study size and disables run when it exceeds the cap", async () => {
    const user = userEvent.setup();
    const globalSensitivity = vi.fn();
    render(
      <GlobalSensitivityPanel
        client={panelClient({ globalSensitivity })}
        experimentId="exp-000000000000"
        capabilities={oscillatorCapabilities}
      />,
    );
    await user.clear(screen.getByTestId("sobol-n"));
    await user.type(screen.getByTestId("sobol-n"), "2048");
    // 2048 * (2 + 2) = 8192 > 4096.
    expect(screen.getByTestId("sobol-cap")).toHaveTextContent(/8192/);
    expect(screen.getByTestId("sobol-cap")).toHaveTextContent(/maximum of 4096/);
    expect(screen.getByTestId("sobol-run")).toBeDisabled();
    expect(globalSensitivity).not.toHaveBeenCalled();
  });

  it("does not invent an estimate when capability metadata is unavailable", () => {
    render(
      <GlobalSensitivityPanel
        client={panelClient()}
        experimentId="exp-000000000000"
        capabilities={null}
      />,
    );
    const cost = screen.getByTestId("sobol-cost");
    expect(cost).toHaveTextContent(/unavailable/i);
    expect(cost).not.toHaveTextContent(/Estimated model evaluations:/);
    expect(cost).not.toHaveTextContent(/Default N =/);
    // Without metadata the UI cannot pre-validate; the backend remains authoritative.
    expect(screen.getByTestId("sobol-run")).toBeEnabled();
  });

  it("computes the estimate from explicit N and factors without metadata", async () => {
    const user = userEvent.setup();
    render(
      <GlobalSensitivityPanel
        client={panelClient()}
        experimentId="exp-000000000000"
        capabilities={null}
      />,
    );
    await user.type(screen.getByTestId("sobol-n"), "32");
    await user.type(screen.getByTestId("sobol-factors"), "alpha");
    // 1 explicit factor at an explicitly entered N -> 32 * (1 + 2) = 96.
    expect(screen.getByTestId("sobol-cost")).toHaveTextContent(/Estimated model evaluations:\s*96/);
  });

  it("flags a non-power-of-two sample size", async () => {
    const user = userEvent.setup();
    render(
      <GlobalSensitivityPanel
        client={panelClient()}
        experimentId="exp-000000000000"
        capabilities={oscillatorCapabilities}
      />,
    );
    expect(screen.queryByTestId("sobol-power-of-two")).toBeNull();
    await user.clear(screen.getByTestId("sobol-n"));
    await user.type(screen.getByTestId("sobol-n"), "100");
    expect(screen.getByTestId("sobol-power-of-two")).toHaveTextContent(/not a power of two/i);
  });
});
