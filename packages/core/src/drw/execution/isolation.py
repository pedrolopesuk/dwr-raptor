"""Hard-enforced isolated execution of a single model run.

Every run is executed by ``python -m drw.execution.worker`` in a fresh child
process with:

* a **hard wall-clock timeout** (``RunContext.timeout_s``) after which the process
  *tree* is killed;
* optional POSIX resource limits (CPU seconds, address space);
* stdout/stderr redirected to files in a private temp directory (so the child can
  never deadlock on a full pipe);
* deterministic failure records for timeout, cancellation, worker crash and
  malformed responses;
* guaranteed temp-directory cleanup.

Security honesty: this is process isolation with a timeout, **not** a sandbox. It
does not restrict filesystem or network access. On Windows only the wall-clock
timeout and process-tree kill are enforced; POSIX style ``rlimit`` limits are
unavailable. See ``docs/architecture/ADR-0005-isolated-execution.md``.
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import tempfile
import threading
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from drw.execution.context import RunContext
from drw.schema.result import Diagnostic, ModelResult, RunStatus
from drw.schema.serialization import dumps_pretty

__all__ = ["ExecutionOutcome", "SubprocessExecutor"]

WORKER_MODULE = "drw.execution.worker"
_POLL_INTERVAL_S = 0.1
_STDERR_TAIL_CHARS = 2000


@dataclass(slots=True)
class ExecutionOutcome:
    """The result of one isolated execution attempt."""

    result: ModelResult | None
    diagnostics: tuple[Diagnostic, ...]
    isolation: str
    timed_out: bool
    exit_code: int | None
    duration_s: float
    stderr_tail: str = ""

    @property
    def ok(self) -> bool:
        return self.result is not None and self.result.ok


def _tail(path: Path, limit: int = _STDERR_TAIL_CHARS) -> str:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    return text[-limit:].strip()


class SubprocessExecutor:
    """Run models in an isolated child process with an enforced timeout."""

    def __init__(
        self,
        *,
        python_executable: str | None = None,
        memory_limit_mb: int | None = None,
        cpu_limit_s: int | None = None,
        kill_grace_s: float = 5.0,
        command_template: Sequence[str] | None = None,
    ) -> None:
        self._python = python_executable or sys.executable
        self._memory_limit_mb = memory_limit_mb
        self._cpu_limit_s = cpu_limit_s
        self._kill_grace_s = kill_grace_s
        # Advanced seam (used by tests): a command *template* appended after the
        # interpreter, with ``{request}`` and ``{response}`` placeholders. The
        # default runs the real worker module.
        self._command_template = tuple(command_template) if command_template else (
            "-m",
            WORKER_MODULE,
            "{request}",
            "{response}",
        )

    # -- public API ---------------------------------------------------------

    def enforced_limits(self) -> dict[str, Any]:
        """Describe what is actually enforced on this platform."""
        posix = os.name != "nt"
        return {
            "platform": os.name,
            "wall_clock_timeout": True,
            "process_tree_kill": True,
            "memory_limit": bool(posix and self._memory_limit_mb is not None),
            "cpu_limit": bool(posix and self._cpu_limit_s is not None),
            "filesystem_sandbox": False,
            "network_sandbox": False,
        }

    def execute(
        self,
        model_id: str,
        inputs: Mapping[str, Any],
        context: RunContext,
        *,
        cancel_event: threading.Event | None = None,
    ) -> ExecutionOutcome:
        timeout_s = float(context.timeout_s)
        workdir = Path(tempfile.mkdtemp(prefix="drw-run-"))
        request_path = workdir / "request.json"
        response_path = workdir / "response.json"
        stdout_path = workdir / "stdout.log"
        stderr_path = workdir / "stderr.log"

        request = {
            "model_id": model_id,
            "inputs": dict(inputs),
            "run_id": context.run_id,
            "experiment_id": context.experiment_id,
            "seed": context.seed,
            "solver": context.solver,
            "rtol": context.rtol,
            "atol": context.atol,
            "timeout_s": timeout_s,
        }
        request_path.write_text(dumps_pretty(request) + "\n", encoding="utf-8")

        start = time.perf_counter()
        process: subprocess.Popen[bytes] | None = None
        timed_out = False
        cancelled = False
        stdout_stream = stdout_path.open("wb")
        stderr_stream = stderr_path.open("wb")
        try:
            process = self._spawn(request_path, response_path, workdir, stdout_stream, stderr_stream)
            deadline = start + timeout_s
            while True:
                if cancel_event is not None and cancel_event.is_set():
                    cancelled = True
                    self._kill_tree(process)
                    break
                remaining = deadline - time.perf_counter()
                if remaining <= 0:
                    timed_out = True
                    self._kill_tree(process)
                    break
                try:
                    process.wait(timeout=min(_POLL_INTERVAL_S, remaining))
                    break
                except subprocess.TimeoutExpired:
                    continue

            duration = time.perf_counter() - start
            stderr_tail = _tail(stderr_path)
            exit_code = process.returncode

            if cancelled:
                return self._failure(
                    "cancelled", "run was cancelled", duration, exit_code, stderr_tail
                )
            if timed_out:
                return self._failure(
                    "timeout",
                    f"run exceeded timeout_s={timeout_s:g}s and was terminated",
                    duration,
                    exit_code,
                    stderr_tail,
                    timed_out=True,
                )
            return self._read_response(
                response_path, duration, exit_code, stderr_tail
            )
        finally:
            stdout_stream.close()
            stderr_stream.close()
            import shutil

            shutil.rmtree(workdir, ignore_errors=True)

    # -- internals ----------------------------------------------------------

    def _spawn(
        self,
        request_path: Path,
        response_path: Path,
        workdir: Path,
        stdout_stream,
        stderr_stream,
    ) -> subprocess.Popen[bytes]:
        args = [
            self._python,
            *(
                part.format(request=request_path, response=response_path)
                for part in self._command_template
            ),
        ]
        kwargs: dict[str, Any] = {}
        if os.name == "nt":
            kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
        else:
            kwargs["start_new_session"] = True
            preexec = self._rlimit_preexec()
            if preexec is not None:
                kwargs["preexec_fn"] = preexec
        return subprocess.Popen(
            args,
            cwd=str(workdir),
            stdout=stdout_stream,
            stderr=stderr_stream,
            **kwargs,
        )

    def _rlimit_preexec(self):
        """Best-effort POSIX resource limits applied in the child before exec."""
        memory_mb = self._memory_limit_mb
        cpu_s = self._cpu_limit_s
        if memory_mb is None and cpu_s is None:
            return None

        def _apply() -> None:  # pragma: no cover - runs in the forked child
            import resource

            if cpu_s is not None:
                resource.setrlimit(resource.RLIMIT_CPU, (int(cpu_s), int(cpu_s) + 1))
            if memory_mb is not None:
                nbytes = int(memory_mb) * 1024 * 1024
                resource.setrlimit(resource.RLIMIT_AS, (nbytes, nbytes))

        return _apply

    def _kill_tree(self, process: subprocess.Popen[bytes]) -> None:
        if process.poll() is not None:
            return
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(process.pid)],
                capture_output=True,
                check=False,
            )
        else:
            try:
                os.killpg(os.getpgid(process.pid), signal.SIGKILL)
            except (ProcessLookupError, PermissionError):  # pragma: no cover
                process.kill()
        try:
            process.wait(timeout=self._kill_grace_s)
        except subprocess.TimeoutExpired:  # pragma: no cover - last resort
            process.kill()

    def _read_response(
        self,
        response_path: Path,
        duration: float,
        exit_code: int | None,
        stderr_tail: str,
    ) -> ExecutionOutcome:
        if not response_path.exists():
            return self._failure(
                "worker_crash",
                f"worker produced no response (exit code {exit_code})"
                + (f"; stderr: {stderr_tail}" if stderr_tail else ""),
                duration,
                exit_code,
                stderr_tail,
            )
        try:
            payload = json.loads(response_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            return self._failure(
                "invalid_worker_response",
                f"could not parse worker response: {exc}",
                duration,
                exit_code,
                stderr_tail,
            )
        if not isinstance(payload, dict) or "ok" not in payload:
            return self._failure(
                "invalid_worker_response",
                "worker response is missing the 'ok' field",
                duration,
                exit_code,
                stderr_tail,
            )
        if not payload.get("ok"):
            return self._failure(
                "worker_model_error",
                f"worker raised: {payload.get('error', 'unknown error')}",
                duration,
                exit_code,
                stderr_tail,
            )
        try:
            result = ModelResult.model_validate(payload["result"])
        except Exception as exc:
            return self._failure(
                "invalid_worker_response",
                f"worker result failed validation: {type(exc).__name__}: {exc}",
                duration,
                exit_code,
                stderr_tail,
            )
        return ExecutionOutcome(
            result=result,
            diagnostics=(),
            isolation="subprocess",
            timed_out=False,
            exit_code=exit_code,
            duration_s=duration,
            stderr_tail=stderr_tail,
        )

    def _failure(
        self,
        code: str,
        message: str,
        duration: float,
        exit_code: int | None,
        stderr_tail: str,
        *,
        timed_out: bool = False,
    ) -> ExecutionOutcome:
        diagnostic = Diagnostic(level="error", code=code, message=message)
        return ExecutionOutcome(
            result=ModelResult(status=RunStatus.FAILED, outputs={}, diagnostics=(diagnostic,)),
            diagnostics=(diagnostic,),
            isolation="subprocess",
            timed_out=timed_out,
            exit_code=exit_code,
            duration_s=duration,
            stderr_tail=stderr_tail,
        )
