"use client";

import { useEffect, useMemo, useState } from "react";

import {
  Button,
  Checkbox,
  InlineNotification,
  Select,
  SelectItem,
  Tag,
  TextArea,
  TextInput,
} from "@carbon/react";

import { LineChart } from "@/components/LineChart";
import { ScientificStatus } from "@/components/page/ScientificStatus";
import { Section } from "@/components/Section";
import { ApiError, type DrwClient } from "@/lib/client";
import { formatNumber } from "@/lib/format";
import type {
  CalibrationConfig,
  CalibrationRef,
  CalibrationResult,
  DatasetSummary,
  ModelSchema,
} from "@/lib/types";

const METRICS = [
  "rmse",
  "mae",
  "max_abs_error",
  "mean_residual",
  "relative_rmse",
  "relative_mae",
  "max_abs_relative_error",
  "weighted_rmse",
  "chi_square",
];
const OPTIMIZERS: { value: string; label: string }[] = [
  { value: "powell", label: "Powell (default, local)" },
  { value: "differential_evolution", label: "Differential Evolution (opt-in, global)" },
  { value: "random_search", label: "Random Search (baseline)" },
];
const IDENTIFIABILITY = ["off", "warn", "require"];

interface FreeRow {
  name: string;
  unit: string;
  lower: number;
  upper: number;
  initial: number;
  enabled: boolean;
}

function defaultRows(schema: ModelSchema): FreeRow[] {
  return schema.parameters
    .filter((parameter) => parameter.type === "float" && parameter.lower !== null && parameter.upper !== null)
    .map((parameter) => ({
      name: parameter.name,
      unit: parameter.unit,
      lower: parameter.lower as number,
      upper: parameter.upper as number,
      initial: typeof parameter.nominal === "number" ? parameter.nominal : (parameter.lower as number),
      enabled: false,
    }));
}

function residualModesFor(metric: string): string[] {
  if (metric === "weighted_rmse" || metric === "chi_square") return ["raw", "normalized"];
  if (metric.startsWith("relative") || metric.startsWith("max_abs_relative")) return ["raw", "relative"];
  return ["raw"];
}

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

/**
 * Calibration (M12B): fit bounded float parameters to a dataset under an explicit
 * objective. Serial and execution-free at the UI layer: it drives the existing
 * Runner + M12A through the bridge. A point estimate only - not parameter
 * uncertainty, not validation, and convergence is not certainty.
 */
