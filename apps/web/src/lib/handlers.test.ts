// @vitest-environment node

/**
 * API/integration tests: the route handlers driven against the real Python core.
 *
 * These do not boot an HTTP server; they exercise the same handler functions the
 * Next.js route files call, including the subprocess bridge.
 */

import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";

import { beforeAll, describe, expect, it } from "vitest";

import { unwrap } from "./client";
import { handlers } from "./handlers";
import type { ExperimentData, ExperimentSpec, ValidationResult } from "./types";

beforeAll(() => {
  process.env.DRW_WORKSPACE = mkdtempSync(path.join(tmpdir(), "drw-web-"));
});

function data<T>(result: { body: unknown }): T {
  return unwrap<T>(result.body);
}

async function sampleSpec(): Promise<ExperimentSpec> {
  return data<{ spec: ExperimentSpec }>(await handlers.sampleExperiment("predator-prey")).spec;
}

describe("model endpoints", () => {
  it("lists registered models", async () => {
    const models = data<{ models: { model_id: string }[] }>(await handlers.listModels()).models;
    expect(models.map((m) => m.model_id)).toContain("predator-prey");
  });

  it("describes a model with its parameters and units", async () => {
    const described = data<{ schema: { parameters: { name: string; unit: string }[] } }>(
      await handlers.describeModel("predator-prey"),
    );
    const alpha = described.schema.parameters.find((p) => p.name === "alpha");
    expect(alpha?.unit).toBe("1/s");
  });

  it("returns 404 for an unknown model", async () => {
    const result = await handlers.describeModel("does-not-exist");
    expect(result.status).toBe(404);
    expect((result.body as { ok: boolean }).ok).toBe(false);
  });
});

describe("validation", () => {
  it("accepts the sample experiment", async () => {
    const validation = data<ValidationResult>(await handlers.validate(await sampleSpec()));
    expect(validation.ok).toBe(true);
    expect(validation.estimate.total_runs).toBe(2);
  });

  it("reports actionable errors for an out-of-bounds intervention", async () => {
    const spec = await sampleSpec();
    spec.factors = [{ parameter: "alpha", values: [999] }];
    const validation = data<ValidationResult>(await handlers.validate(spec));
    expect(validation.ok).toBe(false);
    expect(validation.diagnostics.some((d) => d.code === "factor_out_of_bounds")).toBe(true);
  });
});

describe("run, persistence and evidence", () => {
  it("runs, persists, reloads unchanged and exports", async () => {
    const spec = await sampleSpec();
    const data1 = data<ExperimentData>(await handlers.run(spec));
    expect(data1.experiment_id).toMatch(/^exp-[0-9a-f]{12}$/);
    expect(data1.runs).toHaveLength(2);
    expect(data1.comparisons.length).toBeGreaterThan(0);
    expect(data1.isolation).toBe("subprocess");

    // The metric is produced by the Python differential-analysis implementation.
    const delta = data1.comparisons[0]?.metrics.max_abs_delta ?? 0;
    expect(delta).toBeGreaterThan(0);

    const listed = data<{ experiments: { experiment_id: string }[] }>(
      await handlers.listExperiments(),
    ).experiments;
    expect(listed.map((e) => e.experiment_id)).toContain(data1.experiment_id);

    const loaded = data<{ experiment: { spec: ExperimentSpec } }>(
      await handlers.getExperiment(data1.experiment_id),
    ).experiment;
    expect(loaded.spec).toEqual(JSON.parse(JSON.stringify(spec)));

    const evidence = data<{ evidence: { manifest: { n_runs: number } } }>(
      await handlers.evidence(data1.experiment_id),
    ).evidence;
    expect(evidence.manifest.n_runs).toBe(2);

    const exported = data<{ zip: string; path: string }>(
      await handlers.exportEvidence(data1.experiment_id),
    );
    expect(exported.zip).toMatch(/evidence\.zip$/);

    const sensitivity = data<{ metric: string; ranking: unknown[] }>(
      await handlers.sensitivity(data1.experiment_id),
    );
    expect(sensitivity.metric).toBe("peak_prey");
    expect(sensitivity.ranking.length).toBeGreaterThan(0);
  });
});

describe("failure mapping", () => {
  it("maps a malformed spec to 400", async () => {
    const result = await handlers.validate({ hypothesis: "h" });
    expect(result.status).toBe(400);
    expect((result.body as { error: { code: string } }).error.code).toBe("invalid_spec");
  });

  it("maps a traversal attempt to 400", async () => {
    const result = await handlers.getExperiment("../../etc/passwd");
    expect(result.status).toBe(400);
  });
});
