/**
 * Handler-level test for the global-sensitivity op.
 *
 * The Python bridge is mocked so this asserts only the request the handler
 * builds - in particular that the URL experiment id cannot be overridden by a
 * caller-supplied body field (audit F6).
 */

import { beforeEach, describe, expect, it, vi } from "vitest";

const { callBridge } = vi.hoisted(() => ({ callBridge: vi.fn() }));

vi.mock("./bridge", () => ({ callBridge }));

import { handlers } from "./handlers";

interface BridgeCall {
  op: string;
  params: Record<string, unknown>;
}

describe("globalSensitivity handler", () => {
  beforeEach(() => {
    callBridge.mockReset();
    callBridge.mockResolvedValue({ ok: true, data: { report: {} } });
  });

  function lastRequest(): BridgeCall {
    const call = callBridge.mock.calls[0];
    if (!call) throw new Error("callBridge was not called");
    return call[0] as BridgeCall;
  }

  it("keeps the URL experiment id authoritative over the request body", async () => {
    await handlers.globalSensitivity("exp-url", {
      experiment_id: "exp-body",
      sample_count: 8,
      factors: ["alpha"],
    });

    expect(callBridge).toHaveBeenCalledTimes(1);
    const request = lastRequest();
    expect(request.op).toBe("global_sensitivity");
    expect(request.params).toEqual({
      sample_count: 8,
      factors: ["alpha"],
      experiment_id: "exp-url",
    });
  });

  it("forwards study parameters unchanged when there is no id collision", async () => {
    await handlers.globalSensitivity("exp-url", { output: "peak_prey", seed: 3 });

    expect(lastRequest().params).toEqual({
      output: "peak_prey",
      seed: 3,
      experiment_id: "exp-url",
    });
  });
});
