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

import { Section } from "@/components/Section";
import { ScientificStatus, type ScientificLevel } from "@/components/page/ScientificStatus";
import { ApiError, type DrwClient } from "@/lib/client";
import { formatNumber } from "@/lib/format";
import type {
  CalibrationRef,
  CalibrationResult,
  DatasetSummary,
  IndependenceSpec,
  ValidationConfig,
  ValidationDatasetOutcome,
  ValidationOutcome,
  ValidationStaleness,
} from "@/lib/types";

const CORE_METRICS = ["rmse", "mae", "max_abs_error", "mean_residual"];
const DIMENSIONS = [
  { id: "dataset", label: "dataset (content + science hash)" },
  { id: "time_window", label: "time / coordinate window" },
  { id: "entity", label: "entity / group key" },
];
const OPS = ["<=", "<", ">=", ">"];

function residualModesFor(metrics: string[]): string[] {
  const modes = new Set<string>(["raw"]);
  for (const metric of metrics) {
    if (metric.startsWith("relative") || metric.startsWith("max_abs_relative")) modes.add("relative");
    if (metric === "weighted_rmse" || metric === "chi_square") modes.add("normalized");
  }
  return [...modes];
}

function mappingTemplate(dataset: DatasetSummary | undefined, modelId: string): string {
  return JSON.stringify(
    {
      dataset: dataset
        ? { dataset_id: dataset.dataset_id, content_hash: dataset.content_hash }
        : { dataset_id: "", content_hash: "" },
      model_ref: { model_id: modelId },
      pairs: [{ observation: "", output: "", coordinates: [] }],
    },
    null,
    2,
  );
}

/** Derive the honest overall badge from the three orthogonal axes (never acceptance alone). */
export function validationLevel(outcome: ValidationOutcome): ScientificLevel {
  if (outcome.descriptive) return "descriptive";
  if (outcome.agreement_status === "failed" || outcome.agreement_status === "not_run") {
    return "not_validated";
  }
  if (outcome.acceptance_status === "not_met") return "descriptive";
  if (outcome.agreement_status === "inconclusive") return "limited";
  if (outcome.independence_status === "violated") return "descriptive";
  const acceptanceOk =
    outcome.acceptance_status === "met" || outcome.acceptance_status === "not_specified";
  if (outcome.independence_status === "verified" && acceptanceOk) return "supported";
  return "limited";
}

/**
 * Validation (M12C): test a frozen calibration against independent observations.
 * Execution-free at the UI layer; drives the existing Runner + M12A through the
 * bridge. Reports agreement, independence and (optional) acceptance as three
 * separate axes - never one boolean.
 */
