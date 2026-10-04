import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import test from "node:test";

import {
  EXPERIMENT_SPEC_SCHEMA_VERSION,
  validateExperimentSpecShape,
  type ExperimentSpec,
} from "./index.js";

test("accepts a minimal well-formed spec", () => {
  const spec: ExperimentSpec = {
    hypothesis: "Increasing k by 10% raises the peak.",
    model_ref: { model_id: "oscillator", version: "1.0.0" },
    baseline: { k: 4, m: 1 },
    factors: [{ parameter: "k", values: [4.4] }],
  };
  assert.deepEqual(validateExperimentSpecShape(spec), []);
});

test("reports each missing required field", () => {
  const codes = validateExperimentSpecShape({}).map((issue) => issue.code);
  assert.ok(codes.includes("missing_hypothesis"));
  assert.ok(codes.includes("missing_model_ref"));
  assert.ok(codes.includes("missing_baseline"));
});

test("rejects non-object input", () => {
  const issues = validateExperimentSpecShape("nope");
  assert.equal(issues[0]?.code, "not_an_object");
});

test("exposes the shared schema version", () => {
  assert.equal(EXPERIMENT_SPEC_SCHEMA_VERSION, "1.0.0");
});

test("generated JSON Schema agrees with the client-side guard", () => {
  const schemaUrl = new URL("../schema/experiment-spec.schema.json", import.meta.url);
  const schema = JSON.parse(readFileSync(fileURLToPath(schemaUrl), "utf-8")) as {
    required: string[];
    properties: Record<string, unknown>;
  };

  // The guard's required fields must match the authoritative schema.
  assert.deepEqual(new Set(schema.required), new Set(["hypothesis", "model_ref", "baseline"]));
  // Canonical field name is `analyses`; the singular alias is input-only.
  assert.ok("analyses" in schema.properties);
  assert.ok(!("analysis" in schema.properties));
  // The new isolation control is part of the contract.
  assert.ok("execution" in schema.properties);
});
