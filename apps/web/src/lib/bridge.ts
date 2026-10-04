/**
 * Server-side bridge to the Python scientific core.
 *
 * The UI never reimplements science. Every request is handed to
 * `python -m drw.api`, which reuses the same contracts and engine as the CLI
 * (`drw.execution.runner`, `drw.numerics.*`, `drw.store`).
 *
 * Process model: one short-lived child process per request, JSON on stdin, JSON
 * on stdout. Aborting the request (client navigation/cancel) kills the child, so
 * a long run can be cancelled. Python-side per-run timeouts are enforced by the
 * core (ADR-0005); they are not a sandbox.
 *
 * This module must only be imported from server code (route handlers / tests).
 */

import { spawn } from "node:child_process";
import { existsSync } from "node:fs";
import path from "node:path";

import type { BridgeRequest, BridgeResponse } from "./types";

export interface BridgeOptions {
  signal?: AbortSignal;
  workspace?: string;
}

/** Walk up from `start` until the repository root (the dir holding packages/core) is found. */
export function findRepoRoot(start: string = process.cwd()): string {
  let dir = path.resolve(start);
  for (let depth = 0; depth < 8; depth += 1) {
    if (existsSync(path.join(dir, "packages", "core", "pyproject.toml"))) {
      return dir;
    }
    const parent = path.dirname(dir);
    if (parent === dir) break;
    dir = parent;
  }
  return path.resolve(start, "..", "..");
}

/** Resolve the interpreter to run the bridge: DRW_PYTHON, then the repo venv, then PATH. */
export function resolvePython(repoRoot: string = findRepoRoot()): string {
  if (process.env.DRW_PYTHON) return process.env.DRW_PYTHON;
  const candidate =
    process.platform === "win32"
      ? path.join(repoRoot, ".venv", "Scripts", "python.exe")
      : path.join(repoRoot, ".venv", "bin", "python");
  if (existsSync(candidate)) return candidate;
  return process.platform === "win32" ? "python" : "python3";
}

/** Workspace directory for saved experiments (DRW_WORKSPACE overrides). */
export function resolveWorkspace(repoRoot: string = findRepoRoot()): string {
  return process.env.DRW_WORKSPACE ?? path.join(repoRoot, ".drw", "web-workspace");
}

/**
 * Run one bridge request. Always resolves to an envelope; transport failures are
 * reported as `bridge_error` (or `cancelled` when the caller aborts).
 */
export function callBridge<T = unknown>(
  request: BridgeRequest,
  options: BridgeOptions = {},
): Promise<BridgeResponse<T>> {
  const repoRoot = findRepoRoot();
  const env = {
    ...process.env,
    DRW_WORKSPACE: options.workspace ?? resolveWorkspace(repoRoot),
    PYTHONIOENCODING: "utf-8",
  };

  return new Promise<BridgeResponse<T>>((resolve) => {
    let settled = false;
    let stdout = "";
    let stderr = "";
    const child = spawn(resolvePython(repoRoot), ["-m", "drw.api"], {
      env,
      stdio: ["pipe", "pipe", "pipe"],
    });

    function cleanup(): void {
      options.signal?.removeEventListener("abort", onAbort);
    }

    function finish(response: BridgeResponse<T>): void {
      if (settled) return;
      settled = true;
      cleanup();
      resolve(response);
    }

    function onAbort(): void {
      child.kill();
      finish({
        ok: false,
        error: { code: "cancelled", message: "the request was cancelled", diagnostics: [] },
      });
    }

    child.stdout.on("data", (chunk: Buffer) => {
      stdout += chunk.toString();
    });
    child.stderr.on("data", (chunk: Buffer) => {
      stderr += chunk.toString();
    });
    child.on("error", (error: Error) => {
      finish({
        ok: false,
        error: {
          code: "bridge_error",
          message: `could not start the Python bridge: ${error.message}`,
          diagnostics: [],
        },
      });
    });
    child.on("close", () => {
      const text = stdout.trim();
      if (!text) {
        finish({
          ok: false,
          error: {
            code: "bridge_error",
            message: stderr.trim() || "the bridge produced no output",
            diagnostics: [],
          },
        });
        return;
      }
      try {
        finish(JSON.parse(text) as BridgeResponse<T>);
      } catch {
        finish({
          ok: false,
          error: {
            code: "bridge_error",
            message: `could not parse the bridge response: ${text.slice(0, 400)}`,
            diagnostics: [],
          },
        });
      }
    });

    if (options.signal) {
      if (options.signal.aborted) {
        onAbort();
        return;
      }
      options.signal.addEventListener("abort", onAbort, { once: true });
    }

    child.stdin.write(JSON.stringify(request));
    child.stdin.end();
  });
}
