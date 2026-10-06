"""Unit tests for the reproduction check (classification and comparison)."""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest

from drw.reproduce import (
    ReproduceError,
    ReproduceTolerances,
    _compare_output,
    _compare_run,
    _within_tolerance,
    reproduce_experiment,
)
from drw.schema.model import ModelRef
from drw.schema.result import ModelResult, OutputValue, RunRecord, RunStatus
from drw.schema.serialization import to_plain

pytestmark = pytest.mark.unit


def _run(run_id: str, values, *, label="variant", axis=None, status=RunStatus.SUCCEEDED):
    outputs: dict[str, OutputValue] = {}
    if status == RunStatus.SUCCEEDED:
        outputs["y"] = OutputValue(
            name="y",
            kind="timeseries",
            unit="dimensionless",
            values=list(values),
            axis=list(axis) if axis is not None else None,
            labels=("y",),
        )
    return RunRecord(
        run_id=run_id,
        experiment_id="exp-000000000000",
        label=label,
        status=status,
        model_ref=ModelRef(model_id="oscillator"),
        result=ModelResult(status=status, outputs=outputs),
    )


def _output(run_id: str, values, *, axis=None):
    return _run(run_id, values, axis=axis).result.output("y")


def test_within_tolerance_identity_and_equivalence():
    ref = np.array([1.0, 2.0, 3.0])
    assert _within_tolerance(ref, ref.copy(), 0.0, 0.0) is True
    assert _within_tolerance(ref, ref + 1e-9, 1e-6, 0.0) is True
    assert _within_tolerance(ref, ref + 0.5, 0.0, 1e-6) is False


def test_within_tolerance_absolute_and_relative():
    assert _within_tolerance(np.array([0.0]), np.array([1e-9]), 0.0, 1e-8) is True
    assert _within_tolerance(np.array([100.0]), np.array([100.1]), 1e-3, 0.0) is True
    assert _within_tolerance(np.array([100.0]), np.array([100.1]), 1e-6, 0.0) is False


def test_within_tolerance_is_undefined_for_non_finite():
    assert _within_tolerance(np.array([1.0, np.nan]), np.array([1.0, 2.0]), 1e-9, 1e-9) is None
    assert _within_tolerance(np.array([1.0, np.inf]), np.array([1.0, 2.0]), 1e-9, 1e-9) is None


def test_within_tolerance_boundary_and_zero_reference():
    # Strictly below / strictly above the absolute tolerance around a nonzero ref.
    assert _within_tolerance(np.array([1.0]), np.array([1.0 + 5e-10]), 0.0, 1e-9) is True
    assert _within_tolerance(np.array([1.0]), np.array([1.0 + 2e-9]), 0.0, 1e-9) is False
    # Exactly on a *representable* boundary: reference 0.0 makes the difference exact.
    assert _within_tolerance(np.array([0.0]), np.array([1e-9]), 0.0, 1e-9) is True
    assert (
        _within_tolerance(np.array([0.0]), np.array([np.nextafter(1e-9, np.inf)]), 0.0, 1e-9)
        is False
    )
    # Zero reference governed by the absolute tolerance.
    assert _within_tolerance(np.array([0.0]), np.array([1e-12]), 0.0, 1e-9) is True
    assert _within_tolerance(np.array([0.0]), np.array([1e-8]), 0.0, 1e-9) is False
    # rtol = 0 and atol = 0 require exact equality.
    assert _within_tolerance(np.array([2.0]), np.array([2.0]), 0.0, 0.0) is True
    assert (
        _within_tolerance(np.array([2.0]), np.array([np.nextafter(2.0, np.inf)]), 0.0, 0.0)
        is False
    )


def test_within_tolerance_boundary_is_representation_sensitive():
    # 1.0 + 1e-9 has no exact binary representation, so the difference exceeds 1e-9
    # even though it is "exactly on the boundary" in decimal. This matches numpy.isclose.
    on_boundary = 1.0 + 1e-9
    assert _within_tolerance(np.array([1.0]), np.array([on_boundary]), 0.0, 1e-9) is False
    assert bool(np.isclose(1.0, on_boundary, rtol=0.0, atol=1e-9)) is False


def _run_outputs(run_id: str, outputs: dict[str, list], *, label="variant") -> RunRecord:
    values = {
        name: OutputValue(
            name=name, kind="timeseries", unit="dimensionless", values=list(data), labels=(name,)
        )
        for name, data in outputs.items()
    }
    return RunRecord(
        run_id=run_id,
        experiment_id="exp-000000000000",
        label=label,
        status=RunStatus.SUCCEEDED,
        model_ref=ModelRef(model_id="oscillator"),
        result=ModelResult(status=RunStatus.SUCCEEDED, outputs=values),
    )


