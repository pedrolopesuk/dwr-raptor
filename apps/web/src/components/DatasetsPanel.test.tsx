import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { DatasetsPanel } from "@/components/DatasetsPanel";
import type { DrwClient } from "@/lib/client";
import { datasetDetail, datasetVerification, stubClient } from "@/test/stubClient";

function panelClient(overrides: Partial<DrwClient> = {}): DrwClient {
  return stubClient(overrides);
}

describe("DatasetsPanel", () => {
  it("lists datasets and shows the detail, variables and verification", async () => {
    const user = userEvent.setup();
    const describeDataset = vi.fn().mockResolvedValue(datasetDetail());
    const verifyDataset = vi.fn().mockResolvedValue(datasetVerification());
    render(<DatasetsPanel client={panelClient({ describeDataset, verifyDataset })} />);

    expect(await screen.findByTestId("datasets-list")).toHaveTextContent("ds-abcabcabcabc");
    expect(screen.getByTestId("datasets-list")).toHaveTextContent("file");

    await user.click(screen.getByTestId("dataset-row-ds-abcabcabcabc"));
    expect(describeDataset).toHaveBeenCalledWith("ds-abcabcabcabc");

    const detail = await screen.findByTestId("dataset-detail");
    expect(detail).toHaveTextContent("flux");
    expect(screen.getByTestId("dataset-variables")).toHaveTextContent("Jy");
    expect(screen.getByTestId("dataset-variables")).toHaveTextContent("std");
    expect(screen.getByTestId("dataset-verification")).toHaveTextContent("meta");

    await user.click(screen.getByTestId("dataset-verify"));
    expect(verifyDataset).toHaveBeenCalledWith("ds-abcabcabcabc");
  });

  it("shows an empty state when there are no datasets", async () => {
    render(
      <DatasetsPanel client={panelClient({ listDatasets: vi.fn().mockResolvedValue([]) })} />,
    );
    expect(await screen.findByTestId("datasets-empty")).toBeInTheDocument();
  });

  it("flags a failed verification", async () => {
    const user = userEvent.setup();
    const detail = datasetDetail({
      verification: datasetVerification({
        ok: false,
        errors: 1,
        checks: [{ name: "content_hash", status: "mismatch", message: "content hash mismatch" }],
      }),
    });
    render(<DatasetsPanel client={panelClient({ describeDataset: vi.fn().mockResolvedValue(detail) })} />);

    await user.click(await screen.findByTestId("dataset-row-ds-abcabcabcabc"));
    expect(await screen.findByTestId("dataset-detail")).toHaveTextContent(/verification failed/i);
    expect(screen.getByTestId("dataset-verification")).toHaveTextContent(/mismatch/i);
  });
});
