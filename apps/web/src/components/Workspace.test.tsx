import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { Workspace } from "@/components/Workspace";
import { ApiError, type DrwClient } from "@/lib/client";
import { okValidation, record, stubClient, succeededData } from "@/test/stubClient";
import type { ValidationResult } from "@/lib/types";

async function openSample(user: ReturnType<typeof userEvent.setup>, client: DrwClient) {
  render(<Workspace client={client} />);
  await user.click(await screen.findByTestId("start-sample"));
  await screen.findByRole("cell", { name: "alpha" });
}

describe("Workspace workflow states", () => {
  it("opens the sample project and shows the model parameters", async () => {
    const user = userEvent.setup();
    await openSample(user, stubClient());
    expect(screen.getByTestId("status-value")).toHaveTextContent("idle");
    expect(screen.getByRole("cell", { name: "alpha" })).toBeInTheDocument();
  });

  it("does not allow running before a successful validation", async () => {
    const user = userEvent.setup();
    await openSample(user, stubClient());
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
    await openSample(user, client);
    await user.click(screen.getByTestId("validate-button"));
    expect(await screen.findByTestId("validation-verdict")).toHaveTextContent(/^invalid$/);
    expect(screen.getByText(/factor_out_of_bounds/)).toBeInTheDocument();
    expect(screen.getByTestId("run-button")).toBeDisabled();
  });

  it("never claims success when the run fails", async () => {
    const user = userEvent.setup();
    const client = stubClient({
      run: vi.fn().mockRejectedValue(new ApiError("validation_error", "the run was rejected")),
    });
    await openSample(user, client);
    await user.click(screen.getByTestId("validate-button"));
    await screen.findByTestId("validation-verdict");
    await user.click(screen.getByTestId("run-button"));
    await waitFor(() => expect(screen.getByTestId("status-value")).toHaveTextContent("failed"));
    expect(screen.queryByTestId("export-button")).toBeNull();
  });

  it("reports cancellation", async () => {
    const user = userEvent.setup();
    const client = stubClient({
      run: vi.fn().mockRejectedValue(new ApiError("cancelled", "the request was cancelled")),
    });
    await openSample(user, client);
    await user.click(screen.getByTestId("validate-button"));
    await screen.findByTestId("validation-verdict");
    await user.click(screen.getByTestId("run-button"));
    await waitFor(() => expect(screen.getByTestId("status-value")).toHaveTextContent("cancelled"));
  });

  it("reports a timeout accurately", async () => {
    const user = userEvent.setup();
    const timedOut = succeededData();
    timedOut.runs = [record({ status: "failed", timed_out: true, error: "timeout" })];
    const client = stubClient({ run: vi.fn().mockResolvedValue(timedOut) });
    await openSample(user, client);
    await user.click(screen.getByTestId("validate-button"));
    await screen.findByTestId("validation-verdict");
    await user.click(screen.getByTestId("run-button"));
    await waitFor(() => expect(screen.getByTestId("status-value")).toHaveTextContent("timed_out"));
  });
});
