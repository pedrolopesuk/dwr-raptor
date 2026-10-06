"use client";

import { useState } from "react";

import { Analytics } from "@carbon/icons-react";
import {
  Button,
  InlineNotification,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableHeader,
  TableRow,
  Tag,
  TextInput,
} from "@carbon/react";

import { Section } from "@/components/Section";
import { ApiError, type DrwClient } from "@/lib/client";
import { formatNumber } from "@/lib/format";
import type {
  IdentifiabilityDirection,
  IdentifiabilityReport,
  IdentifiabilityVerdict,
  ModelCapabilities,
} from "@/lib/types";

const VERDICT_TAG: Record<IdentifiabilityVerdict, "green" | "red" | "magenta" | "gray"> = {
  "well-conditioned": "green",
  "ill-conditioned": "magenta",
  "rank-deficient": "red",
  inconclusive: "gray",
};

/** Describe the parameters that dominate a poorly distinguishable direction. */
function describeDirection(direction: IdentifiabilityDirection): string {
  const names = Object.entries(direction.weights)
    .filter(([, weight]) => weight >= 0.1)
    .sort((a, b) => b[1] - a[1])
    .map(([name]) => name);
  if (names.length === 0) return "an unidentified combination";
  if (names.length === 1) {
    return `${names[0]} is locally poorly constrained on its own`;
  }
  const [last, ...rest] = [...names].reverse();
  return `${rest.reverse().join(", ")} and ${last} form a poorly distinguishable combination`;
}

function weightsText(weights: Record<string, number>): string {
  return Object.entries(weights)
    .sort((a, b) => b[1] - a[1])
    .map(([name, weight]) => `${name} (${weight.toFixed(2)})`)
    .join(", ");
}

/**
 * On-demand local parameter identifiability study.
 *
 * Runs finite-difference model evaluations through the Python core and reports
 * whether the declared outputs can *locally* distinguish the parameters near the
 * baseline. It is explicitly local and structural: it makes no global,
 * practical (noisy-data), causal or model-validity claim.
 *
 * `capabilities` is the model's authoritative capability metadata. It provides
 * the eligible factor set and the study limits (step scale, evaluation cap, the
 * disclosed time-series feature set) from the core, so the UI holds no duplicate
 * configuration. When it is unavailable no estimate is fabricated and the
 * backend remains authoritative.
 */