export function ValidationRunPanel({
  client,
  experimentId,
  modelId,
  refreshToken = 0,
}: {
  client: DrwClient;
  experimentId: string;
  modelId: string;
  refreshToken?: number;
}) {
  const [calibrations, setCalibrations] = useState<CalibrationRef[]>([]);
  const [calibrationId, setCalibrationId] = useState("");
  const [calibration, setCalibration] = useState<CalibrationResult | null>(null);
  const [datasets, setDatasets] = useState<DatasetSummary[]>([]);
  const [datasetId, setDatasetId] = useState("");
  const [mappingText, setMappingText] = useState("");
  const [claims, setClaims] = useState<string[]>(["dataset"]);
  const [groupKey, setGroupKey] = useState("");
  const [declaration, setDeclaration] = useState("");
  const [metrics, setMetrics] = useState<string[]>(["rmse", "mae", "max_abs_error"]);
  const [acceptEnabled, setAcceptEnabled] = useState(false);
  const [acceptMetric, setAcceptMetric] = useState("rmse");
  const [acceptOp, setAcceptOp] = useState("<=");
  const [acceptThreshold, setAcceptThreshold] = useState("0.5");
  const [maxEvaluations, setMaxEvaluations] = useState("10");
  const [maxWall, setMaxWall] = useState("600");
  const [reportGap, setReportGap] = useState(true);
  const [outcome, setOutcome] = useState<ValidationOutcome | null>(null);
  const [staleness, setStaleness] = useState<ValidationStaleness | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    void (async () => {
      try {
        setCalibrations(await client.listCalibrations());
      } catch {
        setCalibrations([]);
      }
    })();
  }, [client, refreshToken]);

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
  const calibrationDataset = calibration?.config?.dataset ?? null;

  async function chooseCalibration(next: string): Promise<void> {
    setCalibrationId(next);
    setCalibration(null);
    if (!next) return;
    try {
      const response = await client.getCalibration(next);
      setCalibration(response.calibration);
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : String(caught));
    }
  }

  function chooseDataset(next: string): void {
    setDatasetId(next);
    const dataset = datasets.find((item) => item.dataset_id === next);
    if (dataset) setMappingText(mappingTemplate(dataset, modelId));
  }

  function toggle(list: string[], value: string, on: boolean): string[] {
    return on ? [...new Set([...list, value])] : list.filter((item) => item !== value);
  }

  const canRun = Boolean(calibrationId && calibrationDataset && datasetId && metrics.length > 0);

  function buildConfig(): ValidationConfig {
    if (!selectedDataset || !calibrationDataset || !calibrationId) {
      throw new Error("select a calibration and a validation dataset");
    }
    const independence: IndependenceSpec = {
      vs_dataset: {
        dataset_id: calibrationDataset.dataset_id,
        content_hash: calibrationDataset.content_hash,
        name: calibrationDataset.name,
        created_at: calibrationDataset.created_at,
      },
      claimed_dimensions: claims,
    };
    if (groupKey.trim()) independence.group_key = groupKey.trim();
    if (declaration.trim()) independence.declaration = declaration.trim();
    const config: ValidationConfig = {
      experiment_id: experimentId,
      model_ref: { model_id: modelId },
      calibration: {
        calibration_id: calibrationId,
        result_hash:
          calibrations.find((item) => item.calibration_id === calibrationId)?.result_hash ?? "",
        experiment_id: experimentId,
        model_id: modelId,
        status: calibration?.status ?? "converged",
      },
      datasets: [
        {
          dataset: {
            dataset_id: selectedDataset.dataset_id,
            content_hash: selectedDataset.content_hash,
            name: selectedDataset.name,
            created_at: selectedDataset.created_at,
          },
          mapping: JSON.parse(mappingText),
          independence,
        },
      ],
      evaluation: { metrics, residual_modes: residualModesFor(metrics) },
      budget: { max_evaluations: Number(maxEvaluations), max_wall_seconds: Number(maxWall) },
      report_gap: reportGap,
    };
    if (acceptEnabled) {
      config.acceptance = [
        {
          metric: acceptMetric,
          op: acceptOp as "<=" | "<" | ">=" | ">",
          threshold: Number(acceptThreshold),
        },
      ];
    }
    return config;
  }

  async function run(): Promise<void> {
    setBusy(true);
    setError(null);
    setOutcome(null);
    setStaleness(null);
    try {
      const response = await client.runValidation(experimentId, {
        config: buildConfig(),
        persist: true,
      });
      setOutcome(response.validation);
      if (response.ref) {
        try {
          setStaleness(await client.checkValidationStaleness(response.ref.validation_id));
        } catch {
          setStaleness(null);
        }
      }
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : caught instanceof Error ? caught.message : String(caught));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Section
      id="validation-heading"
      title="Validate frozen calibration"
      description="Test the calibrated model with its parameters frozen against independent observations. Agreement, independence and any acceptance criterion are reported separately - this does not establish that the model is true."
    >
      <div className="drw-stack-tight" data-testid="validation-panel">
        <div className="drw-formgrid">
          <Select
            id="val-calibration"
            data-testid="val-calibration"
            labelText="Calibration"
            value={calibrationId}
            onChange={(event) => void chooseCalibration(event.target.value)}
          >
            <SelectItem value="" text="— select —" />
            {calibrations.map((item) => (
              <SelectItem
                key={item.calibration_id}
                value={item.calibration_id}
                text={`${item.calibration_id} (${item.status})`}
              />
            ))}
          </Select>
          <Select
            id="val-dataset"
            data-testid="val-dataset"
            labelText="Validation dataset"
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
        </div>

        {calibrations.length === 0 ? (
          <p className="drw-hint">No persisted calibration found. Calibrate and persist a result first.</p>
        ) : null}

        <TextArea
          id="val-mapping"
          labelText="Mapping (ObservationMapping JSON)"
          helperText="Pairs an observed variable with a model output for the validation dataset."
          data-testid="val-mapping"
          rows={7}
          value={mappingText}
          onChange={(event) => setMappingText(event.target.value)}
          placeholder='{"dataset": {...}, "model_ref": {...}, "pairs": [...]}'
        />

        <fieldset className="drw-optset">
          <legend className="drw-optset__legend">Independence claim</legend>
          {DIMENSIONS.map((dimension) => (
            <Checkbox
              key={dimension.id}
              id={`val-claim-${dimension.id}`}
              data-testid={`val-claim-${dimension.id}`}
              labelText={dimension.label}
              checked={claims.includes(dimension.id)}
              onChange={(_event, { checked }) => setClaims((current) => toggle(current, dimension.id, checked))}
            />
          ))}
          <TextInput
            id="val-group-key"
            data-testid="val-group-key"
            labelText="Group key column (for entity/region)"
            value={groupKey}
            onChange={(event) => setGroupKey(event.target.value)}
          />
          <TextArea
            id="val-declaration"
            data-testid="val-declaration"
            labelText="Declaration"
            helperText="Why you assert independence for the dimensions DRW cannot verify."
            rows={2}
            value={declaration}
            onChange={(event) => setDeclaration(event.target.value)}
          />
        </fieldset>

        <fieldset className="drw-optset">
          <legend className="drw-optset__legend">Metrics</legend>
          {CORE_METRICS.map((metric) => (
            <Checkbox
              key={metric}
              id={`val-metric-${metric}`}
              data-testid={`val-metric-${metric}`}
              labelText={metric}
              checked={metrics.includes(metric)}
              onChange={(_event, { checked }) => setMetrics((current) => toggle(current, metric, checked))}
            />
          ))}
        </fieldset>

        <fieldset className="drw-optset">
          <legend className="drw-optset__legend">Acceptance criterion (optional, yours)</legend>
          <Checkbox
            id="val-accept-enabled"
            data-testid="val-accept-enabled"
            labelText="Require an explicit criterion"
            checked={acceptEnabled}
            onChange={(_event, { checked }) => setAcceptEnabled(checked)}
          />
          <div className="drw-formgrid">
            <Select
              id="val-accept-metric"
              data-testid="val-accept-metric"
              labelText="Metric"
              value={acceptMetric}
              onChange={(event) => setAcceptMetric(event.target.value)}
            >
              {metrics.map((metric) => (
                <SelectItem key={metric} value={metric} text={metric} />
              ))}
            </Select>
            <Select
              id="val-accept-op"
              data-testid="val-accept-op"
              labelText="Operator"
              value={acceptOp}
              onChange={(event) => setAcceptOp(event.target.value)}
            >
              {OPS.map((op) => (
                <SelectItem key={op} value={op} text={op} />
              ))}
            </Select>
            <TextInput
              id="val-accept-threshold"
              data-testid="val-accept-threshold"
              labelText="Threshold"
              value={acceptThreshold}
              onChange={(event) => setAcceptThreshold(event.target.value)}
            />
          </div>
        </fieldset>

        <div className="drw-formgrid drw-formgrid--run">
          <TextInput
            id="val-max-evals"
            data-testid="val-max-evals"
            labelText="Max evaluations"
            value={maxEvaluations}
            onChange={(event) => setMaxEvaluations(event.target.value)}
          />
          <TextInput
            id="val-max-wall"
            data-testid="val-max-wall"
            labelText="Max wall (s)"
            value={maxWall}
            onChange={(event) => setMaxWall(event.target.value)}
          />
          <Checkbox
            id="val-report-gap"
            data-testid="val-report-gap"
            labelText="Report calibration gap"
            checked={reportGap}
            onChange={(_event, { checked }) => setReportGap(checked)}
          />
          <Button onClick={() => void run()} disabled={!canRun || busy} data-testid="val-run">
            Validate
          </Button>
        </div>

        {error ? (
          <div data-testid="val-error">
            <InlineNotification kind="error" lowContrast hideCloseButton title="Validation" subtitle={error} />
          </div>
        ) : null}

        {staleness && !staleness.fresh ? (
          <div data-testid="val-staleness">
            <InlineNotification
              kind="warning"
              lowContrast
              hideCloseButton
              title="Stale result"
              subtitle={`This stored validation is no longer current: ${staleness.reasons.join(", ")}.`}
            />
          </div>
        ) : null}

        {outcome ? <Report outcome={outcome} /> : null}
      </div>
    </Section>
  );
}

