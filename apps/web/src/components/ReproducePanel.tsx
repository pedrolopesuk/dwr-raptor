"use client";

import { useEffect, useState } from "react";

import { Renew } from "@carbon/icons-react";
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
import { ApiError, type DrwClient, type LoadedExperiment } from "@/lib/client";
import { formatNumber, shortHash } from "@/lib/format";
import type { ReproduceReport, ReproduceVerdict } from "@/lib/types";

const VERDICT_LABEL: Record<ReproduceVerdict, string> = {
  identical: "identical",
  equivalent_within_tolerance: "equivalent within tolerance",
  different: "different",
  inconclusive: "inconclusive",
  execution_failed: "execution failed",
};

const VERDICT_TAG: Record<ReproduceVerdict, "green" | "red" | "magenta"> = {
  identical: "green",
  equivalent_within_tolerance: "green",
  different: "red",
  inconclusive: "magenta",
  execution_failed: "red",
};

function parseTolerance(text: string): number | null {
  if (text.trim() === "") return null;
  const value = Number(text);
  if (!Number.isFinite(value) || value < 0) return null;
  return value;
}

export function ReproducePanel({
  client,
  experimentId,
}: {
  client: DrwClient;
  experimentId: string;
}) {
  const [loaded, setLoaded] = useState<LoadedExperiment | null>(null);
  const [rtolText, setRtolText] = useState("");
  const [atolText, setAtolText] = useState("");
  const [report, setReport] = useState<ReproduceReport | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [running, setRunning] = useState(false);

  useEffect(() => {
    let active = true;
    void (async () => {
      try {
        const result = await client.getExperiment(experimentId);
        if (active) setLoaded(result);
      } catch {
        if (active) setLoaded(null);
      }
    })();
    return () => {
      active = false;
    };
  }, [client, experimentId]);

  const rtol = parseTolerance(rtolText);
  const atol = parseTolerance(atolText);
  const rtolInvalid = rtolText.trim() !== "" && (rtol === null || rtol >= 1);
  const atolInvalid = atolText.trim() !== "" && atol === null;
  const canRun =
    rtol !== null && rtol < 1 && atol !== null && !rtolInvalid && !atolInvalid && !running;

  async function reproduce(): Promise<void> {
    if (!canRun || rtol === null || atol === null) return;
    setRunning(true);
    setError(null);
    setReport(null);
    try {
      setReport(await client.reproduceExperiment(experimentId, rtol, atol));
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : String(caught));
    } finally {
      setRunning(false);
    }
  }

  const storedRunIds = loaded?.results?.runs?.map((run) => run.run_id) ?? [];

  return (
    <Section
      id="reproduce-heading"
      title="Reproduce this result"
      description="Re-run the saved specification and compare the fresh execution to the stored reference. The original saved result is never overwritten."
    >
      <div className="drw-stack-tight" data-testid="reproduce-panel">
        <dl className="drw-kv">
          <div>
            <dt>Saved experiment</dt>
            <dd className="drw-mono">{experimentId}</dd>
          </div>
          <div>
            <dt>Stored reference</dt>
            <dd className="drw-mono" data-testid="reproduce-reference">
              {storedRunIds.length > 0
                ? `${storedRunIds[0]} (+${storedRunIds.length - 1} more stored run(s))`
                : "the stored reference runs"}
            </dd>
          </div>
        </dl>

        <p className="drw-hint">
          Tolerance policy (ADR-0013): a fresh output is equivalent when
          <span className="drw-mono"> |fresh - reference| &lt;= atol + rtol * |reference| </span>
          element-wise. Tolerances are required and are not inferred from the experiment&apos;s solver
          settings. Numerical agreement is not scientific validity.
        </p>

        <div className="drw-row drw-row--center">
          <TextInput
            id="reproduce-rtol"
            data-testid="reproduce-rtol"
            labelText="Relative tolerance (rtol, < 1)"
            helperText="passed if |fresh-ref| <= atol + rtol*|ref|"
            value={rtolText}
            invalid={rtolInvalid}
            invalidText="rtol must be a number >= 0 and < 1"
            onChange={(event) => setRtolText(event.target.value)}
          />
          <TextInput
            id="reproduce-atol"
            data-testid="reproduce-atol"
            labelText="Absolute tolerance (atol, >= 0)"
            helperText="absolute floor for near-zero reference values"
            value={atolText}
            invalid={atolInvalid}
            invalidText="atol must be a number >= 0"
            onChange={(event) => setAtolText(event.target.value)}
          />
        </div>

        <div className="drw-row drw-row--center">
          <Button
            renderIcon={Renew}
            onClick={() => void reproduce()}
            disabled={!canRun}
            data-testid="reproduce-button"
          >
            {running ? "Reproducing..." : "Reproduce experiment"}
          </Button>
          <span className="drw-muted">
            Re-executing the stored specification may take time; it does not modify the original.
          </span>
        </div>

        {error ? (
          <div data-testid="reproduce-error">
            <InlineNotification
              kind="error"
              lowContrast
              hideCloseButton
              title="Reproduction"
              subtitle={error}
            />
          </div>
        ) : null}

        {report ? <Report report={report} storedRunIds={storedRunIds} /> : null}
      </div>
    </Section>
  );
}

