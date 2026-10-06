import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { DatasetImportPanel } from "@/components/DatasetImportPanel";
import { ApiError, type DrwClient } from "@/lib/client";
import { csvInspection, datasetImportResult, stubClient } from "@/test/stubClient";

function panelClient(overrides: Partial<DrwClient> = {}): DrwClient {
  return stubClient(overrides);
}

describe("DatasetImportPanel", () => {
  it("inspects a source, shows advisory structure, and imports with explicit configuration", async () => {
    const user = userEvent.setup();
    const inspectDataset = vi.fn().mockResolvedValue(csvInspection());
    const importDataset = vi
      .fn()
      .mockImplementation((_filename: string, _config: unknown, dryRun?: boolean) =>
        Promise.resolve(datasetImportResult({ dry_run: Boolean(dryRun), stored: !dryRun })),
      );
    const onImported = vi.fn();
    render(
      <DatasetImportPanel
        client={panelClient({ inspectDataset, importDataset })}
        onImported={onImported}
      />,
    );

    expect(screen.getByTestId("dataset-advisory")).toHaveTextContent(/advisory/i);

    await user.selectOptions(
      screen.getByTestId("dataset-source"),
      await screen.findByRole("option", { name: "lightcurve.csv" }),
    );
    await user.click(screen.getByTestId("dataset-inspect"));

    expect(await screen.findByTestId("dataset-preview")).toBeInTheDocument();
    // Suggestions prefill the role but stay editable.
    expect(screen.getByTestId("dataset-role-time")).toHaveValue("coordinate");
    expect(screen.getByTestId("dataset-role-flux")).toHaveValue("measurement");

    // Explicit unit assignment.
    await user.type(screen.getByLabelText("unit", { selector: "#dataset-unit-flux" }), "Jy");

    await user.click(screen.getByTestId("dataset-validate"));
    expect(importDataset).toHaveBeenCalledWith(
      "lightcurve.csv",
      expect.objectContaining({
        name: "lightcurve",
        columns: expect.arrayContaining([
          expect.objectContaining({ column: "flux", role: "measurement", unit: "Jy" }),
        ]),
      }),
      true,
    );
    expect(await screen.findByTestId("dataset-result")).toHaveTextContent(/validated/i);

    await user.click(screen.getByTestId("dataset-import"));
    expect(importDataset).toHaveBeenLastCalledWith(
      "lightcurve.csv",
      expect.any(Object),
      false,
    );
    expect(await screen.findByTestId("dataset-result")).toHaveTextContent(/imported/i);
    expect(onImported).toHaveBeenCalled();
  });

  it("surfaces an invalid configuration", async () => {
    const user = userEvent.setup();
    const importDataset = vi
      .fn()
      .mockRejectedValue(new ApiError("bad_request", "config references unknown column 'x'"));
    render(<DatasetImportPanel client={panelClient({ importDataset })} />);

    await user.selectOptions(
      screen.getByTestId("dataset-source"),
      await screen.findByRole("option", { name: "lightcurve.csv" }),
    );
    await user.click(screen.getByTestId("dataset-inspect"));
    await screen.findByTestId("dataset-preview");
    await user.click(screen.getByTestId("dataset-import"));

    expect(await screen.findByTestId("dataset-error")).toHaveTextContent(/unknown column/i);
  });

  it("surfaces an inspection error", async () => {
    const user = userEvent.setup();
    const inspectDataset = vi.fn().mockRejectedValue(new ApiError("not_found", "source file not found"));
    render(<DatasetImportPanel client={panelClient({ inspectDataset })} />);

    await user.selectOptions(
      screen.getByTestId("dataset-source"),
      await screen.findByRole("option", { name: "lightcurve.csv" }),
    );
    await user.click(screen.getByTestId("dataset-inspect"));

    expect(await screen.findByTestId("dataset-error")).toHaveTextContent(/not found/i);
    expect(screen.queryByTestId("dataset-preview")).toBeNull();
  });
});