function AgreementTag({ agreement }: { agreement: string }) {
  const type = agreement === "evaluated" ? "green" : agreement === "partial" || agreement === "inconclusive" ? "gray" : "red";
  return <Tag type={type}>{agreement}</Tag>;
}

function Report({ outcome }: { outcome: ValidationOutcome }) {
  const level = validationLevel(outcome);
  return (
    <div className="drw-stack-tight" data-testid="val-result">
      <div className="drw-row drw-row--center" data-testid="val-axes">
        <span data-testid="val-verdict">
          <AgreementTag agreement={outcome.agreement_status} />
        </span>
        <span className="drw-muted">
          agreement {outcome.agreement_status} · acceptance {outcome.acceptance_status} ·
          independence {outcome.independence_status} · evaluations {outcome.evaluations_completed}/
          {outcome.evaluations_requested} · hash {outcome.result_hash.slice(0, 12)}…
          {outcome.descriptive ? " · descriptive (non-independent)" : ""}
        </span>
      </div>

      {outcome.datasets.map((dataset, index) => (
        <DatasetReport key={`${dataset.dataset.dataset_id}-${index}`} dataset={dataset} index={index} />
      ))}

      {outcome.diagnostics.length > 0 ? (
        <ul className="drw-muted" data-testid="val-diagnostics">
          {outcome.diagnostics.map((diagnostic) => (
            <li key={`${diagnostic.code}-${diagnostic.message}`}>
              [{diagnostic.level}] {diagnostic.code}: {diagnostic.message}
            </li>
          ))}
        </ul>
      ) : null}

      <p className="drw-muted drw-mono" data-testid="val-provenance">
        model {outcome.provenance.model_hash.slice(0, 12)}… · calibration{" "}
        {outcome.provenance.calibration_result_hash.slice(0, 12)}… · env{" "}
        {outcome.provenance.environment_hash.slice(0, 12)}… · scipy {outcome.provenance.scipy_version}
      </p>

      <ScientificStatus level={level} testId="val-note">
        {outcome.note}
      </ScientificStatus>
    </div>
  );
}

