"use client";

import { useState } from "react";

import { Download } from "@carbon/icons-react";
import {
  Button,
  InlineNotification,
  Select,
  SelectItem,
  Tab,
  TabList,
  TabPanel,
  TabPanels,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableHeader,
  TableRow,
  Tabs,
  Tag,
} from "@carbon/react";

import { Diagnostics } from "@/components/Diagnostics";
import { Section } from "@/components/Section";
import { LineChart } from "@/components/LineChart";
import { formatDuration, formatNumber, shortHash } from "@/lib/format";
import { runIssues } from "@/lib/experiment";
import type {
  Comparison,
  EnvironmentData,
  EvidenceData,
  ExperimentData,
  SensitivityData,
} from "@/lib/types";

const STATUS_TAG: Record<string, "green" | "red" | "magenta" | "gray"> = {
  succeeded: "green",
  failed: "red",
};

// Series colours use Carbon support tokens and are additionally distinguished by
// line style, so meaning is never carried by colour alone.
// Colours come from the Carbon data-visualization palette (defined per theme in
// globals.scss) and are additionally distinguished by line style.
const SERIES = {
  reference: "var(--drw-series-reference)",
  variant: "var(--drw-series-variant)",
  delta: "var(--drw-series-delta)",
};

export function ResultsView({
  data,
  sensitivity,
  sensitivityError,
  environment,
  onExport,
  exporting,
  exportMessage,
}: {
  data: ExperimentData;
  sensitivity: SensitivityData | null;
  sensitivityError: string | null;
  environment: EnvironmentData | null;
  onExport: () => void;
  exporting: boolean;
  exportMessage: string | null;
}) {
  return (
    <Section
      id="results-heading"
      title="Results"
      description={
        <>
          Experiment <span className="drw-mono">{data.experiment_id}</span> · isolation{" "}
          {data.isolation} · spec hash <span className="drw-mono">{shortHash(data.spec_hash)}</span>
        </>
      }
    >
      <Tabs>
        <TabList aria-label="Result sections" contained>
          <Tab>Overview</Tab>
          <Tab>Plots</Tab>
          <Tab>Metrics</Tab>
          <Tab>Sensitivity</Tab>
          <Tab>Reproducibility</Tab>
        </TabList>
        <TabPanels>
          <TabPanel className="drw-tabpanel">
            <div data-testid="overview-panel">
              <Overview data={data} />
            </div>
          </TabPanel>
          <TabPanel className="drw-tabpanel">
            <div data-testid="plots-panel">
              <Plots data={data} />
            </div>
          </TabPanel>
          <TabPanel className="drw-tabpanel">
            <div data-testid="metrics-panel">
              <Metrics data={data} />
            </div>
          </TabPanel>
          <TabPanel className="drw-tabpanel">
            <div data-testid="sensitivity-panel">
              <Sensitivity data={sensitivity} error={sensitivityError} />
            </div>
          </TabPanel>
          <TabPanel className="drw-tabpanel">
            <div data-testid="reproducibility-panel">
              <Reproducibility
                data={data}
                environment={environment}
                onExport={onExport}
                exporting={exporting}
                exportMessage={exportMessage}
              />
            </div>
          </TabPanel>
        </TabPanels>
      </Tabs>
    </Section>
  );
}

