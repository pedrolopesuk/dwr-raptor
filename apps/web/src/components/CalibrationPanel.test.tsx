import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { CalibrationPanel } from "@/components/CalibrationPanel";
import { ApiError, type DrwClient } from "@/lib/client";
import { calibrationResult, schema, stubClient } from "@/test/stubClient";

function panelClient(overrides: Partial<DrwClient> = {}): DrwClient {
  return stubClient(overrides);
}

async function configure(user: ReturnType<typeof userEvent.setup>): Promise<void> {
  await user.selectOptions(
    screen.getByTestId("calib-dataset"),
    await screen.findByRole("option", { name: /ds-abcabcabcabc/ }),
  );
  await user.click(screen.getByTestId("calib-free-alpha"));
}

describe("CalibrationPanel", () => {
  it("calibrates selected free parameters and renders the result", async () => {
    const user = userEvent.setup();
    const calibrate = vi.fn().mockResolvedValue({ calibration: calibrationResult() });
    render(
      <CalibrationPanel
        client={panelClient({ calibrate })}
        experimentId="exp-000000000000"
        schema={schema}
      />,
    );

    expect(screen.getByText(/point estimate only/i)).toBeInTheDocument();
    // The run button is disabled until a dataset is chosen and a parameter is free.
    expect(screen.getByTestId("calib-run")).toBeDisabled();
    await configure(user);
    expect((screen.getByTestId("calib-mapping") as HTMLTextAreaElement).value).toContain(
      "ds-abcabcabcabc",
    );

    await user.click(screen.getByTestId("calib-run"));
    expect(await screen.findByTestId("calib-status")).toHaveTextContent(/converged/i);
    expect(screen.getByTestId("calib-best")).toHaveTextContent(/alpha/);
    expect(screen.getByTestId("calib-note")).toHaveTextContent(/point estimate/i);
    expect(calibrate).toHaveBeenCalledWith(
      "exp-000000000000",
      expect.objectContaining({
        config: expect.objectContaining({
          objective: expect.objectContaining({ metric: "rmse" }),
          free: [expect.objectContaining({ name: "alpha" })],
        }),
      }),
    );
  });

  it("shows no best fit when the calibration fails", async () => {
    const user = userEvent.setup();
    const client = panelClient({
      calibrate: vi.fn().mockResolvedValue({
        calibration: calibrationResult({
          status: "failed",
          converged: false,
          best: null,
          diagnostics: [{ level: "error", code: "all_candidates_failed", message: "no usable candidate" }],
        }),
      }),
    });
    render(<CalibrationPanel client={client} experimentId="exp-000000000000" schema={schema} />);
    await configure(user);
    await user.click(screen.getByTestId("calib-run"));

    expect(await screen.findByTestId("calib-status")).toHaveTextContent(/failed/i);
    expect(screen.getByTestId("calib-result")).toHaveTextContent(/no best fit/i);
  });

  it("surfaces calibration errors", async () => {
    const user = userEvent.setup();
    const client = panelClient({
      calibrate: vi.fn().mockRejectedValue(new ApiError("bad_request", "the calibration config is not well formed")),
    });
    render(<CalibrationPanel client={client} experimentId="exp-000000000000" schema={schema} />);
    await configure(user);
    await user.click(screen.getByTestId("calib-run"));
    expect(await screen.findByTestId("calib-error")).toHaveTextContent(/not well formed/i);
  });
});
