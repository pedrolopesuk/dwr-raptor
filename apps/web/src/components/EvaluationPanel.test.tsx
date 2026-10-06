import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { EvaluationPanel } from "@/components/EvaluationPanel";
import { ApiError, type DrwClient } from "@/lib/client";
import { evaluationResult, stubClient } from "@/test/stubClient";

function panelClient(overrides: Partial<DrwClient> = {}): DrwClient {
  return stubClient(overrides);
}

describe("EvaluationPanel", () => {
  it("evaluates a stored run against a dataset and renders metrics", async () => {
    const user = userEvent.setup();
    const evaluate = vi.fn().mockResolvedValue(evaluationResult());
    render(
      <EvaluationPanel
        client={panelClient({ evaluate })}
        experimentId="exp-000000000000"
        modelId="predator-prey"
        runs={[]}
      />,
    );

    expect(screen.getByText(/never fits or infers/i)).toBeInTheDocument();

    await user.selectOptions(
      screen.getByTestId("eval-dataset"),
      await screen.findByRole("option", { name: /ds-abcabcabcabc/ }),
    );
    // Selecting a dataset prefills the mapping with its exact reference.
    expect((screen.getByTestId("eval-mapping") as HTMLTextAreaElement).value).toContain(
      "ds-abcabcabcabc",
    );

    await user.click(screen.getByTestId("eval-run-button"));
    expect(await screen.findByTestId("eval-verdict")).toHaveTextContent(/evaluated/i);
    expect(screen.getByTestId("eval-metrics-table")).toHaveTextContent("peak_prey");
    expect(screen.getByTestId("eval-metrics-0")).toHaveTextContent(/mae: 1/);
    expect(screen.getByTestId("eval-exclusions-0")).toHaveTextContent(/missing/);
    expect(screen.getByTestId("eval-provenance")).toHaveTextContent(/dataset/);
    expect(evaluate).toHaveBeenCalledWith(
      "exp-000000000000",
      expect.objectContaining({ runId: "baseline" }),
    );
  });

  it("renders a fail-closed result without metrics", async () => {
    const user = userEvent.setup();
    const client = panelClient({
      evaluate: vi.fn().mockResolvedValue(
        evaluationResult({
          ok: false,
          pairs: [],
          total_usable: 0,
          diagnostics: [
            { level: "error", code: "no_usable_observations", message: "no usable comparisons remain" },
          ],
        }),
      ),
    });
    render(
      <EvaluationPanel client={client} experimentId="exp-000000000000" modelId="predator-prey" runs={[]} />,
    );
    await user.selectOptions(
      screen.getByTestId("eval-dataset"),
      await screen.findByRole("option", { name: /ds-abcabcabcabc/ }),
    );
    await user.click(screen.getByTestId("eval-run-button"));

    expect(await screen.findByTestId("eval-verdict")).toHaveTextContent(/not valid/i);
    expect(screen.getByTestId("eval-result")).toHaveTextContent(/no usable comparisons/i);
  });

  it("surfaces evaluation errors", async () => {
    const user = userEvent.setup();
    const client = panelClient({
      evaluate: vi.fn().mockRejectedValue(new ApiError("bad_request", "the mapping is not well formed")),
    });
    render(
      <EvaluationPanel client={client} experimentId="exp-000000000000" modelId="predator-prey" runs={[]} />,
    );
    await user.selectOptions(
      screen.getByTestId("eval-dataset"),
      await screen.findByRole("option", { name: /ds-abcabcabcabc/ }),
    );
    await user.click(screen.getByTestId("eval-run-button"));

    expect(await screen.findByTestId("eval-error")).toHaveTextContent(/not well formed/i);
  });
});