function Overview({ data }: { data: ExperimentData }) {
  const warnings = [
    ...data.warnings,
    ...data.runs.flatMap((run) => run.diagnostics.filter((d) => d.level !== "info")),
  ];
  return (
    <div className="drw-stack">
      <div data-testid="observation-caveat">
        <InlineNotification
          kind="info"
          lowContrast
          hideCloseButton
          title="What this result is"
          subtitle="These are simulated outputs for the model, baseline and intervention you configured. A delta shows what changed under this configuration - it is an observed simulation result, not an established scientific conclusion. Interpretation requires domain reasoning and independent validation."
        />
      </div>

      <div>
        <h3 className="drw-subheading">Hypothesis</h3>
        <p>{data.hypothesis}</p>
      </div>

      <dl className="drw-kv drw-kv--stat">
        <div>
          <dt>Runs succeeded</dt>
          <dd>
            {data.runs.filter((run) => run.status === "succeeded").length} / {data.runs.length}
          </dd>
        </div>
        <div>
          <dt>Comparisons</dt>
          <dd>{data.comparisons.length}</dd>
        </div>
        <div>
          <dt>Warnings</dt>
          <dd>{warnings.length}</dd>
        </div>
      </dl>

      <TableContainer title="Runs" description="Baseline first, then interventions">
        <Table aria-label="Runs" size="md" useZebraStyles>
          <TableHead>
            <TableRow>
              <TableHeader>run</TableHeader>
              <TableHeader>label</TableHeader>
              <TableHeader>status</TableHeader>
              <TableHeader>isolation</TableHeader>
              <TableHeader className="drw-num">duration</TableHeader>
              <TableHeader>issues</TableHeader>
            </TableRow>
          </TableHead>
          <TableBody>
            {data.runs.map((run) => {
              const issues = runIssues(run);
              return (
                <TableRow key={run.run_id}>
                  <TableCell className="drw-mono">{run.run_id}</TableCell>
                  <TableCell>{run.label}</TableCell>
                  <TableCell>
                    <Tag type={STATUS_TAG[run.status] ?? "gray"}>{run.status}</Tag>
                  </TableCell>
                  <TableCell>{run.isolation}</TableCell>
                  <TableCell className="drw-num">{formatDuration(run.duration_s)}</TableCell>
                  <TableCell>{issues.length > 0 ? issues.join("; ") : "—"}</TableCell>
                </TableRow>
              );
            })}
          </TableBody>
        </Table>
      </TableContainer>

      <TableContainer title="Comparisons">
        <Table aria-label="Comparisons" size="md">
          <TableHead>
            <TableRow>
              <TableHeader>variant</TableHeader>
              <TableHeader>output</TableHeader>
              <TableHeader>method</TableHeader>
              <TableHeader className="drw-num">max abs delta</TableHeader>
              <TableHeader className="drw-num">mae</TableHeader>
              <TableHeader>alignment</TableHeader>
            </TableRow>
          </TableHead>
          <TableBody>
            {data.comparisons.length === 0 ? (
              <TableRow>
                <TableCell colSpan={6}>No comparisons (no successful variant).</TableCell>
              </TableRow>
            ) : (
              data.comparisons.map((comparison) => (
                <TableRow
                  key={`${comparison.variant_run_id}-${comparison.output}-${comparison.method}`}
                >
                  <TableCell className="drw-mono">{comparison.variant_run_id}</TableCell>
                  <TableCell>{comparison.output}</TableCell>
                  <TableCell>{comparison.method}</TableCell>
                  <TableCell className="drw-num">
                    {formatNumber(comparison.metrics["max_abs_delta"])}
                  </TableCell>
                  <TableCell className="drw-num">{formatNumber(comparison.metrics["mae"])}</TableCell>
                  <TableCell>
                    {comparison.alignment}
                    {comparison.interpolated ? " (interpolated)" : ""}
                  </TableCell>
                </TableRow>
              ))
            )}
          </TableBody>
        </Table>
      </TableContainer>

      <div>
        <h3 className="drw-subheading">Warnings and diagnostics</h3>
        <Diagnostics diagnostics={warnings} />
      </div>
    </div>
  );
}

