/**
 * End-to-end test: the real routed UI driven against the real Python core.
 *
 * It renders the actual project shell and pages, uses the in-process handler
 * client (the same functions the Next.js route handlers call), and executes
 * real experiments and evidence export. No HTTP server or browser is needed,
 * but nothing about the science is faked.
 */

import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";

import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeAll, describe, expect, it } from "vitest";

import { createDirectClient } from "@/lib/directClient";
import { __getPath } from "@/test/next-navigation";
import { renderApp } from "@/test/renderApp";

beforeAll(() => {
  process.env.DRW_WORKSPACE = mkdtempSync(path.join(tmpdir(), "drw-web-e2e-"));
});

const LONG = { timeout: 120_000 };

describe("researcher workflow (end to end)", () => {
  it("starts an investigation, rejects an invalid configuration, runs, inspects and exports", async () => {
    const user = userEvent.setup();
    renderApp(createDirectClient(), "/projects/default/investigations/draft/overview");

    // 1. Start the sample investigation (spawns real Python subprocesses).
    await user.click(await screen.findByTestId("open-sample", undefined, LONG));
    expect(await screen.findByTestId("investigation-question", undefined, LONG)).toBeInTheDocument();

    // 2. The model page exposes its declared parameters.
    const invNav = () => screen.getByRole("navigation", { name: "Investigation" });
    await user.click(within(invNav()).getByRole("link", { name: "Model" }));
    await user.click(await screen.findByRole("tab", { name: "Parameters" }));
    expect(await screen.findByRole("cell", { name: /alpha/ })).toBeInTheDocument();

    // 3. Configuration: an invalid parameter cannot be executed.
    await user.click(within(invNav()).getByRole("link", { name: "Experiments" }));
    await user.click(await screen.findByRole("link", { name: "Configuration" }));
    const alphaInput = await screen.findByLabelText(/^alpha /);
    await user.clear(alphaInput);
    await user.type(alphaInput, "999");
    await user.click(screen.getByTestId("validate-button"));
    await waitFor(
      () => expect(screen.getByTestId("validation-verdict")).toHaveTextContent(/^invalid$/),
      LONG,
    );
    expect(screen.getByText(/baseline_out_of_bounds|factor_out_of_bounds/)).toBeInTheDocument();
    expect(screen.getByTestId("run-button")).toBeDisabled();

    // 4. Restore a valid baseline, validate and run through the Python engine.
    await user.clear(alphaInput);
    await user.type(alphaInput, "1.1");
    await user.click(screen.getByTestId("validate-button"));
    await waitFor(
      () => expect(screen.getByTestId("validation-verdict")).toHaveTextContent(/^valid$/),
      LONG,
    );
    await waitFor(() => expect(screen.getByTestId("run-button")).toBeEnabled(), LONG);
    expect(screen.getByTestId("estimate-runs")).toHaveTextContent("2");
    await user.click(screen.getByTestId("run-button"));

    // 5. The investigation now has a stored identity and its runs are listed.
    await waitFor(() => expect(__getPath()).toMatch(/investigations\/exp-[0-9a-f]+\/experiments$/), LONG);
    expect(await screen.findByTestId("runs-list", undefined, LONG)).toBeInTheDocument();
    await waitFor(() => expect(screen.getByTestId("status-value")).toHaveTextContent(/^succeeded$/), LONG);

    // 6. Results: differential metrics come from the Python core (regression pin).
    await user.click(screen.getByRole("link", { name: "Results" }));
    const deltas = await screen.findAllByText(/5\.664/, undefined, LONG);
    expect(deltas.length).toBeGreaterThan(0);
    await user.click(screen.getByRole("tab", { name: "Plots" }));
    expect(
      await screen.findByRole("img", { name: /reference, variant and delta/i }, LONG),
    ).toBeInTheDocument();
    await user.click(screen.getByRole("tab", { name: "Metrics" }));
    expect((await screen.findAllByText("max_abs_delta", undefined, LONG)).length).toBeGreaterThan(0);
    await user.click(screen.getByRole("tab", { name: "Sensitivity" }));
    const sensitivityTable = await screen.findByTestId("sensitivity-table", undefined, LONG);
    expect(within(sensitivityTable).getByRole("cell", { name: "beta" })).toBeInTheDocument();

    // 7. Evidence: hashes, provenance and a real evidence export.
    await user.click(within(invNav()).getByRole("link", { name: "Evidence" }));
    const chain = await screen.findByTestId("evidence-chain", undefined, LONG);
    expect(within(chain).getByTestId("spec-hash-full").textContent).toHaveLength(64);
    await user.click(await screen.findByTestId("export-button", undefined, LONG));
    expect(await screen.findByTestId("export-message", undefined, LONG)).toHaveTextContent(
      /wrote .*evidence\.zip/,
    );

    // 8. The stored investigation is listed, and reopening it keeps its configuration.
    const stored = __getPath().match(/(exp-[0-9a-f]+)/)?.[1];
    expect(stored).toBeTruthy();
    await user.click(
      within(screen.getByRole("navigation", { name: "Project" })).getByRole("link", { name: "Investigations" }),
    );
    const list = await screen.findByTestId("investigations-list", undefined, LONG);
    await user.click(within(list).getAllByRole("link")[0] as HTMLElement);
    await waitFor(() => expect(__getPath()).toContain(`${stored}/overview`), LONG);
    expect(await screen.findByTestId("investigation-question", undefined, LONG)).toBeInTheDocument();
  });
});
