"""Integration tests: the runner's isolated execution path (ADR-0005)."""

from __future__ import annotations

import threading

import pytest

from drw.execution.runner import Runner
from drw.models.registry import build_model
from drw.schema.experiment import ExperimentSpec

pytestmark = pytest.mark.integration


def _oscillator_spec(isolation: str, timeout_s: float = 30.0) -> ExperimentSpec:
    return ExperimentSpec(
        hypothesis="increasing k by 10% raises the oscillation frequency",
        model_ref={"model_id": "oscillator"},
        baseline={"m": 1.0, "k": 4.0, "c": 0.2, "x0": 1.0, "v0": 0.0},
        factors=({"parameter": "k", "values": [4.4]},),
        outputs=("x",),
        analyses=({"method": "delta"},),
        execution={"isolation": isolation, "timeout_s": timeout_s},
    )


def test_subprocess_and_in_process_agree_exactly():
    subprocess_result = Runner().run(_oscillator_spec("subprocess"))
    in_process_result = Runner().run(_oscillator_spec("in_process"))

    assert subprocess_result.isolation == "subprocess"
    assert in_process_result.isolation == "in_process"
    assert all(run.isolation == "subprocess" for run in subprocess_result.runs)
    assert subprocess_result.runs[0].metrics == in_process_result.runs[0].metrics
    assert (
        subprocess_result.comparisons[0].metrics["max_abs_delta"]
        == in_process_result.comparisons[0].metrics["max_abs_delta"]
    )


def test_timeout_is_enforced_and_recorded():
    result = Runner().run(_oscillator_spec("subprocess", timeout_s=0.001))
    assert result.baseline.failed
    assert result.baseline.timed_out is True
    assert any(d.code == "timeout" for d in result.baseline.diagnostics)
    assert result.comparisons == []


def test_timeout_failure_records_are_deterministic():
    first = Runner().run(_oscillator_spec("subprocess", timeout_s=0.001))
    second = Runner().run(_oscillator_spec("subprocess", timeout_s=0.001))
    assert [d.code for d in first.baseline.diagnostics] == [
        d.code for d in second.baseline.diagnostics
    ]
    assert first.baseline.error == second.baseline.error
    assert first.baseline.inputs == second.baseline.inputs


def test_cancellation_yields_failed_records_without_executing():
    cancel = threading.Event()
    cancel.set()
    result = Runner().run(_oscillator_spec("subprocess"), cancel_event=cancel)
    assert all(run.failed for run in result.runs)
    assert any(d.code == "cancelled" for d in result.baseline.diagnostics)
    assert result.comparisons == []


def test_custom_adapter_downgrades_to_in_process_with_a_warning():
    adapter = build_model("oscillator")
    result = Runner(adapter).run(_oscillator_spec("subprocess"))
    assert result.isolation == "in_process"
    assert any(d.code == "isolation_downgraded" for d in result.warnings)