export function IdentifiabilityPanel({
  client,
  experimentId,
  capabilities,
}: {
  client: DrwClient;
  experimentId: string;
  capabilities: ModelCapabilities | null;
}) {
  const study = capabilities?.identifiability ?? null;
  const maxEvaluations = study?.max_evaluations ?? null;
  const features = study?.timeseries_features ?? null;

  const [factorsText, setFactorsText] = useState("");
  const [outputsText, setOutputsText] = useState("");
  const [stepText, setStepText] = useState("");
  const [report, setReport] = useState<IdentifiabilityReport | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [running, setRunning] = useState(false);

  const stepValid =
    stepText.trim() === "" || (Number.isFinite(Number(stepText)) && Number(stepText) > 0);

  const factors = factorsText.split(",").map((item) => item.trim()).filter(Boolean);
  const explicitFactors = factors.length > 0;
  const eligibleFactorCount = capabilities ? capabilities.factorable_parameters.length : null;
  const factorCount = explicitFactors ? factors.length : eligibleFactorCount;
  const estimatedEvaluations =
    factorCount !== null && factorCount > 0 ? 2 * factorCount + 1 : null;
  const exceedsCap =
    estimatedEvaluations !== null &&
    maxEvaluations !== null &&
    estimatedEvaluations > maxEvaluations;
  const canRun = !running && stepValid && !exceedsCap;

  const costMessage =
    estimatedEvaluations !== null ? (
      <>
        Estimated model evaluations: <strong>{formatNumber(estimatedEvaluations)}</strong> = 2 x d + 1,
        using d = {factorCount} {explicitFactors ? "selected" : "default bounded"} factor(s). Each
        evaluation produces every selected target feature.
      </>
    ) : !stepValid ? (
      "Step scale must be a positive number."
    ) : eligibleFactorCount === null ? (
      "Estimated evaluation count unavailable: capability metadata could not be loaded."
    ) : (
      "No bounded continuous parameter is eligible, so an identifiability study cannot be configured."
    );

  async function run(): Promise<void> {
    if (!canRun) return;
    setRunning(true);
    setError(null);
    setReport(null);
    try {
      const outputs = outputsText.split(",").map((item) => item.trim()).filter(Boolean);
      setReport(
        await client.identifiability(experimentId, {
          factors: factors.length > 0 ? factors : undefined,
          outputs: outputs.length > 0 ? outputs : undefined,
          stepScale: stepText.trim() === "" ? undefined : Number(stepText),
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
      id="identifiability-heading"
      title="Parameter identifiability"
      description="On-demand local study: could the selected outputs distinguish these parameters near this baseline, and which parameter combinations are effectively indistinguishable? Runs model evaluations; the stored experiment is not modified."
    >
      <div className="drw-stack-tight" data-testid="ident-panel">
        <p className="drw-hint" data-testid="ident-caveat">
          This is <strong>local, linearised structural</strong> identifiability at this baseline and
          these outputs. It is <strong>not</strong> global identifiability, not practical
          identifiability from noisy observations, and not a statement that the model is valid. A
          passing result does not establish that the parameters are correct.
        </p>
        {features ? (
          <p className="drw-muted" data-testid="ident-features">
            Time-series outputs are summarized by the fixed features: {features.join(", ")} (scalar
            outputs use their value).
          </p>
        ) : null}

        <div className="drw-row drw-row--center">
          <TextInput
            id="ident-factors"
            data-testid="ident-factors"
            labelText="Parameters (comma-separated, optional)"
            helperText="default: all bounded continuous parameters"
            placeholder="mass, stiffness"
            value={factorsText}
            onChange={(event) => setFactorsText(event.target.value)}
          />
          <TextInput
            id="ident-outputs"
            data-testid="ident-outputs"
            labelText="Outputs (comma-separated, optional)"
            helperText="default: every scalar and time-series output"
            value={outputsText}
            onChange={(event) => setOutputsText(event.target.value)}
          />
          <TextInput
            id="ident-step"
            data-testid="ident-step"
            labelText="Step scale (optional)"
            helperText={
              study ? `relative finite-difference step; default ${study.default_step_scale}` : "relative finite-difference step"
            }
            invalid={!stepValid && stepText.trim() !== ""}
            invalidText="step scale must be a positive number"
            value={stepText}
            onChange={(event) => setStepText(event.target.value)}
          />
        </div>

        <div className="drw-row drw-row--center">
          <Button
            renderIcon={Analytics}
            onClick={() => void run()}
            disabled={!canRun}
            data-testid="ident-run"
          >
            {running ? "Running study..." : "Run identifiability analysis"}
          </Button>
        </div>

        <p className="drw-muted" data-testid="ident-cost">
          {costMessage}
          {maxEvaluations !== null
            ? ` Maximum ${formatNumber(maxEvaluations)} evaluations.`
            : ""}
        </p>

        {exceedsCap ? (
          <div data-testid="ident-cap">
            <InlineNotification
              kind="warning"
              lowContrast
              hideCloseButton
              title="Study exceeds the evaluation cap"
              subtitle={`The requested study would run ${formatNumber(
                estimatedEvaluations,
              )} evaluations, exceeding the maximum of ${formatNumber(
                maxEvaluations,
              )}. Reduce the number of parameters.`}
            />
          </div>
        ) : null}

        {error ? (
          <div data-testid="ident-error">
            <InlineNotification
              kind="error"
              lowContrast
              hideCloseButton
              title="Parameter identifiability"
              subtitle={error}
            />
          </div>
        ) : null}

        {report ? <Report report={report} /> : null}
      </div>
    </Section>
  );
}

function Report({ report }: { report: IdentifiabilityReport }) {
  const problematic = report.directions.filter((direction) => direction.problematic);
  return (
    <div className="drw-stack-tight" data-testid="ident-report">
      <div className="drw-row drw-row--center">
        <span data-testid="ident-verdict">
          <Tag type={VERDICT_TAG[report.verdict]}>{report.verdict.replace(/-/g, " ")}</Tag>
        </span>
        <span className="drw-muted" data-testid="ident-metrics">
          parameters {report.dimensions} · informative targets {report.n_targets} · rank{" "}
          {report.numerical_rank ?? "n/a"}/{report.dimensions} · condition{" "}
          {formatNumber(report.condition_number)} · evaluations {report.evaluations_completed}/
          {report.evaluations_requested}
        </span>
      </div>

      {report.inconclusive ? (
        <InlineNotification
          kind="warning"
          lowContrast
          hideCloseButton
          title="Inconclusive"
          subtitle={
            report.reasons.join("; ") ||
            "insufficient valid model evaluations to establish an identifiability result"
          }
        />
      ) : null}

      {report.singular_values.length > 0 ? (
        <p className="drw-muted" data-testid="ident-singular">
          Singular values: {report.singular_values.map((value) => formatNumber(value)).join(", ")}
        </p>
      ) : null}

      {problematic.length > 0 ? (
        <div className="drw-stack-tight" data-testid="ident-directions">
          {problematic.map((direction) => (
            <p key={direction.index} className="drw-hint">
              {describeDirection(direction)} (condition index{" "}
              {formatNumber(direction.condition_index)}). Dominant weights:{" "}
              {weightsText(direction.weights)}.
            </p>
          ))}
        </div>
      ) : null}

      {report.factor_correlations.length > 0 ? (
        <div data-testid="ident-correlations">
          <TableContainer title="Strongest parameter-pair correlations">
            <Table aria-label="Parameter-pair correlations" size="sm">
              <TableHead>
                <TableRow>
                  <TableHeader>pair</TableHeader>
                  <TableHeader className="drw-num">correlation</TableHeader>
                </TableRow>
              </TableHead>
              <TableBody>
                {report.factor_correlations.map((pair) => (
                  <TableRow key={`${pair.first}:${pair.second}`}>
                    <TableCell className="drw-mono">
                      {pair.first} · {pair.second}
                    </TableCell>
                    <TableCell className="drw-num">{pair.correlation.toFixed(4)}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </TableContainer>
        </div>
      ) : null}

      <p className="drw-muted" data-testid="ident-thresholds">
        Thresholds: rank tolerance {formatNumber(report.rank_tolerance)} · condition threshold{" "}
        {formatNumber(report.condition_threshold)}.
      </p>
      {report.note ? <p className="drw-hint">{report.note}</p> : null}
    </div>
  );
}
