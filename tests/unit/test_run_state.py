"""Unit tests for the run lifecycle state machine."""

from __future__ import annotations

import pytest

from drw.schema.result import RunStatus, allowed_run_transition

pytestmark = pytest.mark.unit


def test_happy_path_transitions_are_allowed():
    path = [
        (RunStatus.DRAFT, RunStatus.VALIDATED),
        (RunStatus.VALIDATED, RunStatus.QUEUED),
        (RunStatus.QUEUED, RunStatus.RUNNING),
        (RunStatus.RUNNING, RunStatus.SUCCEEDED),
        (RunStatus.SUCCEEDED, RunStatus.ANALYZED),
        (RunStatus.ANALYZED, RunStatus.VERIFIED),
        (RunStatus.VERIFIED, RunStatus.EXPORTED),
    ]
    for source, target in path:
        assert allowed_run_transition(source, target)


def test_failure_is_reachable_and_terminal():
    assert allowed_run_transition(RunStatus.RUNNING, RunStatus.FAILED)
    assert not allowed_run_transition(RunStatus.FAILED, RunStatus.RUNNING)


def test_cannot_skip_states():
    assert not allowed_run_transition(RunStatus.DRAFT, RunStatus.SUCCEEDED)
    assert not allowed_run_transition(RunStatus.QUEUED, RunStatus.SUCCEEDED)
