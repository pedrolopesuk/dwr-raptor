import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { IdentifiabilityPanel } from "@/components/IdentifiabilityPanel";
import { ApiError, type DrwClient } from "@/lib/client";
import type { ModelCapabilities } from "@/lib/types";
import {
  capabilities,
  identifiabilityReport,
  oscillatorCapabilities,
  stubClient,
} from "@/test/stubClient";

function panelClient(overrides: Partial<DrwClient> = {}): DrwClient {
  return stubClient(overrides);
}

describe("IdentifiabilityPanel", () => {
  it("runs a study and renders the verdict, rank and analysis", async () => {
    const user = userEvent.setup();
    const identifiability = vi.fn().mockResolvedValue(identifiabilityReport());
    render(
      <IdentifiabilityPanel
        client={panelClient({ identifiability })}
        experimentId="exp-000000000000"
        capabilities={capabilities}
      />,
    );

    expect(screen.getByTestId("ident-caveat")).toHaveTextContent(/local/i);
    expect(screen.getByTestId("ident-caveat")).toHaveTextContent(/not global identifiability/i);
    await user.click(screen.getByTestId("ident-run"));

    expect(await screen.findByTestId("ident-verdict")).toHaveTextContent(/rank deficient/i);
    expect(screen.getByTestId("ident-metrics")).toHaveTextContent(/rank 1\/2/);
    expect(screen.getByTestId("ident-singular")).toHaveTextContent(/83\.4588/);
    // The problematic combination is described in words, not as an absolute claim.
    expect(screen.getByTestId("ident-directions")).toHaveTextContent(
      /beta and predator0 form a poorly distinguishable combination/i,
    );
    expect(screen.getByTestId("ident-correlations")).toHaveTextContent(/beta · predator0/);
    expect(identifiability).toHaveBeenCalledWith(
      "exp-000000000000",
      expect.objectContaining({}),
    );
  });

  it("renders a well-conditioned verdict with no problematic directions", async () => {
    const user = userEvent.setup();
    const client = panelClient({
      identifiability: vi.fn().mockResolvedValue(
        identifiabilityReport({
          verdict: "well-conditioned",
          numerical_rank: 2,
          condition_number: 3.4,
          directions: [],
          factor_correlations: [],
          evaluations_requested: 5,
          evaluations_completed: 5,
        }),
      ),
    });
    render(
      <IdentifiabilityPanel
        client={client}
        experimentId="exp-000000000000"
        capabilities={capabilities}
      />,
    );
    await user.click(screen.getByTestId("ident-run"));

    expect(await screen.findByTestId("ident-verdict")).toHaveTextContent(/well conditioned/i);
    expect(screen.getByTestId("ident-metrics")).toHaveTextContent(/rank 2\/2/);
    expect(screen.queryByTestId("ident-directions")).toBeNull();
  });

  it("renders an ill-conditioned verdict", async () => {
    const user = userEvent.setup();
    const client = panelClient({
      identifiability: vi.fn().mockResolvedValue(
        identifiabilityReport({
          verdict: "ill-conditioned",
          numerical_rank: 2,
          condition_number: 4.2e6,
          factor_correlations: [],
          directions: [
            {
              index: 1, singular_value: 0.02, condition_index: 4.2e6, problematic: true,
              dominant: ["a"], weights: { a: 0.8, b: 0.6 },
            },
          ],
        }),
      ),
    });
    render(
      <IdentifiabilityPanel
        client={client}
        experimentId="exp-000000000000"
        capabilities={capabilities}
      />,
    );
    await user.click(screen.getByTestId("ident-run"));

    expect(await screen.findByTestId("ident-verdict")).toHaveTextContent(/ill conditioned/i);
    expect(screen.getByTestId("ident-metrics")).toHaveTextContent(/condition 4200000/);
  });

  it("renders an inconclusive study with its reasons", async () => {
    const user = userEvent.setup();
    const client = panelClient({
      identifiability: vi.fn().mockResolvedValue(
        identifiabilityReport({
          verdict: "inconclusive",
          inconclusive: true,
          numerical_rank: null,
          singular_values: [],
          directions: [],
          factor_correlations: [],
          reasons: ["factor 'm' cannot be perturbed: central difference needs a valid step"],
        }),
      ),
    });
    render(
      <IdentifiabilityPanel
        client={client}
        experimentId="exp-000000000000"
        capabilities={capabilities}
      />,
    );
    await user.click(screen.getByTestId("ident-run"));

    expect(await screen.findByTestId("ident-verdict")).toHaveTextContent(/inconclusive/i);
    expect(screen.getByTestId("ident-report")).toHaveTextContent(/cannot be perturbed/i);
  });

  it("surfaces request errors", async () => {
    const user = userEvent.setup();
    const client = panelClient({
      identifiability: vi
        .fn()
        .mockRejectedValue(new ApiError("bad_request", "unknown factor 'nope'")),
    });
    render(
      <IdentifiabilityPanel
        client={client}
        experimentId="exp-000000000000"
        capabilities={capabilities}
      />,
    );
    await user.click(screen.getByTestId("ident-run"));

    expect(await screen.findByTestId("ident-error")).toHaveTextContent(/unknown factor/i);
  });

  it("estimates the cost from the default factor selection (2 x d + 1)", () => {
    render(
      <IdentifiabilityPanel
        client={panelClient()}
        experimentId="exp-000000000000"
        capabilities={oscillatorCapabilities}
      />,
    );
    // 2 default bounded factors -> 2 * 2 + 1 = 5.
    const cost = screen.getByTestId("ident-cost");
    expect(cost).toHaveTextContent(/Estimated model evaluations:\s*5/);
    expect(cost).toHaveTextContent(/d = 2/);
    expect(cost).toHaveTextContent(/maximum 4096|Maximum 4096/i);
  });

  it("updates the cost for an explicit parameter selection", async () => {
    const user = userEvent.setup();
    render(
      <IdentifiabilityPanel
        client={panelClient()}
        experimentId="exp-000000000000"
        capabilities={oscillatorCapabilities}
      />,
    );
    await user.type(screen.getByTestId("ident-factors"), "a, b, c");
    expect(screen.getByTestId("ident-cost")).toHaveTextContent(/Estimated model evaluations:\s*7/);
  });

  it("uses the backend-provided cap instead of a hard-coded value", () => {
    const customLimits: ModelCapabilities = {
      ...oscillatorCapabilities,
      identifiability: {
        method: "central_finite_difference_sensitivity_svd",
        default_step_scale: 0.001,
        condition_threshold: 1_000_000,
        max_evaluations: 4,
        timeseries_features: ["max", "min", "mean", "final", "argmax_t"],
      },
    };
    render(
      <IdentifiabilityPanel
        client={panelClient()}
        experimentId="exp-000000000000"
        capabilities={customLimits}
      />,
    );
    // 2 factors -> 5 evaluations > cap 4.
    expect(screen.getByTestId("ident-cap")).toHaveTextContent(/5/);
    expect(screen.getByTestId("ident-cap")).toHaveTextContent(/4/);
    expect(screen.getByTestId("ident-run")).toBeDisabled();
  });

  it("does not invent an estimate when capability metadata is unavailable", () => {
    render(
      <IdentifiabilityPanel
        client={panelClient()}
        experimentId="exp-000000000000"
        capabilities={null}
      />,
    );
    const cost = screen.getByTestId("ident-cost");
    expect(cost).toHaveTextContent(/unavailable/i);
    expect(cost).not.toHaveTextContent(/Estimated model evaluations:/);
    expect(screen.getByTestId("ident-run")).toBeEnabled();
  });

  it("displays the disclosed time-series feature set", () => {
    render(
      <IdentifiabilityPanel
        client={panelClient()}
        experimentId="exp-000000000000"
        capabilities={oscillatorCapabilities}
      />,
    );
    const features = screen.getByTestId("ident-features");
    for (const feature of ["max", "min", "mean", "final", "argmax_t"]) {
      expect(features).toHaveTextContent(feature);
    }
  });

  it("disables run for an invalid step scale", async () => {
    const user = userEvent.setup();
    render(
      <IdentifiabilityPanel
        client={panelClient()}
        experimentId="exp-000000000000"
        capabilities={oscillatorCapabilities}
      />,
    );
    await user.type(screen.getByTestId("ident-step"), "0");
    expect(screen.getByTestId("ident-run")).toBeDisabled();
  });
});
