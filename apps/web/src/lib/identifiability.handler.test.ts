/**
 * Handler-level test for the identifiability op.
 *
 * The Python bridge is mocked so this asserts only the request the handler
 * builds - in particular that the URL experiment id cannot be overridden by a
 * caller-supplied body field.
 */

import { beforeEach, describe, expect, it, vi } from "vitest";

const { callBridge } = vi.hoisted(() => ({ callBridge: vi.fn() }));

vi.mock("./bridge", () => ({ callBridge }));

import { handlers } from "./handlers";

interface BridgeCall {
  op: string;
  params: Record<string, unknown>;
}

describe("identifiability handler", () => {
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
    await handlers.identifiability("exp-url", {
      experiment_id: "exp-body",
      factors: ["mass", "stiffness"],
      step_scale: 0.01,
    });

    expect(callBridge).toHaveBeenCalledTimes(1);
    const request = lastRequest();
    expect(request.op).toBe("identifiability");
    expect(request.params).toEqual({
      factors: ["mass", "stiffness"],
      step_scale: 0.01,
      experiment_id: "exp-url",
    });
  });

  it("forwards study parameters unchanged when there is no id collision", async () => {
    await handlers.identifiability("exp-url", { outputs: ["x"] });

    expect(lastRequest().params).toEqual({ outputs: ["x"], experiment_id: "exp-url" });
  });
});
