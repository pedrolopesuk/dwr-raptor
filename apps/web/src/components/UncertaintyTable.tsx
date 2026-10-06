"use client";

import {
  InlineNotification,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableHeader,
  TableRow,
} from "@carbon/react";

import { formatNumber } from "@/lib/format";
import type { UncertaintySummary } from "@/lib/types";

/**
 * Descriptive uncertainty summary over an experiment's sampled variants.
 *
 * Read-only presentation of stats the engine already computed; it makes no
 * probabilistic or scientific claim (see the banner).
 */
export function UncertaintyTable({ summary }: { summary: UncertaintySummary }) {
  return (
    <div className="drw-stack-tight" data-testid="uncertainty-table">
      <div data-testid="uncertainty-note">
        <InlineNotification
          kind="info"
          lowContrast
          hideCloseButton
          title="Descriptive summary only"
          subtitle="These statistics describe the sampled parameter design. They are not a probability distribution, a confidence interval, or scientific validation."
        />
      </div>

      <p className="drw-hint" data-testid="uncertainty-design">
        Sampling <strong>{summary.sampling_method}</strong> · seed {summary.seed} · variants{" "}
        {summary.requested_variants} · valid output-samples {summary.valid_output_samples} · excluded
        output-samples {summary.excluded_output_samples} · quantiles {summary.quantiles.join(", ")}{" "}
        (method <span className="drw-mono">{summary.quantile_method}</span>)
      </p>
      <p className="drw-hint">
        Variants are a per-run count; valid/excluded output-samples are summed across the declared
        scalar outputs, so the per-output <em>valid</em> column is authoritative.
      </p>
      {summary.note ? <p className="drw-hint">{summary.note}</p> : null}

      <TableContainer title="Scalar outputs (sampled design)">
        <Table aria-label="Uncertainty summary" size="md" data-testid="uncertainty-outputs">
          <TableHead>
            <TableRow>
              <TableHeader>output</TableHeader>
              <TableHeader>unit</TableHeader>
              <TableHeader className="drw-num">valid / variants</TableHeader>
              <TableHeader className="drw-num">mean</TableHeader>
              <TableHeader className="drw-num">std</TableHeader>
              <TableHeader className="drw-num">min</TableHeader>
              <TableHeader className="drw-num">max</TableHeader>
              <TableHeader className="drw-num">p05</TableHeader>
              <TableHeader className="drw-num">p50</TableHeader>
              <TableHeader className="drw-num">p95</TableHeader>
              <TableHeader>notes</TableHeader>
            </TableRow>
          </TableHead>
          <TableBody>
            {summary.outputs.map((output) => {
              const exclusions = Object.entries(output.exclusions)
                .map(([reason, count]) => `${reason}:${count}`)
                .join(", ");
              const note = output.note ?? (output.sufficient ? "—" : "insufficient samples");
              return (
                <TableRow key={output.output}>
                  <TableCell className="drw-mono">{output.output}</TableCell>
                  <TableCell>{output.unit}</TableCell>
                  <TableCell className="drw-num">
                    {output.valid_samples} / {output.requested_variants}
                  </TableCell>
                  <TableCell className="drw-num">{formatNumber(output.mean)}</TableCell>
                  <TableCell className="drw-num">{formatNumber(output.std)}</TableCell>
                  <TableCell className="drw-num">{formatNumber(output.minimum)}</TableCell>
                  <TableCell className="drw-num">{formatNumber(output.maximum)}</TableCell>
                  <TableCell className="drw-num">{formatNumber(output.p05)}</TableCell>
                  <TableCell className="drw-num">{formatNumber(output.p50)}</TableCell>
                  <TableCell className="drw-num">{formatNumber(output.p95)}</TableCell>
                  <TableCell>{exclusions ? `${note} · excluded ${exclusions}` : note}</TableCell>
                </TableRow>
              );
            })}
          </TableBody>
        </Table>
      </TableContainer>
    </div>
  );
}