def test_compare_run_mixed_different_and_incomparable():
    """One output outside tolerance, another non-finite: run is not comparable, but the
    known numerical difference is still exposed per output."""
    tolerances = ReproduceTolerances(rtol=0.0, atol=1e-9)
    reference = _run_outputs("r0", {"a": [1.0, 2.0], "b": [1.0, 2.0]}, label="baseline")
    fresh = _run_outputs("f0", {"a": [1.0, 9.0], "b": [1.0, float("nan")]}, label="baseline")

    comparison = _compare_run(0, reference, fresh, tolerances)

    assert comparison.comparable is False
    assert comparison.passes_tolerance is None
    by_name = {output.output: output for output in comparison.outputs}
    assert by_name["a"].status == "different" and by_name["a"].passes_tolerance is False
    assert by_name["b"].status == "incomparable"


def test_reproduce_mixed_difference_is_inconclusive_but_still_reported(monkeypatch):
    stored = [_run_outputs("r0", {"a": [1.0, 2.0], "b": [1.0, 2.0]}, label="baseline")]
    fresh = [_run_outputs("f0", {"a": [1.0, 9.0], "b": [1.0, float("nan")]}, label="baseline")]
    _patch_runner(monkeypatch, fresh)

    report = reproduce_experiment(
        "exp-000000000000", rtol=0.0, atol=1e-9, store=_FakeStore(_payload(stored))
    )

    # Top-level: inconclusive per the documented precedence (cannot be a success) ...
    assert report.verdict == "inconclusive"
    assert report.numerical == "inconclusive"
    assert report.verdict not in ("identical", "equivalent_within_tolerance")
    # ... but the known output-level difference is not hidden by the incomparability.
    outputs = {output.output: output for output in report.runs[0].outputs}
    assert outputs["a"].status == "different"
    assert outputs["b"].status == "incomparable"


def test_compare_output_classifies_identical_equivalent_and_different():
    tolerances = ReproduceTolerances(rtol=1e-6, atol=1e-9)
    ref_run = _run("r0", [1.0, 2.0, 3.0], label="baseline")
    fresh_run = _run("f0", [1.0, 2.0, 3.0], label="baseline")
    identical = _compare_output(ref_run, fresh_run, _output("r0", [1.0, 2.0, 3.0]), _output("f0", [1.0, 2.0, 3.0]), tolerances)
    assert identical.status == "identical" and identical.identical is True

    close = _compare_output(ref_run, fresh_run, _output("r0", [1.0, 2.0, 3.0]), _output("f0", [1.0, 2.0, 3.0000001]), tolerances)
    assert close.status == "equivalent" and close.passes_tolerance is True

    far = _compare_output(ref_run, fresh_run, _output("r0", [1.0, 2.0, 3.0]), _output("f0", [1.0, 2.0, 9.0]), tolerances)
    assert far.status == "different" and far.passes_tolerance is False
    assert far.mae is not None and far.max_abs_delta == pytest.approx(6.0)


def test_compare_output_reports_shape_and_axis_incompatibility():
    tolerances = ReproduceTolerances(rtol=1e-6, atol=1e-9)
    ref_run = _run("r0", [1.0, 2.0, 3.0], label="baseline")
    fresh_run = _run("f0", [1.0, 2.0], label="baseline")
    shape = _compare_output(ref_run, fresh_run, _output("r0", [1.0, 2.0, 3.0]), _output("f0", [1.0, 2.0]), tolerances)
    assert shape.comparable is False and shape.status == "incomparable"

    axis = _compare_output(
        ref_run,
        fresh_run,
        _output("r0", [1.0, 2.0, 3.0], axis=[0.0, 1.0, 2.0]),
        _output("f0", [1.0, 2.0, 3.0], axis=[0.0, 1.5, 3.0]),
        tolerances,
    )
    assert axis.comparable is False and axis.interpolated is True


def test_compare_run_aggregates_outputs():
    tolerances = ReproduceTolerances(rtol=1e-6, atol=1e-9)
    reference = _run("r0", [1.0, 2.0, 3.0], label="baseline")
    fresh = _run("f0", [1.0, 2.0, 3.0], label="baseline")
    comparison = _compare_run(0, reference, fresh, tolerances)
    assert comparison.comparable is True
    assert comparison.identical is True
    assert comparison.passes_tolerance is True


# ---------------------------------------------------------------------------
# End-to-end classification with a stubbed runner and a fake store.
# ---------------------------------------------------------------------------


class _FakeStore:
    def __init__(self, payload):
        self._payload = payload

    def load(self, experiment_id):
        return self._payload


def _spec():
    return {
        "hypothesis": "h",
        "model_ref": {"model_id": "oscillator", "version": "1.0.0"},
        "baseline": {"m": 1.0, "k": 4.0, "c": 0.2, "x0": 1.0, "v0": 0.0},
        "outputs": ["y"],
        "analyses": [{"method": "delta"}],
    }


