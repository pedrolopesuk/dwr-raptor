"use client";

import { useState } from "react";

import { Analytics } from "@carbon/icons-react";
import {
  Button,
  InlineNotification,
  Tag,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableHeader,
  TableRow,
  TextInput,
} from "@carbon/react";

import { Section } from "@/components/Section";
import { ApiError, type DrwClient } from "@/lib/client";
import { formatNumber } from "@/lib/format";
import type { ModelCapabilities, SobolReport } from "@/lib/types";

function formatCi(interval: [number, number] | null): string {
  if (!interval) return "n/a";
  return `[${formatNumber(interval[0])}, ${formatNumber(interval[1])}]`;
}

/**
 * On-demand global variance-based (Sobol) sensitivity study.
 *
 * Runs model evaluations through the Python core; it makes no probabilistic or
 * causal claim (see the caveat). Estimates are finite-sample and are reported
 * without clipping to theoretical bounds.
 *
 * `capabilities` is the model's authoritative capability metadata. It provides
 * the eligible factor set *and* the study limits (default sample count, evaluation
 * cap) from the core, so the UI holds no duplicate configuration. When it is
 * unavailable, no estimate is fabricated and the backend remains authoritative.
 */
export function GlobalSensitivityPanel({
  client,
  experimentId,
  capabilities,
}: {
  client: DrwClient;
  experimentId: string;
  capabilities: ModelCapabilities | null;
}) {
  // Authoritative study limits, sourced from the core via capabilities.
  const defaultSampleCount = capabilities?.global_sensitivity?.default_sample_count ?? null;
  const maxEvaluations = capabilities?.global_sensitivity?.max_evaluations ?? null;

  const [factorsText, setFactorsText] = useState("");
  const [output, setOutput] = useState("");
  const [nText, setNText] = useState("");
  const [seedText, setSeedText] = useState("0");
  const [report, setReport] = useState<SobolReport | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [running, setRunning] = useState(false);

  const trimmedN = nText.trim();
  // A blank N means "use the backend default"; an explicit N must be an integer >= 2.
  const specifiedN = trimmedN === "" ? null : Number(trimmedN);
  const specifiedNValid =
    specifiedN === null || (Number.isInteger(specifiedN) && specifiedN >= 2);
  const effectiveN = specifiedN ?? defaultSampleCount;

  const seed = Number(seedText);
  const seedValid = Number.isInteger(seed) && seed >= 0;

  const factors = factorsText.split(",").map((item) => item.trim()).filter(Boolean);
  const explicitFactors = factors.length > 0;
  // The backend selects all bounded numeric parameters when none are given;
  // capabilities.factorable_parameters is that exact set (derived by the core).
  const eligibleFactorCount = capabilities ? capabilities.factorable_parameters.length : null;
  const factorCount = explicitFactors ? factors.length : eligibleFactorCount;
  const estimatedEvaluations =
    effectiveN !== null &&
    Number.isInteger(effectiveN) &&
    effectiveN >= 2 &&
    factorCount !== null &&
    factorCount > 0
      ? effectiveN * (factorCount + 2)
      : null;
  const exceedsCap =
    estimatedEvaluations !== null && maxEvaluations !== null && estimatedEvaluations > maxEvaluations;
  const nonPowerOfTwo =
    effectiveN !== null && effectiveN >= 2 && (effectiveN & (effectiveN - 1)) !== 0;
  const canRun = specifiedNValid && seedValid && !running && !exceedsCap;

  const costMessage =
    estimatedEvaluations !== null ? (
      <>
        Estimated model evaluations: <strong>{formatNumber(estimatedEvaluations)}</strong> = N x (d +
        2), using d = {factorCount} {explicitFactors ? "selected" : "default bounded"} factor(s).
        This estimates model evaluations, not elapsed time.
      </>
    ) : !specifiedNValid ? (
      "N must be an integer >= 2."
    ) : effectiveN === null ? (
      "Estimated evaluation count unavailable: the backend default sample size could not be loaded. Enter N explicitly to compute the estimate."
    ) : eligibleFactorCount === null ? (
      "Estimated evaluation count unavailable: eligible-factor metadata could not be loaded. List the factors explicitly to compute the estimate."
    ) : (
      "No bounded numeric parameter is eligible, so a global-sensitivity study cannot be configured."
    );

  async function run(): Promise<void> {
    if (!canRun) return;
    setRunning(true);
    setError(null);
    setReport(null);
    try {
      setReport(
        await client.globalSensitivity(experimentId, {
          factors: factors.length > 0 ? factors : undefined,
          output: output.trim() || undefined,
          sampleCount: specifiedN ?? defaultSampleCount ?? undefined,
          seed,
        }),
      );
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : String(caught));
    } finally {
      setRunning(false);
    }
  }

  return (
    <Section
      id="sobol-heading"
      title="Global sensitivity (Sobol)"
      description="On-demand variance-based study: how much of the output variance each independent input explains (first-order S1) and including interactions (total-order ST). Runs model evaluations; the stored experiment is not modified."
    >
      <div className="drw-stack-tight" data-testid="sobol-panel">
        <p className="drw-hint" data-testid="sobol-caveat">
          Estimates assume <strong>independent inputs</strong> and are finite-sample: they are not
          exact, not causal, and a single sample size does not establish convergence. A bootstrap
          interval is a diagnostic only. Theoretical bounds are not imposed.
        </p>

        <div className="drw-row drw-row--center">
          <TextInput
            id="sobol-factors"
            data-testid="sobol-factors"
            labelText="Factors (comma-separated, optional)"
            helperText="default: all bounded numeric parameters"
            placeholder="alpha, beta"
            value={factorsText}
            onChange={(event) => setFactorsText(event.target.value)}
          />
          <TextInput
            id="sobol-output"
            data-testid="sobol-output"
            labelText="Scalar output (optional)"
            helperText="default: the primary scalar output"
            value={output}
            onChange={(event) => setOutput(event.target.value)}
          />
          <TextInput
            id="sobol-n"
            data-testid="sobol-n"
            labelText="Base sample size N"
            helperText={
              defaultSampleCount !== null
                ? `evaluations = N x (d + 2); default ${defaultSampleCount}; power of two recommended`
                : "evaluations = N x (d + 2); power of two recommended"
            }
            placeholder={defaultSampleCount !== null ? String(defaultSampleCount) : undefined}
            value={nText}
            invalid={!specifiedNValid && trimmedN !== ""}
            invalidText="N must be an integer >= 2"
            onChange={(event) => setNText(event.target.value)}
          />
          <TextInput
            id="sobol-seed"
            data-testid="sobol-seed"
            labelText="Seed"
            value={seedText}
            invalid={!seedValid && seedText.trim() !== ""}
            invalidText="seed must be a non-negative integer"
            onChange={(event) => setSeedText(event.target.value)}
          />
        </div>

        <div className="drw-row drw-row--center">
          <Button
            renderIcon={Analytics}
            onClick={() => void run()}
            disabled={!canRun}
            data-testid="sobol-run"
          >
            {running ? "Running study..." : "Run global sensitivity"}
          </Button>
        </div>

        <p className="drw-muted" data-testid="sobol-cost">
          {costMessage}
          {defaultSampleCount !== null ? ` Default N = ${defaultSampleCount}.` : ""}
          {maxEvaluations !== null
            ? ` Maximum ${formatNumber(maxEvaluations)} evaluations.`
            : ""}
        </p>

        {nonPowerOfTwo ? (
          <p className="drw-hint" data-testid="sobol-power-of-two">
            N = {effectiveN} is not a power of two: the Sobol' sequence balance properties are
            weaker and the estimates may be less accurate. A power of two (e.g. 32, 64, 128) is
            recommended.
          </p>
        ) : null}

        {exceedsCap ? (
          <div data-testid="sobol-cap">
            <InlineNotification
              kind="warning"
              lowContrast
              hideCloseButton
              title="Study exceeds the evaluation cap"
              subtitle={`The requested study would run an estimated ${formatNumber(
                estimatedEvaluations,
              )} evaluations, exceeding the maximum of ${formatNumber(
                maxEvaluations,
              )}. Reduce N or the number of factors.`}
            />
          </div>
        ) : null}

        {error ? (
          <div data-testid="sobol-error">
            <InlineNotification kind="error" lowContrast hideCloseButton title="Global sensitivity" subtitle={error} />
          </div>
        ) : null}

        {report ? <Report report={report} /> : null}
      </div>
    </Section>
  );
}

