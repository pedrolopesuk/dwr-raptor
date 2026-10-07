"""Durable, structured SI investigation state.

The chat transcript is an interface; this store is the scientific memory. State is
kept per investigation under the workspace root::

    <root>/si/<investigation_id>.json

An investigation id is either the draft sentinel, a stored experiment id
(``exp-<12 hex>``) or an explicit ``inv-<12 hex>`` id. Ids are validated and every
resolved path is confirmed to stay inside the store.
"""

from __future__ import annotations

import json
import os
import re
from datetime import UTC, datetime
from pathlib import Path

from drw.schema.serialization import dumps_pretty
from drw.schema.si import SIInvestigationState

__all__ = [
    "DRAFT_INVESTIGATION_ID",
    "INVESTIGATION_ID_PATTERN",
    "InvalidInvestigationId",
    "SIStore",
    "default_si_store",
    "new_state",
]

DRAFT_INVESTIGATION_ID = "draft"
INVESTIGATION_ID_PATTERN = re.compile(r"^(draft|exp-[0-9a-f]{12}|inv-[0-9a-f]{12})$")


class InvalidInvestigationId(ValueError):
    """Raised for a malformed investigation id or a path that escapes the store."""


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _default_root() -> Path:
    return Path(os.environ.get("DRW_WORKSPACE", ".drw/workspace"))


def default_si_store() -> SIStore:
    return SIStore(_default_root())


def new_state(
    investigation_id: str, project_id: str | None = None, *, at: str | None = None
) -> SIInvestigationState:
    """Create an empty investigation state with a created/updated timestamp."""
    timestamp = at or _now()
    return SIInvestigationState(
        investigation_id=investigation_id,
        project_id=project_id,
        created_at=timestamp,
        updated_at=timestamp,
    )


class SIStore:
    """Filesystem-backed store for SI investigation state."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)

    @property
    def si_dir(self) -> Path:
        return self.root / "si"

    def path(self, investigation_id: str) -> Path:
        if not INVESTIGATION_ID_PATTERN.match(investigation_id):
            raise InvalidInvestigationId(
                f"invalid investigation id {investigation_id!r}"
            )
        base = self.si_dir.resolve()
        candidate = (base / f"{investigation_id}.json").resolve()
        if candidate.parent != base:
            raise InvalidInvestigationId(
                f"investigation path escapes the store: {investigation_id!r}"
            )
        return candidate

    def exists(self, investigation_id: str) -> bool:
        try:
            return self.path(investigation_id).is_file()
        except InvalidInvestigationId:
            return False

    def load(self, investigation_id: str) -> SIInvestigationState | None:
        path = self.path(investigation_id)
        if not path.is_file():
            return None
        document = json.loads(path.read_text(encoding="utf-8"))
        return SIInvestigationState.model_validate(document)

    def load_or_create(
        self, investigation_id: str, project_id: str | None = None
    ) -> SIInvestigationState:
        state = self.load(investigation_id)
        if state is None:
            state = new_state(investigation_id, project_id)
            self.save(state)
        elif project_id is not None and state.project_id is None:
            state.project_id = project_id
            self.save(state)
        return state

    def save(
        self, state: SIInvestigationState, *, touch: bool = True, at: str | None = None
    ) -> Path:
        if touch:
            state.updated_at = at or _now()
        path = self.path(state.investigation_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(dumps_pretty(state) + "\n", encoding="utf-8")
        return path

    def delete(self, investigation_id: str) -> None:
        path = self.path(investigation_id)
        if path.is_file():
            path.unlink()

    def list(self) -> list[SIInvestigationState]:
        if not self.si_dir.is_dir():
            return []
        states: list[SIInvestigationState] = []
        for candidate in sorted(self.si_dir.glob("*.json")):
            if not candidate.is_file():
                continue
            try:
                states.append(
                    SIInvestigationState.model_validate(
                        json.loads(candidate.read_text(encoding="utf-8"))
                    )
                )
            except (
                OSError,
                json.JSONDecodeError,
                ValueError,
            ):  # pragma: no cover - corrupt entry
                continue
        return states
