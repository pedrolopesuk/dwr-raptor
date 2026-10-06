"use client";

import { useEffect, useMemo, useState } from "react";

import {
  Button,
  Checkbox,
  InlineNotification,
  Select,
  SelectItem,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableHeader,
  TableRow,
  Tag,
  TextArea,
  TextInput,
} from "@carbon/react";

import { LineChart } from "@/components/LineChart";
import { Section } from "@/components/Section";
import { ApiError, type DrwClient } from "@/lib/client";
import { formatNumber } from "@/lib/format";
import type {
  DatasetSummary,
  EvaluationConfig,
  EvaluationResult,
  PairEvaluation,
} from "@/lib/types";

function mappingTemplate(dataset: DatasetSummary, modelId: string): string {
  return JSON.stringify(
    {
      dataset: { dataset_id: dataset.dataset_id, content_hash: dataset.content_hash },
      model_ref: { model_id: modelId },
      pairs: [{ observation: "", output: "", coordinates: [] }],
    },
    null,
    2,
  );
}

function pairSeries(pair: PairEvaluation) {
  const axis = pair.points.map((point, index) => point.coordinate ?? point.observation_index ?? index);
  return {
    axis,
    series: [
      { name: "observed", color: "#6929c4", values: pair.points.map((p) => p.observed) },
      { name: "predicted", color: "#0f62fe", values: pair.points.map((p) => p.predicted), dashed: true },
    ],
  };
}

/**
 * Observation <-> model evaluation (M12A).
 *
 * Evaluates an already-stored run against a dataset under an explicit mapping.
 * Read-only and execution-free: it never runs a model, never fits parameters and
 * never infers uncertainty. Any scientifically invalid comparison fails closed.
 */
