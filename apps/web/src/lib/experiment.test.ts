import { describe, expect, it } from "vitest";

import {
  buildSpec,
  modelViability,
  parseDraftFactors,
  statusFromResult,
  type FactorDraft,
} from "./experiment";
import type { ExperimentSpec, ModelCapabilities, RunRecord } from "./types";

function capabilities(overrides: Partial<ModelCapabilities>): ModelCapabilities {
  return {
    model_id: "m",
    version: "1.0.0",
    parameter_names: ["a"],
    factorable_parameters: [{ name: "a", unit: "1/s", lower: 0, upper: 1 }],
    fixed_parameters: [],
    state_parameters: [],
    categorical_parameters: [],
    timeseries_outputs: ["y"],
    scalar_outputs: [],
    sampling_methods: ["grid"],
    analysis_methods: ["delta"],
    sensitivity: null,
    isolation: "subprocess",
    limitations: [],
    ...overrides,
  };
}

function draft(overrides: Partial<FactorDraft>): FactorDraft {
  return {
    id: "f1",
    parameter: "alpha",
    mode: "value",
    value: "1.21",
    lower: "",
    upper: "",
    steps: "3",
    ...overrides,
  };
}

function run(overrides: Partial<RunRecord>): RunRecord {
  return {
    run_id: "exp-000000000000-r0000",
    label: "baseline",
    status: "succeeded",
    isolation: "subprocess",
    timed_out: false,
    attempt: 1,
    parent_run_id: null,
    inputs: {},
    metrics: {},
    diagnostics: [],
    error: null,
    duration_s: 0.01,
    result: null,
    ...overrides,
  };
}

describe("parseDraftFactors", () => {
  it("parses a single-value intervention", () => {
    const { factors, errors } = parseDraftFactors([draft({})]);
    expect(errors).toEqual([]);
    expect(factors).toEqual([{ parameter: "alpha", values: [1.21] }]);
  });

  it("parses a range intervention", () => {
    const { factors, errors } = parseDraftFactors([
      draft({ mode: "range", lower: "0.5", upper: "2", steps: "4" }),
    ]);
    expect(errors).toEqual([]);
    expect(factors).toEqual([{ parameter: "alpha", lower: 0.5, upper: 2, steps: 4 }]);
  });

  it("reports a non-numeric value instead of sending it", () => {
    const { factors, errors } = parseDraftFactors([draft({ value: "abc" })]);
    expect(factors).toEqual([]);
    expect(errors[0]).toMatch(/must be a number/);
  });

  it("reports non-integer steps", () => {
    const { errors } = parseDraftFactors([draft({ mode: "range", lower: "0", upper: "1", steps: "1.5" })]);
    expect(errors[0]).toMatch(/steps/);
  });
});

describe("statusFromResult", () => {
  it("is succeeded only when every run succeeded", () => {
    expect(statusFromResult({ runs: [run({}), run({ run_id: "r1", label: "variant" })] })).toBe(
      "succeeded",
    );
  });

  it("reports a partial failure as failed", () => {
    expect(
      statusFromResult({
        runs: [run({}), run({ run_id: "r1", status: "failed", error: "boom" })],
      }),
    ).toBe("failed");
  });

  it("reports a timeout when any run timed out", () => {
    expect(
      statusFromResult({ runs: [run({ timed_out: true, status: "failed" })] }),
    ).toBe("timed_out");
  });

  it("reports cancellation when a run carries the cancelled diagnostic", () => {
    expect(
      statusFromResult({
        runs: [
          run({
            status: "failed",
            diagnostics: [{ level: "warning", code: "cancelled", message: "cancelled" }],
          }),
        ],
      }),
    ).toBe("cancelled");
  });

  it("never reports success for an empty result", () => {
    expect(statusFromResult({ runs: [] })).toBe("failed");
  });
});

describe("buildSpec", () => {
  it("keeps the base model but replaces hypothesis, baseline and factors", () => {
    const base = {
      hypothesis: "old",
      model_ref: { model_id: "predator-prey" },
      baseline: { alpha: 1.1 },
      factors: [{ parameter: "alpha", values: [1.1] }],
      outputs: ["prey"],
      analyses: [{ method: "delta" }],
    } as unknown as ExperimentSpec;
    const spec = buildSpec(base, {
      hypothesis: "new hypothesis",
      baseline: { alpha: 1.2 },
      factors: [{ parameter: "alpha", values: [1.3] }],
    });
    expect(spec.hypothesis).toBe("new hypothesis");
    expect(spec.baseline).toEqual({ alpha: 1.2 });
    expect(spec.factors).toEqual([{ parameter: "alpha", values: [1.3] }]);
    expect(spec.model_ref.model_id).toBe("predator-prey");
    expect(spec.outputs).toEqual(["prey"]);
  });
});

describe("modelViability", () => {
  it("is eligible when a numeric parameter and an output exist", () => {
    expect(modelViability(capabilities({}))).toEqual({ eligible: true, reason: null });
  });

  it("is ineligible without any numeric parameter to vary", () => {
    const result = modelViability(
      capabilities({ parameter_names: ["mode"], factorable_parameters: [] }),
    );
    expect(result.eligible).toBe(false);
    expect(result.reason).toMatch(/no numeric parameter/);
  });

  it("is ineligible when capabilities are unavailable", () => {
    expect(modelViability(null)).toEqual({
      eligible: false,
      reason: "Capabilities are unavailable for this model.",
    });
  });

  it("is ineligible without a comparable output", () => {
    const result = modelViability(
      capabilities({ timeseries_outputs: [], scalar_outputs: [] }),
    );
    expect(result.eligible).toBe(false);
    expect(result.reason).toMatch(/no output/);
  });
});