function Plots({ data }: { data: ExperimentData }) {
  const outputs = Array.from(new Set(data.comparisons.map((c) => c.output)));
  const [output, setOutput] = useState<string>(outputs[0] ?? "");
  const comparison = data.comparisons.find((c) => c.output === output) ?? data.comparisons[0];
  if (!comparison || outputs.length === 0) {
    return <p className="drw-muted">No comparison data to plot.</p>;
  }
  return (
    <div className="drw-stack-tight">
      <div className="drw-select-narrow">
        <Select
          id="plot-output"
          labelText="Output"
          value={output}
          onChange={(event) => setOutput(event.target.value)}
        >
          {outputs.map((name) => (
            <SelectItem key={name} value={name} text={name} />
          ))}
        </Select>
      </div>

      <LineChart
        axis={comparison.axis}
        ariaLabel={`${comparison.output}: reference, variant and delta`}
        yLabel={`${comparison.output} (${comparison.unit})`}
        xLabel="time"
        series={[
          {
            name: "reference (baseline)",
            color: SERIES.reference,
            values: comparison.reference,
          },
          {
            name: "variant (intervention)",
            color: SERIES.variant,
            values: comparison.variant,
          },
          {
            name: "delta (variant - reference)",
            color: SERIES.delta,
            values: comparison.delta,
            dashed: true,
          },
        ]}
      />

      <p className="drw-muted">
        Alignment: <strong>{comparison.alignment}</strong>
        {comparison.interpolated
          ? " - interpolation was applied and may change conclusions."
          : " - compared on identical coordinates."}
      </p>
      {comparison.warnings.length > 0 ? <Diagnostics diagnostics={comparison.warnings} /> : null}
    </div>
  );
}

function Metrics({ data }: { data: ExperimentData }) {
  if (data.comparisons.length === 0) return <p className="drw-muted">No metrics available.</p>;
  return (
    <div className="drw-stack">
      {data.comparisons.map((comparison) => (
        <ComparisonMetrics
          key={`${comparison.variant_run_id}-${comparison.output}-${comparison.method}`}
          comparison={comparison}
        />
      ))}
    </div>
  );
}

