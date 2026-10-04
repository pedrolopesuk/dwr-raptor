"""Unit tests for the local job journal (ADR-0009)."""

from __future__ import annotations

import os
import time

import pytest

from drw.jobs import InvalidJobId, JobJournal, derive_phase

pytestmark = pytest.mark.unit

JOB = "job-" + "a" * 16


def test_append_and_read_roundtrip(tmp_path):
    journal = JobJournal(tmp_path, JOB)
    journal.append("started", total_runs=3)
    journal.append("run_completed", index=1, run_id="r1", status="succeeded")
    events = journal.read()
    assert [e["event"] for e in events] == ["started", "run_completed"]
    assert [e["seq"] for e in events] == [1, 2]
    assert events[0]["total_runs"] == 3


def test_invalid_job_id_is_rejected(tmp_path):
    for bad in ("job-XYZ", "job-", "../../etc", "job-" + "a" * 15):
        with pytest.raises(InvalidJobId):
            JobJournal(tmp_path, bad)


def test_journal_stays_inside_the_workspace(tmp_path):
    journal = JobJournal(tmp_path, JOB)
    assert tmp_path.resolve() in journal.path.resolve().parents


def test_derive_phase_tracks_measured_progress(tmp_path):
    journal = JobJournal(tmp_path, JOB)
    assert derive_phase(journal.read())["phase"] == "pending"

    journal.append("started", total_runs=2)
    journal.append("run_completed", index=1, run_id="r1", status="succeeded")
    running = derive_phase(journal.read())
    assert running["phase"] == "running"
    assert running["completed_runs"] == 1
    assert running["total_runs"] == 2
    assert running["terminal"] is False

    journal.append("finished", status="succeeded", counts={"succeeded": 2})
    finished = derive_phase(journal.read())
    assert finished["phase"] == "finished"
    assert finished["terminal"] is True
    assert finished["status"] == "succeeded"


def test_prune_removes_only_stale_journals(tmp_path):
    journal = JobJournal(tmp_path, JOB)
    journal.append("started", total_runs=1)
    # Make the journal look old.
    old = time.time() - 10_000
    os.utime(journal.path, (old, old))
    fresh = JobJournal(tmp_path, "job-" + "b" * 16)
    fresh.append("started", total_runs=1)

    removed = journal.prune(max_age_hours=1)

    assert removed == 1
    assert not journal.path.exists()
    assert fresh.path.exists()
