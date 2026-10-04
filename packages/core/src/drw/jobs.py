"""Minimal local job journal for **measured** execution progress.

The bridge is one-shot, so it cannot stream. Instead the client supplies a
``job_id``, the bridge appends a JSONL event per completed run to
``<workspace>/jobs/<job_id>.jsonl``, and the client polls ``job_status`` while the
run request is still open.

Design rules (ADR-0009):

* Only **real events** are recorded - ``started``, ``run_completed``, ``finished``.
  There are no percentages and no estimates; progress is "k of n runs completed".
* Cancellation is unchanged: the client aborts the run request, which kills the
  bridge child. The journal then simply stops without a ``finished`` event, and
  the client (which initiated the abort) reports it as cancelled.
* Journals are tiny and live in the workspace; stale ones are pruned opportunistically.
"""

from __future__ import annotations

import json
import re
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

__all__ = ["InvalidJobId", "JobJournal", "derive_phase"]

JOB_ID_PATTERN = re.compile(r"^job-[0-9a-f]{16}$")


class InvalidJobId(ValueError):
    """Raised when a job id is malformed or would escape the workspace."""


def _iso() -> str:
    return datetime.now(UTC).isoformat()


class JobJournal:
    """Append-only JSONL journal for one job."""

    def __init__(self, root: str | Path, job_id: str) -> None:
        if not JOB_ID_PATTERN.match(job_id):
            raise InvalidJobId(f"invalid job id {job_id!r}")
        self.root = Path(root)
        jobs = (self.root / "jobs").resolve()
        candidate = (jobs / f"{job_id}.jsonl").resolve()
        if jobs != candidate.parent:
            raise InvalidJobId(f"job path escapes the workspace: {job_id!r}")
        self.job_id = job_id
        self.path = candidate

    @property
    def directory(self) -> Path:
        return self.path.parent

    def append(self, event: str, **data: Any) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        record = {"seq": self._next_seq(), "event": event, "at": _iso(), **data}
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, sort_keys=True) + "\n")

    def read(self) -> list[dict[str, Any]]:
        if not self.path.is_file():
            return []
        events: list[dict[str, Any]] = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:  # pragma: no cover - torn write
                continue
        return events

    def _next_seq(self) -> int:
        return len(self.read()) + 1

    def prune(self, *, max_age_hours: float = 24.0) -> int:
        """Delete journals older than ``max_age_hours``. Returns the count removed."""
        if not self.directory.is_dir():
            return 0
        cutoff = time.time() - max_age_hours * 3600
        removed = 0
        for path in self.directory.glob("*.jsonl"):
            try:
                if path.stat().st_mtime < cutoff:
                    path.unlink()
                    removed += 1
            except OSError:  # pragma: no cover - concurrent delete
                continue
        return removed


def derive_phase(events: list[dict[str, Any]]) -> dict[str, Any]:
    """Summarize a journal into a coarse, *measured* phase."""
    started = next((e for e in events if e["event"] == "started"), None)
    finished = next((e for e in events if e["event"] == "finished"), None)
    completed = sum(1 for e in events if e["event"] == "run_completed")
    total = int(started["total_runs"]) if started and "total_runs" in started else None

    if finished is not None:
        phase = "finished"
    elif started is not None:
        phase = "running"
    elif events:
        phase = "unknown"
    else:
        phase = "pending"

    return {
        "phase": phase,
        "terminal": finished is not None,
        "completed_runs": completed,
        "total_runs": total,
        "status": finished.get("status") if finished else None,
        "events": events,
    }
