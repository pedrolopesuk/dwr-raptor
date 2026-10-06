import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { ReproducePanel } from "@/components/ReproducePanel";
import { ApiError, type DrwClient } from "@/lib/client";
import {
  reproduceReport,
  sampleSpec,
  stubClient,
  succeededData,
} from "@/test/stubClient";
import type { ExperimentSummary, ReproduceVerdict } from "@/lib/types";

const meta: ExperimentSummary = {
  experiment_id: "exp-000000000000",
  project_id: "default",
  name: "sample",
  hypothesis: "h",
  model_id: "predator-prey",
  isolation: "subprocess",
  spec_hash: "a".repeat(64),
  n_runs: 2,
  n_succeeded: 2,
  n_failed: 0,
  created_at: null,
  warnings: [],
};

function panelClient(overrides: Partial<DrwClient> = {}): DrwClient {
  return stubClient({
    getExperiment: vi.fn().mockResolvedValue({ meta, spec: sampleSpec, results: succeededData() }),
    ...overrides,
  });
}

async function fillTolerances(user: ReturnType<typeof userEvent.setup>) {
  await user.type(await screen.findByTestId("reproduce-rtol"), "0");
  await user.type(screen.getByTestId("reproduce-atol"), "0");
}

describe("ReproducePanel", () => {
  it("shows the entry point and states the original is not overwritten", async () => {
    render(<ReproducePanel client={panelClient()} experimentId="exp-000000000000" />);
    expect(await screen.findByTestId("reproduce-panel")).toBeInTheDocument();
    await waitFor(() =>
      expect(screen.getByTestId("reproduce-reference")).toHaveTextContent(/exp-000000000000-r0000/),
    );
    expect(screen.getByText(/never overwritten/i)).toBeInTheDocument();
    expect(screen.getByTestId("reproduce-button")).toBeDisabled();
  });

  it("requires explicit, valid tolerances before running", async () => {
    const user = userEvent.setup();
    render(<ReproducePanel client={panelClient()} experimentId="exp-000000000000" />);

    await user.type(await screen.findByTestId("reproduce-rtol"), "1");
    await user.type(screen.getByTestId("reproduce-atol"), "0");
    expect(screen.getByTestId("reproduce-button")).toBeDisabled();

    await user.clear(screen.getByTestId("reproduce-rtol"));
    await user.type(screen.getByTestId("reproduce-rtol"), "0");
    await waitFor(() => expect(screen.getByTestId("reproduce-button")).toBeEnabled());
  });

  it("runs and renders metrics, fingerprints and the validity caveat", async () => {
    const user = userEvent.setup();
    render(<ReproducePanel client={panelClient()} experimentId="exp-000000000000" />);
    await fillTolerances(user);
    await user.click(screen.getByTestId("reproduce-button"));

    expect(await screen.findByTestId("reproduce-verdict")).toHaveTextContent("identical");
    expect(screen.getAllByText("prey").length).toBeGreaterThan(0);
    expect(screen.getByTestId("reproduce-provenance")).toBeInTheDocument();
    expect(screen.getByTestId("reproduce-note")).toHaveTextContent(/does not prove/i);
  });

  const verdicts: ReproduceVerdict[] = [
    "identical",
    "equivalent_within_tolerance",
    "different",
    "inconclusive",
    "execution_failed",
  ];
  it.each(verdicts)("renders the %s verdict", async (verdict) => {
    const user = userEvent.setup();
    const client = panelClient({
      reproduceExperiment: vi.fn().mockResolvedValue(
        reproduceReport({
          verdict,
          numerical: verdict === "execution_failed" ? "inconclusive" : verdict,
        }),
      ),
    });
    render(<ReproducePanel client={client} experimentId="exp-000000000000" />);
    await fillTolerances(user);
    await user.click(screen.getByTestId("reproduce-button"));

    const expected = verdict.replace(/_/g, " ");
    expect(await screen.findByTestId("reproduce-verdict")).toHaveTextContent(expected);
  });

  it("reports provenance differences separately from the numerical verdict", async () => {
    const user = userEvent.setup();
    const client = panelClient({
      reproduceExperiment: vi.fn().mockResolvedValue(
        reproduceReport({
          provenance: {
            ...reproduceReport().provenance,
            model_hash_match: false,
            differences: ["the model implementation fingerprint has changed since this experiment"],
          },
          warnings: ["the model implementation fingerprint has changed since this experiment"],
        }),
      ),
    });
    render(<ReproducePanel client={client} experimentId="exp-000000000000" />);
    await fillTolerances(user);
    await user.click(screen.getByTestId("reproduce-button"));

    expect(await screen.findByTestId("reproduce-provenance")).toHaveTextContent(/model hash.*no/i);
    expect(screen.getByTestId("reproduce-warnings")).toHaveTextContent(/fingerprint has changed/i);
  });

  it("surfaces request errors", async () => {
    const user = userEvent.setup();
    const client = panelClient({
      reproduceExperiment: vi
        .fn()
        .mockRejectedValue(new ApiError("bad_request", "invalid tolerances")),
    });
    render(<ReproducePanel client={client} experimentId="exp-000000000000" />);
    await fillTolerances(user);
    await user.click(screen.getByTestId("reproduce-button"));

    expect(await screen.findByTestId("reproduce-error")).toHaveTextContent(/invalid tolerances/i);
  });

  it("distinguishes the stored reference from the in-memory fresh execution", async () => {
    const user = userEvent.setup();
    render(<ReproducePanel client={panelClient()} experimentId="exp-000000000000" />);
    await fillTolerances(user);
    await user.click(screen.getByTestId("reproduce-button"));

    expect(await screen.findByTestId("reproduce-identity-note")).toHaveTextContent(
      /not a separately stored run/i,
    );
    expect(screen.getByTestId("reproduce-report")).toHaveTextContent(/in memory \(not persisted\)/i);
    expect(screen.getByText("stored reference run")).toBeInTheDocument();
    expect(screen.getByText("fresh run (not persisted)")).toBeInTheDocument();
  });
});