export function CalibrationPanel({
  client,
  experimentId,
  schema,
  refreshToken = 0,
}: {
  client: DrwClient;
  experimentId: string;
  schema: ModelSchema;
  refreshToken?: number;
}) {
  const [datasets, setDatasets] = useState<DatasetSummary[]>([]);
  const [datasetId, setDatasetId] = useState("");
  const [mappingText, setMappingText] = useState("");
  const [rows, setRows] = useState<FreeRow[]>(() => defaultRows(schema));
  const [metric, setMetric] = useState("rmse");
  const [optimizer, setOptimizer] = useState("powell");
  const [seed, setSeed] = useState("0");
  const [maxEvaluations, setMaxEvaluations] = useState("100");
  const [maxWall, setMaxWall] = useState("600");
  const [identifiability, setIdentifiability] = useState("warn");
  const [result, setResult] = useState<CalibrationResult | null>(null);
  const [storedRef, setStoredRef] = useState<CalibrationRef | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => setRows(defaultRows(schema)), [schema]);

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

  const freeCount = rows.filter((row) => row.enabled).length;

  function chooseDataset(next: string): void {
    setDatasetId(next);
    const dataset = datasets.find((item) => item.dataset_id === next);
    if (dataset) setMappingText(mappingTemplate(dataset, schema.model_id));
  }

  function updateRow(name: string, patch: Partial<FreeRow>): void {
    setRows((current) => current.map((row) => (row.name === name ? { ...row, ...patch } : row)));
  }

  function buildConfig(): CalibrationConfig {
    if (!selectedDataset) throw new Error("select a dataset");
    const free = rows
      .filter((row) => row.enabled)
      .map((row) => ({ name: row.name, lower: Number(row.lower), upper: Number(row.upper), initial: Number(row.initial) }));
    return {
      experiment_id: experimentId,
      model_ref: { model_id: schema.model_id },
      free,
      objective: { metric },
      optimizer: { name: optimizer as "powell" | "differential_evolution" | "random_search" },
      budget: { max_evaluations: Number(maxEvaluations), max_wall_seconds: Number(maxWall) },
      seed: Number(seed),
      dataset: {
        dataset_id: selectedDataset.dataset_id,
        content_hash: selectedDataset.content_hash,
        name: selectedDataset.name,
        created_at: selectedDataset.created_at,
      },
      mapping: JSON.parse(mappingText),
      evaluation: { metrics: [metric], residual_modes: residualModesFor(metric) },
      identifiability,
    };
  }

  async function run(): Promise<void> {
    setBusy(true);
    setError(null);
    setResult(null);
    setStoredRef(null);
    try {
      // Persist the calibration so it can be referenced by validation.
      const response = await client.calibrate(experimentId, { config: buildConfig(), persist: true });
      setResult(response.calibration);
      setStoredRef(response.ref ?? null);
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : caught instanceof Error ? caught.message : String(caught));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Section
      id="calibration-heading"
      title="Calibrate against dataset"
      description="Fit bounded parameters to a dataset by minimising a chosen error metric (the objective). Serial, bounded and execution-free: a point estimate only - not parameter uncertainty and not validation."
    >
      <div className="drw-stack-tight" data-testid="calibration-panel">
        <div className="drw-formgrid">
          <Select
            id="calib-dataset"
            data-testid="calib-dataset"
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
            id="calib-metric"
            data-testid="calib-metric"
            labelText="Objective metric"
            value={metric}
            onChange={(event) => setMetric(event.target.value)}
          >
            {METRICS.map((name) => (
              <SelectItem key={name} value={name} text={name} />
            ))}
          </Select>
          <Select
            id="calib-optimizer"
            data-testid="calib-optimizer"
            labelText="Optimizer"
            value={optimizer}
            onChange={(event) => setOptimizer(event.target.value)}
          >
            {OPTIMIZERS.map((item) => (
              <SelectItem key={item.value} value={item.value} text={item.label} />
            ))}
          </Select>
          <Select
            id="calib-identifiability"
            data-testid="calib-identifiability"
            labelText="Identifiability check"
            value={identifiability}
            onChange={(event) => setIdentifiability(event.target.value)}
          >
            {IDENTIFIABILITY.map((mode) => (
              <SelectItem key={mode} value={mode} text={mode} />
            ))}
          </Select>
        </div>

        <div>
          <h3 className="drw-subheading">Free parameters</h3>
          <p className="drw-hint">
            Float, bounded{freeCount ? ` — ${freeCount} selected` : ""}. Tick the parameters to fit
            and set their bounds and starting value.
          </p>
          <table className="drw-table drw-table--form" data-testid="calib-parameters">
            <thead>
              <tr>
                <th scope="col">free</th>
                <th scope="col">name</th>
                <th scope="col">lower</th>
                <th scope="col">upper</th>
                <th scope="col">initial</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={row.name}>
                  <td>
                    <Checkbox
                      id={`calib-free-${row.name}`}
                      labelText={`free parameter ${row.name}`}
                      hideLabel
                      data-testid={`calib-free-${row.name}`}
                      checked={row.enabled}
                      onChange={(_event, { checked }) => updateRow(row.name, { enabled: checked })}
                    />
                  </td>
                  <td className="drw-mono">{row.name}</td>
                  <td>
                    <TextInput
                      id={`calib-lower-${row.name}`}
                      size="sm"
                      labelText={`${row.name} lower bound`}
                      hideLabel
                      data-testid={`calib-lower-${row.name}`}
                      value={row.lower}
                      onChange={(event) => updateRow(row.name, { lower: Number(event.target.value) })}
                    />
                  </td>
                  <td>
                    <TextInput
                      id={`calib-upper-${row.name}`}
                      size="sm"
                      labelText={`${row.name} upper bound`}
                      hideLabel
                      data-testid={`calib-upper-${row.name}`}
                      value={row.upper}
                      onChange={(event) => updateRow(row.name, { upper: Number(event.target.value) })}
                    />
                  </td>
                  <td>
                    <TextInput
                      id={`calib-initial-${row.name}`}
                      size="sm"
                      labelText={`${row.name} initial value`}
                      hideLabel
                      data-testid={`calib-initial-${row.name}`}
                      value={row.initial}
                      onChange={(event) => updateRow(row.name, { initial: Number(event.target.value) })}
                    />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <TextArea
          id="calib-mapping"
          labelText="Mapping (ObservationMapping JSON)"
          helperText="Pairs an observed variable with a model output. Calibration supports one pair."
          data-testid="calib-mapping"
          rows={7}
          value={mappingText}
          onChange={(event) => setMappingText(event.target.value)}
          placeholder='{"dataset": {...}, "model_ref": {...}, "pairs": [...]}'
        />

        <div className="drw-formgrid drw-formgrid--run">
          <TextInput id="calib-seed" data-testid="calib-seed" labelText="Seed" value={seed} onChange={(e) => setSeed(e.target.value)} />
          <TextInput
            id="calib-evals"
            data-testid="calib-max-evals"
            labelText="Max evaluations"
            value={maxEvaluations}
            onChange={(e) => setMaxEvaluations(e.target.value)}
          />
          <TextInput
            id="calib-wall"
            data-testid="calib-max-wall"
            labelText="Max wall (s)"
            value={maxWall}
            onChange={(e) => setMaxWall(e.target.value)}
          />
          <Button onClick={() => void run()} disabled={!datasetId || freeCount === 0 || busy} data-testid="calib-run">
            Calibrate
          </Button>
        </div>

        {error ? (
          <div data-testid="calib-error">
            <InlineNotification kind="error" lowContrast hideCloseButton title="Calibration" subtitle={error} />
          </div>
        ) : null}

        {storedRef ? (
          <p className="drw-hint" data-testid="calib-stored">
            stored calibration {storedRef.calibration_id} — available to Validation.
          </p>
        ) : null}

        {result ? <Report result={result} /> : null}
      </div>
    </Section>
  );
}

