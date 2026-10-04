"""Isolated worker entry point for one model execution.

The parent (:class:`drw.execution.isolation.SubprocessExecutor`) writes a JSON
*request* file and waits with a hard wall-clock timeout. This module executes the
model in a **separate process** and writes a JSON *response* file.

Protocol (both strict JSON, produced via the canonical serializer)::

    request  = {model_id, inputs, run_id, experiment_id, seed, solver, rtol, atol, timeout_s}
    response = {"ok": true,  "result": <ModelResult>}
             | {"ok": false, "error": "<TypeError>: <message>"}

The exit code is ``0`` for any *handled* outcome - including a model that reports
``FAILED`` - because "the model failed" is a valid result, not a worker crash. A
non-zero exit or a missing/invalid response file means the worker itself crashed
or was killed, which the parent records deterministically.

This worker deliberately imports only the schema, adapter and registry: it must
never import the runner, so an isolated model cannot reach the orchestration
layer.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from drw.schema.serialization import dumps_pretty

__all__ = ["main"]

WORKER_USAGE = "usage: python -m drw.execution.worker <request.json> <response.json>"


def _execute(request: dict[str, Any]) -> dict[str, Any]:
    # Imported lazily so `python -m drw.execution.worker` has a small import graph.
    from drw.execution.context import RunContext
    from drw.models.registry import build_model

    model = build_model(request["model_id"])
    context = RunContext(
        run_id=request["run_id"],
        experiment_id=request["experiment_id"],
        seed=request.get("seed"),
        timeout_s=float(request.get("timeout_s", 60.0)),
        solver=request.get("solver", "auto"),
        rtol=float(request.get("rtol", 1e-8)),
        atol=float(request.get("atol", 1e-10)),
    )
    result = model.run(request.get("inputs", {}), context)
    return {"ok": True, "result": result.model_dump(mode="json")}


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) != 2:
        print(WORKER_USAGE, file=sys.stderr)
        return 2

    request_path, response_path = (Path(arg) for arg in args)
    try:
        request = json.loads(request_path.read_text(encoding="utf-8"))
        payload = _execute(request)
    except BaseException as exc:
        payload = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}

    try:
        response_path.write_text(dumps_pretty(payload) + "\n", encoding="utf-8")
    except Exception as exc:  # pragma: no cover - disk failure path
        print(f"worker: failed to write response: {exc}", file=sys.stderr)
        return 3
    return 0


if __name__ == "__main__":  # pragma: no cover - exercised via subprocess
    raise SystemExit(main())