function metricRows(
  dataset: ValidationDatasetOutcome,
): { key: string; value: number | null; calibration: number | null }[] {
  const keys = [...new Set([...Object.keys(dataset.metrics), ...Object.keys(dataset.calibration_metrics)])];
  return keys.map((key) => ({
    key,
    value: dataset.metrics[key] ?? null,
    calibration: dataset.calibration_metrics[key] ?? null,
  }));
}

function DatasetReport({ dataset, index }: { dataset: ValidationDatasetOutcome; index: number }) {
  const rows = metricRows(dataset);
  return (
    <div className="drw-block" data-testid={`val-dataset-${index}`}>
      <p className="drw-hint">
        <strong>{dataset.label || dataset.dataset.dataset_id}</strong> ·{" "}
        {dataset.failure ? (
          <span data-testid={`val-failure-${index}`}>failed: {dataset.failure}</span>
        ) : (
          `agreement ${dataset.agreement}`
        )}{" "}
        · {dataset.n_used} used, {dataset.n_excluded} excluded
      </p>

      <TableContainer>
        <Table size="sm" aria-label={`validation metrics ${index}`}>
          <TableHead>
            <TableRow>
              <TableHeader>metric</TableHeader>
              <TableHeader>validation</TableHeader>
              <TableHeader>calibration</TableHeader>
              <TableHeader>gap</TableHeader>
            </TableRow>
          </TableHead>
          <TableBody>
            {rows.map((row) => {
              const gap =
                row.value !== null && row.calibration !== null ? row.value - row.calibration : null;
              return (
                <TableRow key={row.key}>
                  <TableCell>{row.key}</TableCell>
                  <TableCell>{formatNumber(row.value)}</TableCell>
                  <TableCell>{formatNumber(row.calibration)}</TableCell>
                  <TableCell>{formatNumber(gap)}</TableCell>
                </TableRow>
              );
            })}
          </TableBody>
        </Table>
      </TableContainer>

      <p className="drw-muted" data-testid={`val-independence-${index}`}>
        independence: {dataset.independence.status} — {dataset.independence.note}
      </p>
      <ul className="drw-muted">
        {dataset.independence.checks.map((check) => (
          <li key={`${check.dimension}-${check.message}`}>
            {check.dimension}: {check.state} — {check.message}
          </li>
        ))}
      </ul>

      {Object.keys(dataset.exclusion_counts).length > 0 ? (
        <p className="drw-muted" data-testid={`val-exclusions-${index}`}>
          exclusions:{" "}
          {Object.entries(dataset.exclusion_counts)
            .map(([reason, count]) => `${reason}=${count}`)
            .join(", ")}
        </p>
      ) : null}

      <p className="drw-muted" data-testid={`val-context-${index}`}>
        {dataset.context.note}
      </p>

      {dataset.acceptance.length > 0 ? (
        <ul className="drw-muted" data-testid={`val-acceptance-${index}`}>
          {dataset.acceptance.map((item) => (
            <li key={`${item.metric}-${item.op}-${item.threshold}`}>
              acceptance: {item.metric} {item.op} {item.threshold} → {item.status}
              {item.observed !== null ? ` (observed ${formatNumber(item.observed)})` : ""}
            </li>
          ))}
        </ul>
      ) : (
        <p className="drw-muted" data-testid={`val-acceptance-${index}`}>
          acceptance: not specified
        </p>
      )}
    </div>
  );
}
