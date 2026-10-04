/**
 * Pure helpers for the experiment workflow.
 *
 * These contain no science: they assemble a spec from UI state (the Python core
 * validates it) and map a result to a UI status. Kept pure so they can be unit
 * tested without rendering.
 */

import type { ExperimentSpec, FactorSpec } from "./types";
import type { ModelCapabilities, ModelSchema, RunRecord } from "./types";

export type UiStatus =
  | "idle"
  | "validating"
  | "running"
  | "succeeded"
  | "failed"
  | "cancelled"
  | "timed_out";

export interface FactorDraft {
  id: string;
  parameter: string;
  mode: "value" | "range";
  value: string;
  lower: string;
  upper: string;
  steps: string;
}

export type BaselineValue = number | boolean | string;

let factorCounter = 0;

export function newFactorDraft(parameter: string, value: string): FactorDraft {
  factorCounter += 1;
  return {
    id: `factor-${factorCounter}`,
    parameter,
    mode: "value",
    value,
    lower: "",
    upper: "",
    steps: "3",
  };
}

/** Default baseline: each parameter's declared nominal value. */
export function baselineFromSchema(schema: ModelSchema): Record<string, BaselineValue> {
  const baseline: Record<string, BaselineValue> = {};
  for (const param of schema.parameters) {
    if (typeof param.nominal === "number") baseline[param.name] = param.nominal;
    else if (typeof param.nominal === "boolean") baseline[param.name] = param.nominal;
    else if (typeof param.nominal === "string") baseline[param.name] = param.nominal;
    else baseline[param.name] = 0;
  }
  return baseline;
}

export interface FactorParseResult {
  factors: FactorSpec[];
  errors: string[];
}

/** Convert factor drafts into wire `FactorSpec`s, reporting unparseable input. */
export function parseDraftFactors(drafts: FactorDraft[]): FactorParseResult {
  const factors: FactorSpec[] = [];
  const errors: string[] = [];
  for (const draft of drafts) {
    if (!draft.parameter) {
      errors.push("every intervention needs a parameter");
      continue;
    }
    if (draft.mode === "value") {
      const value = Number(draft.value);
      if (draft.value.trim() === "" || !Number.isFinite(value)) {
        errors.push(`intervention on ${draft.parameter}: value must be a number`);
        continue;
      }
      factors.push({ parameter: draft.parameter, values: [value] });
    } else {
      const lower = Number(draft.lower);
      const upper = Number(draft.upper);
      const steps = Number(draft.steps);
      if (!Number.isFinite(lower) || !Number.isFinite(upper)) {
        errors.push(`intervention on ${draft.parameter}: lower and upper must be numbers`);
        continue;
      }
      if (!Number.isInteger(steps) || steps < 1) {
        errors.push(`intervention on ${draft.parameter}: steps must be a positive integer`);
        continue;
      }
      factors.push({ parameter: draft.parameter, lower, upper, steps });
    }
  }
  return { factors, errors };
}

export interface SpecDraft {
  hypothesis: string;
  baseline: Record<string, BaselineValue>;
  factors: FactorSpec[];
  timeoutS?: number;
}

/** Assemble a spec from UI state. `base` supplies model/outputs/analyses/execution. */
export function buildSpec(base: ExperimentSpec, draft: SpecDraft): ExperimentSpec {
  const spec: ExperimentSpec = {
    ...base,
    hypothesis: draft.hypothesis.trim() || base.hypothesis,
    baseline: draft.baseline,
    factors: draft.factors,
  };
  if (draft.timeoutS !== undefined) {
    spec.execution = { ...(base.execution ?? {}), timeout_s: draft.timeoutS };
  }
  return spec;
}

/**
 * Map an executed experiment to a UI status.
 *
 * Deliberately conservative: any failed or timed-out run, partial success, or a
 * zero-run result is surfaced as a non-success state so the UI never claims
 * success before every run actually succeeded.
 */
export function statusFromResult(data: {
  runs: RunRecord[];
}): Extract<UiStatus, "succeeded" | "failed" | "cancelled" | "timed_out"> {
  const runs = data.runs ?? [];
  if (runs.length === 0) return "failed";
  if (runs.some((run) => run.timed_out)) return "timed_out";
  if (runs.some((run) => run.diagnostics.some((d) => d.code === "cancelled"))) {
    return "cancelled";
  }
  const succeeded = runs.filter((run) => run.status === "succeeded").length;
  if (succeeded === 0 || succeeded < runs.length) return "failed";
  return "succeeded";
}

/** Human-readable issues for a single run (used in the run table). */
export function runIssues(run: RunRecord): string[] {
  const issues: string[] = [];
  if (run.timed_out) issues.push("timed out");
  for (const diagnostic of run.diagnostics) {
    if (diagnostic.code === "cancelled") issues.push("cancelled");
  }
  if (run.error && !run.timed_out) issues.push(run.error);
  return issues;
}

export interface ModelViability {
  eligible: boolean;
  reason: string | null;
}

/**
 * Whether a model can seed an experiment through the existing core, derived only
 * from its declared capabilities.
 *
 * Technical eligibility - not scientific validity. A model that passes here can
 * be *configured and executed*; whether any particular hypothesis is worth
 * testing, or whether the result means anything, is a scientific judgement the
 * platform does not make.
 */
export function modelViability(capabilities: ModelCapabilities | null | undefined): ModelViability {
  if (!capabilities) {
    return { eligible: false, reason: "Capabilities are unavailable for this model." };
  }
  const numeric =
    capabilities.factorable_parameters.length + capabilities.fixed_parameters.length;
  if (capabilities.parameter_names.length === 0 || numeric === 0) {
    return {
      eligible: false,
      reason:
        "This model declares no numeric parameter that can be varied, so an intervention cannot be defined.",
    };
  }
  const outputs =
    capabilities.timeseries_outputs.length + capabilities.scalar_outputs.length;
  if (outputs === 0) {
    return { eligible: false, reason: "This model declares no output that can be compared." };
  }
  return { eligible: true, reason: null };
}

/** Rebuild editor drafts from a (possibly reopened) spec. */
export function factorDraftsFromSpec(spec: ExperimentSpec): FactorDraft[] {
  const drafts: FactorDraft[] = [];
  for (const factor of spec.factors ?? []) {
    if (factor.values && factor.values.length > 0) {
      drafts.push({
        ...newFactorDraft(factor.parameter, String(factor.values[0])),
        mode: "value",
      });
    } else {
      drafts.push({
        ...newFactorDraft(factor.parameter, ""),
        mode: "range",
        lower: String(factor.lower ?? ""),
        upper: String(factor.upper ?? ""),
        steps: String(factor.steps ?? 3),
      });
    }
  }
  return drafts;
}