def _payload(stored_runs, *, model_hash=None, run_count=None, environment=None):
    from drw.execution.environment import environment_fingerprint
    from drw.models.registry import build_model

    spec_dict = _spec()
    schema = build_model("oscillator").describe()
    results = {
        "runs": [to_plain(run) for run in stored_runs],
        "spec_hash": "",
        "model_hash": model_hash if model_hash is not None else schema.content_hash(),
        "environment": environment if environment is not None else environment_fingerprint(),
    }
    return {"meta": {}, "spec": spec_dict, "results": results}


def _patch_runner(monkeypatch, fresh_runs):
    monkeypatch.setattr(
        "drw.reproduce.Runner",
        lambda: SimpleNamespace(run=lambda spec, **kwargs: SimpleNamespace(runs=fresh_runs)),
    )


def test_reproduce_identical(monkeypatch):
    stored = [_run("r0", [1.0, 2.0, 3.0], label="baseline")]
    fresh = [_run("f0", [1.0, 2.0, 3.0], label="baseline")]
    _patch_runner(monkeypatch, fresh)
    report = reproduce_experiment(
        "exp-000000000000", rtol=1e-6, atol=1e-9, store=_FakeStore(_payload(stored))
    )
    assert report.verdict == "identical"
    assert report.numerical == "identical"
    assert report.fresh_runs_persisted is False
    assert report.reference_run_ids == ["r0"] and report.fresh_run_ids == ["f0"]


def test_reproduce_equivalent_within_tolerance(monkeypatch):
    stored = [_run("r0", [1.0, 2.0, 3.0], label="baseline")]
    fresh = [_run("f0", [1.0, 2.0, 3.0000001], label="baseline")]
    _patch_runner(monkeypatch, fresh)
    report = reproduce_experiment(
        "exp-000000000000", rtol=1e-6, atol=1e-9, store=_FakeStore(_payload(stored))
    )
    assert report.verdict == "equivalent_within_tolerance"


def test_reproduce_different(monkeypatch):
    stored = [_run("r0", [1.0, 2.0, 3.0], label="baseline")]
    fresh = [_run("f0", [1.0, 2.0, 9.0], label="baseline")]
    _patch_runner(monkeypatch, fresh)
    report = reproduce_experiment(
        "exp-000000000000", rtol=1e-6, atol=1e-9, store=_FakeStore(_payload(stored))
    )
    assert report.verdict == "different"
    assert report.runs[0].outputs[0].status == "different"


def test_reproduce_execution_failed(monkeypatch):
    stored = [_run("r0", [1.0], label="baseline")]
    fresh = [_run("f0", [], label="baseline", status=RunStatus.FAILED)]
    _patch_runner(monkeypatch, fresh)
    report = reproduce_experiment(
        "exp-000000000000", rtol=1e-6, atol=1e-9, store=_FakeStore(_payload(stored))
    )
    assert report.verdict == "execution_failed"
    assert report.numerical == "inconclusive"


def test_reproduce_inconclusive_on_shape_mismatch(monkeypatch):
    stored = [_run("r0", [1.0, 2.0, 3.0], label="baseline")]
    fresh = [_run("f0", [1.0, 2.0], label="baseline")]
    _patch_runner(monkeypatch, fresh)
    report = reproduce_experiment(
        "exp-000000000000", rtol=1e-6, atol=1e-9, store=_FakeStore(_payload(stored))
    )
    assert report.verdict == "inconclusive"


def test_reproduce_reports_provenance_differences(monkeypatch):
    stored = [_run("r0", [1.0, 2.0, 3.0], label="baseline")]
    fresh = [_run("f0", [1.0, 2.0, 3.0], label="baseline")]
    _patch_runner(monkeypatch, fresh)
    report = reproduce_experiment(
        "exp-000000000000",
        rtol=1e-6,
        atol=1e-9,
        store=_FakeStore(_payload(stored, model_hash="deadbeef")),
    )
    assert report.provenance.model_hash_match is False
    assert report.provenance.differences
    # Provenance differences do not silently change the numerical verdict.
    assert report.verdict == "identical"


def test_reproduce_invalid_tolerances():
    with pytest.raises(ReproduceError):
        reproduce_experiment("x", rtol=-1.0, atol=0.0, store=_FakeStore({}))
    with pytest.raises(ReproduceError):
        reproduce_experiment("x", rtol=1.0, atol=0.0, store=_FakeStore({}))


def test_reproduce_missing_reference_runs(monkeypatch):
    _patch_runner(monkeypatch, [])
    with pytest.raises(ReproduceError):
        reproduce_experiment(
            "exp-000000000000",
            rtol=1e-6,
            atol=1e-9,
            store=_FakeStore({"meta": {}, "spec": _spec(), "results": {"runs": []}}),
        )
