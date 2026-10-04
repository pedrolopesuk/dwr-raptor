"""Unit tests for hard-enforced isolated execution (ADR-0005)."""

from __future__ import annotations

import tempfile
import threading
import time
from pathlib import Path

import pytest

from drw.execution.context import RunContext
from drw.execution.isolation import SubprocessExecutor

pytestmark = pytest.mark.unit

SLEEP_CMD = ("-c", "import time; time.sleep(30)")
CRASH_CMD = ("-c", "import sys; sys.exit(3)")
BAD_RESPONSE_CMD = (
    "-c",
    "import sys; open(sys.argv[2], 'w').write('not json')",
    "{request}",
    "{response}",
)


def _context(timeout_s: float) -> RunContext:
    return RunContext(run_id="r", experiment_id="e", timeout_s=timeout_s)


def test_wall_clock_timeout_kills_the_process():
    executor = SubprocessExecutor(command_template=SLEEP_CMD)
    start = time.perf_counter()
    outcome = executor.execute("oscillator", {"m": 1.0}, _context(0.6))
    elapsed = time.perf_counter() - start

    assert outcome.timed_out is True
    assert [d.code for d in outcome.diagnostics] == ["timeout"]
    assert outcome.result is not None and not outcome.result.ok
    # Killed promptly rather than waiting for the full 30s sleep.
    assert elapsed < 15.0


def test_worker_crash_is_a_deterministic_failure():
    executor = SubprocessExecutor(command_template=CRASH_CMD)
    outcome = executor.execute("oscillator", {"m": 1.0}, _context(10.0))
    assert [d.code for d in outcome.diagnostics] == ["worker_crash"]
    assert outcome.exit_code == 3
    assert outcome.result is not None and not outcome.result.ok


def test_invalid_worker_response_is_rejected():
    executor = SubprocessExecutor(command_template=BAD_RESPONSE_CMD)
    outcome = executor.execute("oscillator", {"m": 1.0}, _context(10.0))
    assert [d.code for d in outcome.diagnostics] == ["invalid_worker_response"]


def test_cancellation_stops_the_run():
    executor = SubprocessExecutor(command_template=SLEEP_CMD)
    cancel = threading.Event()
    threading.Timer(0.4, cancel.set).start()
    start = time.perf_counter()
    outcome = executor.execute("oscillator", {"m": 1.0}, _context(30.0), cancel_event=cancel)
    assert [d.code for d in outcome.diagnostics] == ["cancelled"]
    assert time.perf_counter() - start < 15.0


def test_successful_isolated_run_round_trips_a_result():
    executor = SubprocessExecutor()
    inputs = {"m": 1.0, "k": 4.0, "c": 0.2, "x0": 1.0, "v0": 0.0}
    outcome = executor.execute("oscillator", inputs, _context(60.0))
    assert outcome.ok
    assert outcome.result is not None
    assert outcome.isolation == "subprocess"
    assert "x" in outcome.result.outputs


def test_temp_directories_are_cleaned_up():
    executor = SubprocessExecutor()
    prefix = "drw-run-"
    before = {p.name for p in Path(tempfile.gettempdir()).glob(f"{prefix}*")}
    executor.execute(
        "oscillator", {"m": 1.0, "k": 4.0, "c": 0.2, "x0": 1.0, "v0": 0.0}, _context(60.0)
    )
    after = {p.name for p in Path(tempfile.gettempdir()).glob(f"{prefix}*")}
    assert after <= before


def test_enforced_limits_are_reported_honestly():
    limits = SubprocessExecutor().enforced_limits()
    assert limits["wall_clock_timeout"] is True
    assert limits["process_tree_kill"] is True
    # We must not claim sandboxing we do not provide.
    assert limits["filesystem_sandbox"] is False
    assert limits["network_sandbox"] is False


def test_isolated_run_does_not_write_into_the_repository(tmp_path, monkeypatch):
    # The worker's working directory is a private temp dir, never the caller's cwd.
    monkeypatch.chdir(tmp_path)
    executor = SubprocessExecutor()
    executor.execute(
        "oscillator", {"m": 1.0, "k": 4.0, "c": 0.2, "x0": 1.0, "v0": 0.0}, _context(60.0)
    )
    assert list(tmp_path.iterdir()) == []
