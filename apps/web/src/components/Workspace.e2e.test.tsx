/**
 * End-to-end test: the real UI component driven against the real Python core.
 *
 * It renders the actual `Workspace`, uses the in-process handler client (the same
 * functions the Next.js route handlers call), and executes real experiments and
 * evidence export. No HTTP server or browser is required, but nothing about the
 * science is faked.
 */

import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";

import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeAll, describe, expect, it } from "vitest";

import { Workspace } from "@/components/Workspace";
import { createDirectClient } from "@/lib/directClient";

beforeAll(() => {
  process.env.DRW_WORKSPACE = mkdtempSync(path.join(tmpdir(), "drw-web-e2e-"));
});

describe("researcher workflow (end to end)", () => {
  it("opens the sample, rejects an invalid configuration, runs, inspects and exports", async () => {
    const user = userEvent.setup();
    render(<Workspace client={createDirectClient()} />);

    // 1. Open the sample project; the model's parameters are shown.
    //    Loading spawns two Python subprocesses; allow for real process startup
    //    under parallel test load (the default 1s findBy* timeout is too short).
    await user.click(await screen.findByTestId("start-sample"));
    expect(
      await screen.findByRole("cell", { name: "alpha" }, { timeout: 60_000 }),
    ).toBeInTheDocument();
    expect(screen.getByTestId("status-value")).toHaveTextContent("idle");

    // 2. An invalid parameter cannot be executed.
    const alphaInput = screen.getByLabelText(/^alpha /);
    await user.clear(alphaInput);
    await user.type(alphaInput, "999");
    await user.click(screen.getByTestId("validate-button"));
    await waitFor(() =>
      expect(screen.getByTestId("validation-verdict")).toHaveTextContent(/^invalid$/),
    );
    expect(screen.getByText(/baseline_out_of_bounds|factor_out_of_bounds/)).toBeInTheDocument();
    expect(screen.getByTestId("run-button")).toBeDisabled();

    // 3. Restore a valid baseline and validate successfully.
    await user.clear(alphaInput);
    await user.type(alphaInput, "1.1");
    await user.click(screen.getByTestId("validate-button"));
    await waitFor(() =>
      expect(screen.getByTestId("validation-verdict")).toHaveTextContent(/^valid$/),
    );
    await waitFor(() => expect(screen.getByTestId("run-button")).toBeEnabled());
    expect(screen.getByTestId("estimate-runs")).toHaveTextContent("2");

    // 4. Run through the Python engine.
    await user.click(screen.getByTestId("run-button"));
    await waitFor(
      () => expect(screen.getByTestId("status-value")).toHaveTextContent(/^succeeded$/),
      { timeout: 120_000 },
    );

    // 5. Differential metrics come from the Python core (regression pin).
    const deltas = await screen.findAllByText(/5\.664/);
    expect(deltas.length).toBeGreaterThan(0);

    // 6. Plots render the reference/variant/delta series.
    await user.click(screen.getByRole("tab", { name: "Plots" }));
    expect(
      await screen.findByRole("img", { name: /reference, variant and delta/i }),
    ).toBeInTheDocument();

    // 7. Metrics table exposes the metric names and valid-point counts.
    await user.click(screen.getByRole("tab", { name: "Metrics" }));
    expect((await screen.findAllByText("max_abs_delta")).length).toBeGreaterThan(0);
    expect((await screen.findAllByText("valid_points")).length).toBeGreaterThan(0);

    // 8. Sensitivity ranking is computed by the shared Python implementation.
    await user.click(screen.getByRole("tab", { name: "Sensitivity" }));
    const sensitivityTable = await screen.findByTestId("sensitivity-table", undefined, {
      timeout: 120_000,
    });
    expect(within(sensitivityTable).getByRole("cell", { name: "beta" })).toBeInTheDocument();

    // 9. Reproducibility: provenance and a real evidence export.
    await user.click(screen.getByRole("tab", { name: "Reproducibility" }));
    expect(screen.getByTestId("spec-hash").textContent).toHaveLength(64);
    await user.click(screen.getByTestId("export-button"));
    expect(await screen.findByTestId("export-message", undefined, { timeout: 60_000 })).toHaveTextContent(
      /wrote .*evidence\.zip/,
    );

    // 10. Reopen the saved experiment; the stored configuration is unchanged.
    const list = screen.getByTestId("experiments-list");
    await user.click(within(list).getAllByRole("button")[0] as HTMLElement);
    expect(
      await screen.findByTestId("reopened-note", undefined, { timeout: 60_000 }),
    ).toBeInTheDocument();
    expect(screen.getByTestId("spec-preview").textContent).toContain('"alpha": 1.1');
  });
});
