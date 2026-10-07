"""Structured contracts for Scientific Intelligence (SI).

SI is the conversational orchestration layer over the deterministic DRW engine.
These models are the **structured state** that a conversation produces: an
objective, a plan made of inspectable steps, the action previews the user
approves, the execution records, and the interpretations. Conversation text is an
interface to this state, never the source of truth.

Nothing here executes anything or calls a model; SI proposes and interprets, DRW
computes and records. The action registry (:mod:`drw.si.actions`) is the only
place that binds an action id to a real capability.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from drw.schema.result import Diagnostic
from drw.schema.serialization import content_hash

__all__ = [
    "SI_SCHEMA_VERSION",
    "ActionCategory",
    "ApprovalState",
    "SIActionPreview",
    "SIActionRef",
    "SIAnalysis",
    "SIEffect",
    "SIExecutionResult",
    "SIInterpretation",
    "SIInvestigationState",
    "SIMessage",
    "SIPlan",
    "SIPlanStep",
    "SIStatus",
    "compute_plan_id",
]

SI_SCHEMA_VERSION = "1.0.0"

#: What an action does to the investigation.
ActionCategory = Literal["read", "scientific", "model", "simulation"]
#: The lifecycle of a plan step or an execution record.
SIStatus = Literal[
    "proposed",
    "approved",
    "rejected",
    "executed",
    "failed",
    "skipped",
    "unsupported",
]
#: Whether a step needs explicit approval before it can run.
ApprovalState = Literal["not_required", "required", "approved", "rejected"]
#: The externally visible effect of an action (used to make the approval obvious).
SIEffect = Literal[
    "none",
    "creates_experiment",
    "creates_calibration",
    "creates_validation",
    "creates_analysis",
    "creates_dataset",
    "creates_model_spec",
    "modifies_model",
]


class SIActionRef(BaseModel):
    """A registry entry's public metadata (no executor, safe to return to a client)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    action_id: str
    name: str
    description: str = ""
    category: ActionCategory
    read_only: bool
    requires_approval: bool
    supported: bool = True
    effects: SIEffect = "none"
    limitations: tuple[str, ...] = ()