function ComparisonMetrics({ comparison }: { comparison: Comparison }) {
  return (
    <TableContainer
      title={`${comparison.output} (${comparison.unit}) vs ${comparison.variant_run_id}`}
    >
      <Table aria-label={`Metrics for ${comparison.output}`} size="md">
        <TableHead>
          <TableRow>
            <TableHeader>metric</TableHeader>
            <TableHeader className="drw-num">value</TableHeader>
          </TableRow>
        </TableHead>
        <TableBody>
          {Object.entries(comparison.metrics).map(([name, value]) => (
            <TableRow key={name}>
              <TableCell className="drw-mono">{name}</TableCell>
              <TableCell className="drw-num">{formatNumber(value)}</TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
      {comparison.warnings.length > 0 ? <Diagnostics diagnostics={comparison.warnings} /> : null}
    </TableContainer>
  );
}

function Sensitivity({
  data,
  error,
}: {
  data: SensitivityData | null;
  error: string | null;
}) {
  if (error) {
    return (
      <InlineNotification
        kind="error"
        lowContrast
        hideCloseButton
        title="Sensitivity"
        subtitle={`Could not be computed: ${error}`}
      />
    );
  }
  if (!data) return <p className="drw-muted">Computing sensitivity...</p>;
  return (
    <div className="drw-stack-tight">
      <p className="drw-hint">
        One-at-a-time +{data.perturbation} influence on <strong>{data.metric}</strong>. This is
        local OAT sensitivity, not global variance-based analysis. Absolute delta is
        scale-dependent; <strong>elasticity</strong> (relative output change / relative input
        change) is the normalized comparison. OAT cannot detect interactions.
      </p>
      <TableContainer>
        <Table aria-label="Sensitivity ranking" size="md" data-testid="sensitivity-table">
          <TableHead>
            <TableRow>
              <TableHeader>parameter</TableHeader>
              <TableHeader className="drw-num">baseline</TableHeader>
              <TableHeader className="drw-num">perturbed</TableHeader>
              <TableHeader className="drw-num">abs delta</TableHeader>
              <TableHeader className="drw-num">elasticity</TableHeader>
              <TableHeader>notes</TableHeader>
            </TableRow>
          </TableHead>
          <TableBody>
            {data.ranking.map((row) => (
              <TableRow key={row.parameter}>
                <TableCell className="drw-mono">{row.parameter}</TableCell>
                <TableCell className="drw-num">{formatNumber(row.baseline_value)}</TableCell>
                <TableCell className="drw-num">{formatNumber(row.perturbed_value)}</TableCell>
                <TableCell className="drw-num">{formatNumber(row.abs_delta)}</TableCell>
                <TableCell className="drw-num">{formatNumber(row.elasticity)}</TableCell>
                <TableCell>{row.clamped ? "clamped to bounds" : "—"}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </TableContainer>
    </div>
  );
}

function Reproducibility({
  data,
  environment,
  onExport,
  exporting,
  exportMessage,
}: {
  data: ExperimentData;
  environment: EnvironmentData | null;
  onExport: () => void;
  exporting: boolean;
  exportMessage: string | null;
}) {
  const evidence: EvidenceData | undefined = data.evidence;
  const environmentEntries = Object.entries(environment?.environment ?? {}).sort(([a], [b]) =>
    a.localeCompare(b),
  );
  return (
    <div className="drw-stack">
      <dl className="drw-kv">
        <div>
          <dt>Spec hash</dt>
          <dd className="drw-mono" data-testid="spec-hash">
            {data.spec_hash}
          </dd>
        </div>
        <div>
          <dt>Model hash</dt>
          <dd className="drw-mono">{data.model_hash}</dd>
        </div>
        <div>
          <dt>Environment hash</dt>
          <dd className="drw-mono">{environment?.environment_hash ?? "—"}</dd>
        </div>
        <div>
          <dt>Isolation</dt>
          <dd>{data.isolation} (process boundary, not a sandbox)</dd>
        </div>
      </dl>

      <TableContainer title="Environment">
        <Table aria-label="Environment fingerprint" size="md">
          <TableBody>
            {environmentEntries.length === 0 ? (
              <TableRow>
                <TableCell>Environment fingerprint unavailable.</TableCell>
              </TableRow>
            ) : (
              environmentEntries.map(([key, value]) => (
                <TableRow key={key}>
                  <TableCell className="drw-mono">{key}</TableCell>
                  <TableCell className="drw-mono">{value}</TableCell>
                </TableRow>
              ))
            )}
          </TableBody>
        </Table>
      </TableContainer>

      <div>
        <h3 className="drw-subheading">Evidence package</h3>
        {evidence ? (
          <>
            <p className="drw-muted">
              {evidence.files.length} files · the manifest lists the SHA-256 of each artifact.
            </p>
            <TableContainer>
              <Table aria-label="Evidence files" size="md">
                <TableHead>
                  <TableRow>
                    <TableHeader>file</TableHeader>
                    <TableHeader>kind</TableHeader>
                    <TableHeader>sha256</TableHeader>
                    <TableHeader className="drw-num">bytes</TableHeader>
                  </TableRow>
                </TableHead>
                <TableBody>
                  {evidence.files.map((file) => (
                    <TableRow key={file.path}>
                      <TableCell className="drw-mono">{file.path}</TableCell>
                      <TableCell>{file.kind}</TableCell>
                      <TableCell className="drw-mono">{shortHash(file.sha256, 16)}</TableCell>
                      <TableCell className="drw-num">{file.size_bytes}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </TableContainer>

            <div className="drw-row drw-row--center">
              <Button renderIcon={Download} onClick={onExport} disabled={exporting} data-testid="export-button">
                {exporting ? "Exporting..." : "Export evidence (.zip)"}
              </Button>
              {exportMessage ? (
                <span className="drw-muted" data-testid="export-message">
                  {exportMessage}
                </span>
              ) : null}
            </div>

            <h4 className="drw-subheading">Report</h4>
            <pre className="drw-pre" tabIndex={0} aria-label="Evidence report">
              {evidence.report}
            </pre>
          </>
        ) : (
          <p className="drw-muted">No evidence package is attached to this result.</p>
        )}
      </div>
    </div>
  );
}
