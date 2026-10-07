"""Scientific Intelligence (SI): the conversational orchestration layer.

SI turns a research question into a structured, inspectable investigation plan and
drives existing DRW capabilities through a controlled action registry. It never
executes arbitrary code, never bypasses approval, and never fabricates results.

The public entry points are :func:`ask`, :func:`preview_step`,
:func:`approve_and_execute` and :func:`get_state`; the action registry is
:func:`default_registry`.
"""

from __future__ import annotations

from drw.si.actions import (
    SIAction,
    SIActionContext,
    SIActionError,
    SIActionOutcome,
    SIActionRegistry,
    default_registry,
)
from drw.si.context import build_action_context, build_context
from drw.si.executor import (
    approve_step,
    dependencies_satisfied,
    execute_step,
    next_runnable_step,
    reject_step,
)
from drw.si.interpreter import interpret
from drw.si.planner import plan_analysis, preview_of
from drw.si.provider import SIProvider, provider_from_env, provider_status
from drw.si.service import (
    approve_and_execute,
    ask,
    get_state,
    list_actions,
    preview_step,
    reject_plan_step,
)
from drw.si.store import DRAFT_INVESTIGATION_ID, SIStore, default_si_store

__all__ = [
    "DRAFT_INVESTIGATION_ID",
    "SIAction",
    "SIActionContext",
    "SIActionError",
    "SIActionOutcome",
    "SIActionRegistry",
    "SIProvider",
    "SIStore",
    "approve_and_execute",
    "approve_step",
    "ask",
    "build_action_context",
    "build_context",
    "default_registry",
    "default_si_store",
    "dependencies_satisfied",
    "execute_step",
    "get_state",
    "interpret",
    "list_actions",
    "next_runnable_step",
    "plan_analysis",
    "preview_of",
    "preview_step",
    "provider_from_env",
    "provider_status",
    "reject_plan_step",
    "reject_step",
]