function Report({
  report,
  storedRunIds,
}: {
  report: ReproduceReport;
  storedRunIds: string[];
}) {
  return (
    <div className="drw-stack" data-testid="reproduce-report">
      <div className="drw-row drw-row--center">
        <span data-testid="reproduce-verdict">
          <Tag type={VERDICT_TAG[report.verdict]}>{VERDICT_LABEL[report.verdict]}</Tag>
        </span>
        <span className="drw-muted">
          numerical: <strong>{VERDICT_LABEL[report.numerical]}</strong> · rtol=
          {formatNumber(report.tolerances.rtol)} atol={formatNumber(report.tolerances.atol)} · fresh
          results in memory ({report.fresh_runs_persisted ? "persisted" : "not persisted"})
        </span>
      </div>

      {report.fresh_runs_persisted === false &&
      report.reference_run_ids.some((id, index) => id === report.fresh_run_ids[index]) ? (
        <p className="drw-hint" data-testid="reproduce-identity-note">
          A fresh identifier can be identical to the stored one because the deterministic experiment
          id is derived from the specification. The fresh execution exists only in memory and is
          <strong> not</strong> a separately stored run; the stored reference is unchanged.
        </p>
      ) : null}

      <div data-testid="reproduce-note">
        <InlineNotification
          kind="info"
          lowContrast
          hideCloseButton
          title="What this does and does not prove"
          subtitle="A passing check means the fresh execution reproduces the stored numbers under the tolerance you chose. It does not prove the model is scientifically correct, nor that hashes/environment are unchanged. Hash agreement is reported separately below."
        />
      </div>

      <TableContainer title="Reference vs fresh runs">
        <Table aria-label="Reference and fresh run identifiers" size="md">
          <TableHead>
            <TableRow>
              <TableHeader>#</TableHeader>
              <TableHeader>label</TableHeader>
              <TableHeader>stored reference run</TableHeader>
              <TableHeader>fresh run (not persisted)</TableHeader>
              <TableHeader>status</TableHeader>
              <TableHeader>result</TableHeader>
            </TableRow>
          </TableHead>
          <TableBody>
            {report.runs.map((run) => (
              <TableRow key={run.index}>
                <TableCell>{run.index}</TableCell>
                <TableCell>{run.label}</TableCell>
                <TableCell className="drw-mono">{run.reference_run_id}</TableCell>
                <TableCell className="drw-mono">{run.fresh_run_id ?? "—"}</TableCell>
                <TableCell>
                  {run.reference_status} / {run.fresh_status ?? "—"}
                </TableCell>
                <TableCell>
                  {run.identical
                    ? "identical"
                    : run.passes_tolerance
                      ? "within tolerance"
                      : run.comparable
                        ? "different"
                        : "incomparable"}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </TableContainer>

      <div data-testid="reproduce-metrics">
        {report.runs.map((run) => (
          <TableContainer
            key={run.index}
            title={`Outputs · run ${run.index} (${run.label})`}
          >
            <Table aria-label={`Output metrics for run ${run.index}`} size="md">
              <TableHead>
                <TableRow>
                  <TableHeader>output</TableHeader>
                  <TableHeader>unit</TableHeader>
                  <TableHeader>status</TableHeader>
                  <TableHeader className="drw-num">max abs delta</TableHeader>
                  <TableHeader className="drw-num">max rel delta</TableHeader>
                  <TableHeader className="drw-num">mae</TableHeader>
                  <TableHeader className="drw-num">rmse</TableHeader>
                  <TableHeader className="drw-num">valid / points</TableHeader>
                </TableRow>
              </TableHead>
              <TableBody>
                {run.outputs.map((output) => (
                  <TableRow key={output.output}>
                    <TableCell className="drw-mono">{output.output}</TableCell>
                    <TableCell>{output.unit}</TableCell>
                    <TableCell>{output.status}</TableCell>
                    <TableCell className="drw-num">{formatNumber(output.max_abs_delta)}</TableCell>
                    <TableCell className="drw-num">
                      {formatNumber(output.max_abs_relative_delta)}
                    </TableCell>
                    <TableCell className="drw-num">{formatNumber(output.mae)}</TableCell>
                    <TableCell className="drw-num">{formatNumber(output.rmse)}</TableCell>
                    <TableCell className="drw-num">
                      {output.valid_points ?? "—"} / {output.n_points ?? "—"}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </TableContainer>
        ))}
      </div>

      <TableContainer title="Fingerprints (reported separately from the numbers)">
        <Table aria-label="Fingerprint comparison" size="md" data-testid="reproduce-provenance">
          <TableHead>
            <TableRow>
              <TableHeader>fingerprint</TableHeader>
              <TableHeader>stored</TableHeader>
              <TableHeader>current</TableHeader>
              <TableHeader>match</TableHeader>
            </TableRow>
          </TableHead>
          <TableBody>
            <TableRow>
              <TableCell>spec hash</TableCell>
              <TableCell className="drw-mono">{shortHash(report.provenance.spec_hash_stored)}</TableCell>
              <TableCell className="drw-mono">{shortHash(report.provenance.spec_hash_current)}</TableCell>
              <TableCell>{report.provenance.spec_hash_match ? "yes" : "no"}</TableCell>
            </TableRow>
            <TableRow>
              <TableCell>model hash</TableCell>
              <TableCell className="drw-mono">{shortHash(report.provenance.model_hash_stored)}</TableCell>
              <TableCell className="drw-mono">{shortHash(report.provenance.model_hash_current)}</TableCell>
              <TableCell>{report.provenance.model_hash_match ? "yes" : "no"}</TableCell>
            </TableRow>
            <TableRow>
              <TableCell>environment hash</TableCell>
              <TableCell className="drw-mono">
                {shortHash(report.provenance.environment_hash_stored)}
              </TableCell>
              <TableCell className="drw-mono">
                {shortHash(report.provenance.environment_hash_current)}
              </TableCell>
              <TableCell>{report.provenance.environment_hash_match ? "yes" : "no"}</TableCell>
            </TableRow>
          </TableBody>
        </Table>
      </TableContainer>

      {report.warnings.length > 0 ? (
        <ul className="drw-stack-tight" data-testid="reproduce-warnings">
          {report.warnings.map((warning) => (
            <li key={warning} className="drw-hint">
              {warning}
            </li>
          ))}
        </ul>
      ) : null}

      <p className="drw-hint">
        Reference runs: {report.reference_run_ids.join(", ") || "—"} · fresh runs:{" "}
        {report.fresh_run_ids.join(", ") || "—"}
        {storedRunIds.length !== report.reference_run_ids.length
          ? " (reference run list changed since load)"
          : ""}
      </p>
    </div>
  );
}
