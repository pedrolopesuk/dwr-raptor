import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { UncertaintyTable } from "@/components/UncertaintyTable";
import { uncertaintySummary } from "@/test/stubClient";

describe("UncertaintyTable", () => {
  it("renders the descriptive statistics and labels them as descriptive only", () => {
    render(<UncertaintyTable summary={uncertaintySummary()} />);

    expect(screen.getByTestId("uncertainty-note")).toHaveTextContent(
      /not a probability distribution/i,
    );
    const design = screen.getByTestId("uncertainty-design");
    expect(design).toHaveTextContent(/latin_hypercube/);
    expect(design).toHaveTextContent(/seed 5/);
    expect(design).toHaveTextContent(/variants 3/);
    expect(design).toHaveTextContent(/valid output-samples 3/);
    expect(design).toHaveTextContent(/method\s+linear/);

    const table = screen.getByTestId("uncertainty-outputs");
    expect(within(table).getByRole("cell", { name: "peak_prey" })).toBeInTheDocument();
    expect(within(table).getByRole("cell", { name: "3 / 3" })).toBeInTheDocument();
    expect(within(table).getByRole("columnheader", { name: /valid \/ variants/i })).toBeInTheDocument();
  });

  it("shows insufficient samples and exclusion reasons explicitly", () => {
    render(
      <UncertaintyTable
        summary={uncertaintySummary({
          requested_variants: 2,
          valid_output_samples: 1,
          excluded_output_samples: 1,
          outputs: [
            {
              output: "peak_prey",
              unit: "count",
              requested_variants: 2,
              valid_samples: 1,
              excluded_samples: 1,
              exclusions: { run_failed: 1 },
              sufficient: false,
              mean: 5,
              std: null,
              minimum: 5,
              maximum: 5,
              p05: 5,
              p50: 5,
              p95: 5,
              note: "fewer than two valid samples: standard deviation is undefined",
            },
          ],
        })}
      />,
    );

    const table = screen.getByTestId("uncertainty-outputs");
    expect(within(table).getByText(/run_failed:1/)).toBeInTheDocument();
    expect(within(table).getByText(/fewer than two valid samples/)).toBeInTheDocument();
  });
});