export function EvaluationPanel({
  client,
  experimentId,
  modelId,
  runs,
  refreshToken = 0,
}: {
  client: DrwClient;
  experimentId: string;
  modelId: string;
  runs: { run_id: string; label: string }[];
  refreshToken?: number;
}) {
  const [datasets, setDatasets] = useState<DatasetSummary[]>([]);
  const [datasetId, setDatasetId] = useState("");
  const [runId, setRunId] = useState("baseline");
  const [mappingText, setMappingText] = useState("");
  const [relative, setRelative] = useState(false);
  const [weighted, setWeighted] = useState(false);
  const [interpolate, setInterpolate] = useState(false);
  const [tolerance, setTolerance] = useState("0");
  const [timeOrigin, setTimeOrigin] = useState("");
  const [result, setResult] = useState<EvaluationResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    void (async () => {
      try {
        setDatasets(await client.listDatasets());
      } catch {
        setDatasets([]);
      }
    })();
  }, [client, refreshToken]);

  const selectedDataset = useMemo(
    () => datasets.find((item) => item.dataset_id === datasetId) ?? null,
    [datasets, datasetId],
  );

  function chooseDataset(next: string): void {
    setDatasetId(next);
    const dataset = datasets.find((item) => item.dataset_id === next);
    if (dataset) setMappingText(mappingTemplate(dataset, modelId));
  }

  function buildConfig(): EvaluationConfig {
    const metrics = ["mean_residual", "mae", "rmse", "max_abs_error"];
    const residual_modes = ["raw"];
    if (relative) {
      metrics.push("relative_mae", "relative_rmse", "max_abs_relative_error");
      residual_modes.push("relative");
    }
    if (weighted) {
      metrics.push("weighted_rmse", "chi_square");
      residual_modes.push("normalized");
    }
    const config: EvaluationConfig = {
      metrics,
      residual_modes,
      alignment: interpolate ? "interpolate" : "exact",
      alignment_tolerance: Number(tolerance) || 0,
    };
    if (timeOrigin.trim()) config.time_origin = timeOrigin.trim();
    return config;
  }

  async function evaluate(): Promise<void> {
    setBusy(true);
    setError(null);
    setResult(null);
    try {
      const mapping = JSON.parse(mappingText);
      setResult(await client.evaluate(experimentId, { runId, mapping, config: buildConfig() }));
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : caught instanceof Error ? caught.message : String(caught));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Section
      id="evaluation-heading"
      title="Evaluate against dataset"
      description="Compare an already-stored model run against a dataset under an explicit mapping. Read-only and execution-free; it never fits or infers."
    >
      <div className="drw-stack-tight" data-testid="evaluation-panel">
        <div className="drw-formgrid">
          <Select
            id="eval-dataset"
            data-testid="eval-dataset"
            labelText="Dataset"
            value={datasetId}
            onChange={(event) => chooseDataset(event.target.value)}
          >
            <SelectItem value="" text="— select —" />
            {datasets.map((dataset) => (
              <SelectItem
                key={dataset.dataset_id}
                value={dataset.dataset_id}
                text={`${dataset.name} (${dataset.dataset_id})`}
              />
            ))}
          </Select>
          <Select
            id="eval-run"
            data-testid="eval-run"
            labelText="Run"
            value={runId}
            onChange={(event) => setRunId(event.target.value)}
          >
            <SelectItem value="baseline" text="baseline" />
            {runs.map((run) => (
              <SelectItem key={run.run_id} value={run.run_id} text={`${run.label} (${run.run_id})`} />
            ))}
          </Select>
        </div>

        <TextArea
          id="eval-mapping"
          labelText="Mapping (ObservationMapping JSON)"
          helperText="Pairs each observed variable with a model output, with the coordinates to match on."
          data-testid="eval-mapping"
          rows={8}
          value={mappingText}
          onChange={(event) => setMappingText(event.target.value)}
          placeholder='{"dataset": {...}, "model_ref": {...}, "pairs": [...]}'
        />

        <fieldset className="drw-optset">
          <legend className="drw-optset__legend">Options</legend>
          <div className="drw-optset__row">
            <Checkbox id="eval-relative" labelText="relative metrics" data-testid="eval-relative" checked={relative} onChange={(_e, { checked }) => setRelative(checked)} />
            <Checkbox id="eval-weighted" labelText="weighted metrics" data-testid="eval-weighted" checked={weighted} onChange={(_e, { checked }) => setWeighted(checked)} />
            <Checkbox id="eval-interpolate" labelText="interpolate" data-testid="eval-interpolate" checked={interpolate} onChange={(_e, { checked }) => setInterpolate(checked)} />
          </div>
        </fieldset>

        <div className="drw-formgrid drw-formgrid--run">
          <TextInput id="eval-tolerance" data-testid="eval-tolerance" labelText="Tolerance" value={tolerance} onChange={(e) => setTolerance(e.target.value)} />
          <TextInput id="eval-origin" data-testid="eval-origin" labelText="Time origin (ISO-8601)" value={timeOrigin} onChange={(e) => setTimeOrigin(e.target.value)} />
          <Button onClick={() => void evaluate()} disabled={!datasetId || busy} data-testid="eval-run-button">
            Evaluate
          </Button>
        </div>

        {error ? (
          <div data-testid="eval-error">
            <InlineNotification kind="error" lowContrast hideCloseButton title="Evaluation" subtitle={error} />
          </div>
        ) : null}

        {result ? <Report result={result} /> : null}
      </div>
    </Section>
  );
}