function Report({ result }: { result: CalibrationResult }) {
  const axis = result.history.map((_, index) => index);
  const objectiveValues = result.history.map((candidate) => (candidate.objective ?? Number.NaN));
  return (
    <div className="drw-stack-tight" data-testid="calib-result">
      <div className="drw-row drw-row--center">
        <span data-testid="calib-status">
          <Tag type={result.status === "converged" ? "green" : result.status === "failed" ? "red" : "gray"}>
            {result.status}
          </Tag>
        </span>
        <span className="drw-muted">
          stop: {result.stop_reason} · converged: {String(result.converged)} · evaluations{" "}
          {result.evaluations_completed}/{result.evaluations_requested} ({result.evaluations_invalid} invalid) · hash{" "}
          {result.result_hash.slice(0, 12)}…
        </span>
      </div>

      {result.best ? (
        <p className="drw-hint" data-testid="calib-best">
          <strong>best objective ({result.objective.metric}): {formatNumber(result.objective.value)}</strong>
          {" · "}
          {Object.entries(result.best.parameters)
            .map(([name, value]) => `${name}=${formatNumber(value)}`)
            .join(", ")}
        </p>
      ) : (
        <InlineNotification
          kind="warning"
          lowContrast
          hideCloseButton
          title="No usable best"
          subtitle="the calibration produced no valid candidate; no best fit is reported"
        />
      )}

      {axis.length > 1 ? (
        <div data-testid="calib-chart">
          <LineChart
            axis={axis}
            series={[{ name: `${result.objective.metric} objective`, color: "#0f62fe", values: objectiveValues }]}
            ariaLabel="calibration objective history"
            xLabel="candidate"
            yLabel={result.objective.metric}
          />
        </div>
      ) : null}

      {result.diagnostics.length > 0 ? (
        <ul className="drw-muted" data-testid="calib-diagnostics">
          {result.diagnostics.map((diagnostic) => (
            <li key={`${diagnostic.code}-${diagnostic.message}`}>
              [{diagnostic.level}] {diagnostic.code}: {diagnostic.message}
            </li>
          ))}
        </ul>
      ) : null}

      {result.identifiability ? (
        <p className="drw-muted" data-testid="calib-identifiability">
          identifiability: {String(result.identifiability.verdict)} (advisory)
        </p>
      ) : null}

      <ScientificStatus level="not_validated" testId="calib-note">
        {result.note}
      </ScientificStatus>
    </div>
  );
}
