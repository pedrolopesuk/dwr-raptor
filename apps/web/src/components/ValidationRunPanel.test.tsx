import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { ValidationRunPanel, validationLevel } from "@/components/ValidationRunPanel";
import { ApiError, type DrwClient } from "@/lib/client";
import { stubClient, validationDatasetOutcome, validationOutcome } from "@/test/stubClient";

function panelClient(overrides: Partial<DrwClient> = {}): DrwClient {
  return stubClient(overrides);
}

async function configure(user: ReturnType<typeof userEvent.setup>): Promise<void> {
  await user.selectOptions(
    screen.getByTestId("val-calibration"),
    await screen.findByRole("option", { name: /cal-dddddddddddd/ }),
  );
  await user.selectOptions(
    screen.getByTestId("val-dataset"),
    await screen.findByRole("option", { name: /ds-abcabcabcabc/ }),
  );
}

describe("ValidationRunPanel", () => {
  it("runs a validation against a frozen calibration and renders the three axes", async () => {
    const user = userEvent.setup();
    const runValidation = vi.fn().mockResolvedValue({
      validation: validationOutcome(),
      ref: { validation_id: "val-eeeeeeeeeeee", result_hash: "e".repeat(64) },
    });
    render(
      <ValidationRunPanel
        client={panelClient({ runValidation })}
        experimentId="exp-000000000000"
        modelId="predator-prey"
      />,
    );

    expect(screen.getByTestId("val-run")).toBeDisabled();
    await configure(user);
    expect((screen.getByTestId("val-mapping") as HTMLTextAreaElement).value).toContain(
      "ds-abcabcabcabc",
    );

    await user.click(screen.getByTestId("val-run"));
    expect(await screen.findByTestId("val-verdict")).toHaveTextContent(/evaluated/i);
    expect(screen.getByTestId("val-axes")).toHaveTextContent(/independence verified/i);
    expect(screen.getByTestId("val-axes")).toHaveTextContent(/acceptance met/i);
    expect(screen.getByTestId("val-acceptance-0")).toHaveTextContent(/met/i);
    expect(screen.getByTestId("val-note")).toHaveTextContent(/frozen calibrated model/i);

    expect(runValidation).toHaveBeenCalledWith(
      "exp-000000000000",
      expect.objectContaining({
        persist: true,
        config: expect.objectContaining({
          model_ref: expect.objectContaining({ model_id: "predator-prey" }),
          datasets: [
            expect.objectContaining({
              independence: expect.objectContaining({ claimed_dimensions: ["dataset"] }),
            }),
          ],
        }),
      }),
    );
  });

  it("fails closed when leakage is detected and shows the failure code", async () => {
    const user = userEvent.setup();
    const outcome = validationOutcome({
      agreement_status: "failed",
      independence_status: "violated",
      acceptance_status: "not_specified",
      datasets: [
        validationDatasetOutcome({
          agreement: "failed",
          failure: "independence_violated",
          metrics: {},
          acceptance: [],
        }),
      ],
    });
    const client = panelClient({
      runValidation: vi.fn().mockResolvedValue({ validation: outcome }),
    });
    render(
      <ValidationRunPanel client={client} experimentId="exp-000000000000" modelId="predator-prey" />,
    );
    await configure(user);
    await user.click(screen.getByTestId("val-run"));

    expect(await screen.findByTestId("val-failure-0")).toHaveTextContent(/independence_violated/i);
    expect(screen.getByTestId("val-verdict")).toHaveTextContent(/failed/i);
  });

  it("shows a staleness banner when the stored result is stale", async () => {
    const user = userEvent.setup();
    const client = panelClient({
      runValidation: vi.fn().mockResolvedValue({
        validation: validationOutcome(),
        ref: { validation_id: "val-eeeeeeeeeeee", result_hash: "e".repeat(64) },
      }),
      checkValidationStaleness: vi.fn().mockResolvedValue({
        validation_id: "val-eeeeeeeeeeee",
        result_hash: "e".repeat(64),
        fresh: false,
        reasons: ["validation_dataset_missing"],
        checks: [],
      }),
    });
    render(
      <ValidationRunPanel client={client} experimentId="exp-000000000000" modelId="predator-prey" />,
    );
    await configure(user);
    await user.click(screen.getByTestId("val-run"));
    expect(await screen.findByTestId("val-staleness")).toHaveTextContent(/no longer current/i);
  });

  it("surfaces validation errors", async () => {
    const user = userEvent.setup();
    const client = panelClient({
      runValidation: vi
        .fn()
        .mockRejectedValue(new ApiError("bad_request", "the validation config is not well formed")),
    });
    render(
      <ValidationRunPanel client={client} experimentId="exp-000000000000" modelId="predator-prey" />,
    );
    await configure(user);
    await user.click(screen.getByTestId("val-run"));
    expect(await screen.findByTestId("val-error")).toHaveTextContent(/not well formed/i);
  });
});

describe("validationLevel", () => {
  it("never yields supported from a met acceptance alone", () => {
    const declared = validationOutcome({
      agreement_status: "evaluated",
      acceptance_status: "met",
      independence_status: "declared_only",
    });
    expect(validationLevel(declared)).toBe("limited");
  });

  it("supports only when agreement is evaluated and independence is verified", () => {
    const supported = validationOutcome({
      agreement_status: "evaluated",
      acceptance_status: "met",
      independence_status: "verified",
      descriptive: false,
    });
    expect(validationLevel(supported)).toBe("supported");
  });

  it("is honest about failure, inconclusiveness and descriptive runs", () => {
    expect(validationLevel(validationOutcome({ agreement_status: "failed", independence_status: "violated" }))).toBe("not_validated");
    expect(validationLevel(validationOutcome({ agreement_status: "inconclusive" }))).toBe("limited");
    expect(validationLevel(validationOutcome({ acceptance_status: "not_met" }))).toBe("descriptive");
    expect(validationLevel(validationOutcome({ descriptive: true }))).toBe("descriptive");
  });
});