class SIActionPreview(BaseModel):
    """Exactly what a step will do, shown to the user before approval.

    Read-only actions may be described and run without approval; every other
    action is ``requires_approval`` and lists its concrete inputs and effects.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    action_id: str
    name: str
    description: str
    read_only: bool
    requires_approval: bool
    supported: bool
    effects: SIEffect
    inputs: dict[str, Any] = Field(default_factory=dict)
    input_diagnostics: tuple[Diagnostic, ...] = ()
    summary: str = ""
    warnings: tuple[str, ...] = ()


class SIExecutionResult(BaseModel):
    """The structured outcome of running one plan step."""

    model_config = ConfigDict(extra="forbid")

    step_id: str
    action_id: str
    status: SIStatus
    ok: bool
    summary: str = ""
    result: dict[str, Any] = Field(default_factory=dict)
    #: Named artifact references produced by the action, e.g. {"experiment_id": "exp-..."}.
    artifacts: dict[str, str] = Field(default_factory=dict)
    diagnostics: tuple[Diagnostic, ...] = ()
    error_code: str | None = None
    error_message: str | None = None
    started_at: str | None = None
    finished_at: str | None = None


class SIPlanStep(BaseModel):
    """One inspectable step of an SI plan.

    A step is not prose: it names an action, carries deterministic inputs, states
    its purpose and scientific rationale, and tracks its own approval and
    execution status.
    """

    model_config = ConfigDict(extra="forbid")

    step_id: str
    purpose: str
    action_id: str
    inputs: dict[str, Any] = Field(default_factory=dict)
    expected_output: str = ""
    scientific_rationale: str = ""
    depends_on: tuple[str, ...] = ()
    approval: ApprovalState = "required"
    status: SIStatus = "proposed"
    execution: SIExecutionResult | None = None

    @property
    def requires_approval(self) -> bool:
        return self.approval == "required"

    @property
    def runnable(self) -> bool:
        return self.status in ("proposed", "approved") and self.approval in (
            "not_required",
            "approved",
        )


class SIPlan(BaseModel):
    """A structured investigation plan: the graph, not a linear wizard."""

    model_config = ConfigDict(extra="forbid")

    plan_id: str
    objective: str
    steps: list[SIPlanStep]
    rationale: str = ""
    assumptions: list[str] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)
    provider: str = "rule-based"
    used_ai: bool = False
    notes: str = ""

    def step(self, step_id: str) -> SIPlanStep:
        for candidate in self.steps:
            if candidate.step_id == step_id:
                return candidate
        raise KeyError(f"plan {self.plan_id!r} has no step {step_id!r}")

    def current_next_step(self) -> SIPlanStep | None:
        for candidate in self.steps:
            if candidate.status in ("proposed", "approved"):
                return candidate
        return None


class SIAnalysis(BaseModel):
    """SI's structured response to one question.

    Separates what SI understood, what it found in the current scientific state,
    what is missing, and the plan it proposes. ``unsupported_requests`` records
    analyses DRW cannot currently perform rather than pretending.
    """

    model_config = ConfigDict(extra="forbid")

    schema_version: str = SI_SCHEMA_VERSION
    question: str
    understanding: str = ""
    state_summary: list[str] = Field(default_factory=list)
    known: list[str] = Field(default_factory=list)
    missing_information: list[str] = Field(default_factory=list)
    unsupported_requests: list[str] = Field(default_factory=list)
    caveats: list[str] = Field(default_factory=list)
    plan: SIPlan | None = None
    provider: str = "rule-based"
    used_ai: bool = False
    diagnostics: tuple[Diagnostic, ...] = ()


class SIMessage(BaseModel):
    """One turn of the SI conversation. Durable state holds the transcript."""

    model_config = ConfigDict(extra="forbid")

    message_id: str
    role: Literal["user", "si"]
    text: str = ""
    analysis: SIAnalysis | None = None
    at: str


class SIInterpretation(BaseModel):
    """SI's plain-language interpretation of an execution result.

    Explicitly separates what the result does and does not establish, so a fit is
    never read as truth.
    """

    model_config = ConfigDict(extra="forbid")

    interpretation_id: str
    step_id: str
    action_id: str
    text: str
    establishes: list[str] = Field(default_factory=list)
    does_not_establish: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    next_steps: list[str] = Field(default_factory=list)
    artifacts: dict[str, str] = Field(default_factory=dict)
    at: str


class SIInvestigationState(BaseModel):
    """Durable scientific memory for one investigation.

    This - not the chat transcript - is the source of truth. It is built up
    incrementally as the user asks questions, approves plans and runs actions.
    """

    model_config = ConfigDict(extra="forbid")

    schema_version: str = SI_SCHEMA_VERSION
    investigation_id: str
    project_id: str | None = None
    objective: str = ""
    hypotheses: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    models: list[str] = Field(default_factory=list)
    datasets: list[str] = Field(default_factory=list)
    experiments: list[str] = Field(default_factory=list)
    calibrations: list[str] = Field(default_factory=list)
    validations: list[str] = Field(default_factory=list)
    simulations: list[str] = Field(default_factory=list)
    evidence: list[str] = Field(default_factory=list)
    unresolved_questions: list[str] = Field(default_factory=list)
    decisions: list[str] = Field(default_factory=list)
    messages: list[SIMessage] = Field(default_factory=list)
    plans: list[SIPlan] = Field(default_factory=list)
    executions: list[SIExecutionResult] = Field(default_factory=list)
    interpretations: list[SIInterpretation] = Field(default_factory=list)
    current_plan_id: str | None = None
    current_next_step: str | None = None
    created_at: str
    updated_at: str

    def plan(self, plan_id: str) -> SIPlan:
        for candidate in self.plans:
            if candidate.plan_id == plan_id:
                return candidate
        raise KeyError(
            f"investigation {self.investigation_id!r} has no plan {plan_id!r}"
        )

    def current_plan(self) -> SIPlan | None:
        if self.current_plan_id is None:
            return None
        try:
            return self.plan(self.current_plan_id)
        except KeyError:
            return None


def compute_plan_id(objective: str, steps: list[SIPlanStep]) -> str:
    """Deterministic plan identity from its objective and proposed actions.

    Statuses are excluded, so approving a step does not change the plan's id.
    """
    payload = {
        "objective": objective,
        "steps": [
            {
                "step_id": step.step_id,
                "action_id": step.action_id,
                "inputs": step.inputs,
                "purpose": step.purpose,
            }
            for step in steps
        ],
    }
    return "plan-" + content_hash(payload)[:12]