function Report({ report }: { report: SobolReport }) {
  return (
    <div className="drw-stack-tight" data-testid="sobol-report">
      <div className="drw-row drw-row--center">
        <span data-testid="sobol-verdict">
          <Tag type={report.inconclusive ? "red" : "green"}>
            {report.inconclusive ? "inconclusive" : "estimated"}
          </Tag>
        </span>
        <span className="drw-muted">
          output <strong>{report.output}</strong> · N={report.sample_count} · d={report.dimensions} ·
          seed {report.seed} · evaluations {report.evaluations_completed}/{report.evaluations_requested}
          {report.variance !== null ? ` · variance ${formatNumber(report.variance)}` : ""}
        </span>
      </div>

      {report.inconclusive ? (
        <InlineNotification
          kind="warning"
          lowContrast
          hideCloseButton
          title="Inconclusive"
          subtitle={report.reasons.join("; ") || "the study could not be estimated"}
        />
      ) : null}

      {report.results.length > 0 ? (
        <TableContainer title={`Estimator: ${report.estimator}`}>
          <Table aria-label="Sobol sensitivity indices" size="md" data-testid="sobol-table">
            <TableHead>
              <TableRow>
                <TableHeader>factor</TableHeader>
                <TableHeader className="drw-num">S1 (first-order)</TableHeader>
                <TableHeader className="drw-num">S1 95% CI</TableHeader>
                <TableHeader className="drw-num">ST (total-order)</TableHeader>
                <TableHeader className="drw-num">ST 95% CI</TableHeader>
              </TableRow>
            </TableHead>
            <TableBody>
              {report.results.map((row) => (
                <TableRow key={row.name}>
                  <TableCell className="drw-mono">{row.name}</TableCell>
                  <TableCell className="drw-num">{formatNumber(row.s1)}</TableCell>
                  <TableCell className="drw-num">{formatCi(row.s1_ci)}</TableCell>
                  <TableCell className="drw-num">{formatNumber(row.st)}</TableCell>
                  <TableCell className="drw-num">{formatCi(row.st_ci)}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </TableContainer>
      ) : null}

      {report.note ? <p className="drw-hint">{report.note}</p> : null}
    </div>
  );
}