function Report({ result }: { result: EvaluationResult }) {
  return (
    <div className="drw-stack-tight" data-testid="eval-result">
      <div className="drw-row drw-row--center">
        <span data-testid="eval-verdict">
          <Tag type={result.ok ? "green" : "red"}>{result.ok ? "evaluated" : "not valid"}</Tag>
        </span>
        <span className="drw-muted">
          run {result.run_id} · dataset {result.dataset.dataset_id} · usable {result.total_usable} · excluded{" "}
          {result.total_excluded} · hash {result.evaluation_hash.slice(0, 12)}…
        </span>
      </div>

      {!result.ok ? (
        <InlineNotification
          kind="warning"
          lowContrast
          hideCloseButton
          title="Fail-closed"
          subtitle={result.diagnostics.map((d) => d.message).join("; ") || "the comparison was not valid"}
        />
      ) : null}

      {result.pairs.map((pair, index) => (
        <div key={`${pair.observation}-${pair.output}-${index}`} className="drw-stack-tight">
          <p className="drw-hint" data-testid={`eval-pair-${index}`}>
            <strong>
              {pair.observation} → {pair.output}
            </strong>{" "}
            ({pair.kind}, {pair.unit}, {pair.alignment}) · usable {pair.usable_count} · excluded{" "}
            {pair.excluded_count}
            {pair.interpolated ? " · interpolated" : ""}
          </p>
          <div className="drw-row drw-row--center" data-testid={`eval-metrics-${index}`}>
            {Object.entries(pair.metrics).map(([name, value]) => (
              <span key={name} className="drw-muted">
                {name}: {formatNumber(value)}
              </span>
            ))}
          </div>
          {pair.points.length > 1 ? (
            <div data-testid={`eval-chart-${index}`}>
              {(() => {
                const { axis, series } = pairSeries(pair);
                return (
                  <LineChart
                    axis={axis}
                    series={series}
                    ariaLabel={`${pair.observation} observed vs predicted`}
                    xLabel={pair.kind === "timeseries" ? "coordinate" : "row"}
                    yLabel={pair.unit}
                  />
                );
              })()}
            </div>
          ) : null}
          {pair.exclusions.length > 0 ? (
            <div data-testid={`eval-exclusions-${index}`}>
              <InlineNotification
                kind="info"
                lowContrast
                hideCloseButton
                title="Excluded observations"
                subtitle={pair.exclusions
                  .map((exclusion) => `#${exclusion.observation_index} ${exclusion.reason}`)
                  .join(", ")}
              />
            </div>
          ) : null}
        </div>
      ))}

      {result.pairs.length > 0 ? (
        <TableContainer title="Metrics">
          <Table aria-label="Evaluation metrics" size="sm" data-testid="eval-metrics-table">
            <TableHead>
              <TableRow>
                <TableHeader>observation</TableHeader>
                <TableHeader>output</TableHeader>
                <TableHeader>unit</TableHeader>
                <TableHeader className="drw-num">usable</TableHeader>
                <TableHeader className="drw-num">excluded</TableHeader>
                {Array.from(new Set(result.pairs.flatMap((p) => Object.keys(p.metrics)))).map((name) => (
                  <TableHeader key={name} className="drw-num">
                    {name}
                  </TableHeader>
                ))}
              </TableRow>
            </TableHead>
            <TableBody>
              {result.pairs.map((pair, index) => {
                const metricNames = Array.from(new Set(result.pairs.flatMap((p) => Object.keys(p.metrics))));
                return (
                  <TableRow key={`${pair.observation}-${pair.output}-${index}`}>
                    <TableCell className="drw-mono">{pair.observation}</TableCell>
                    <TableCell className="drw-mono">{pair.output}</TableCell>
                    <TableCell>{pair.unit}</TableCell>
                    <TableCell className="drw-num">{pair.usable_count}</TableCell>
                    <TableCell className="drw-num">{pair.excluded_count}</TableCell>
                    {metricNames.map((name) => (
                      <TableCell key={name} className="drw-num">
                        {formatNumber(pair.metrics[name] ?? null)}
                      </TableCell>
                    ))}
                  </TableRow>
                );
              })}
            </TableBody>
          </Table>
        </TableContainer>
      ) : null}

      <p className="drw-muted" data-testid="eval-provenance">
        provenance: spec {result.provenance.spec_hash.slice(0, 12)}… · model{" "}
        {result.provenance.model_hash.slice(0, 12)}… · dataset {result.provenance.dataset_content_hash.slice(0, 12)}… ·
        mapping {result.provenance.mapping_hash.slice(0, 12)}…
      </p>
      <p className="drw-hint">
        Evaluation is read-only and execution-free; it is not calibration, not validation and not a scientific
        conclusion.
      </p>
    </div>
  );
}
