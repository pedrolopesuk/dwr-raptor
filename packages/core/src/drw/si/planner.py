"""SI plan generation.

Given a natural-language question and the structured context, SI produces an
:class:`~drw.schema.si.SIAnalysis`: what it understood, what exists, what is
missing, and a structured plan of inspectable steps. The plan is never prose - each
step names a registered action with deterministic inputs.

Two backends, mirroring the rest of DRW:

* a **deterministic rule-based planner** (always available), which reasons over
  the context and reuses the existing experiment planner to build a real spec; and
* an **optional LLM provider** whose fields are individually validated against the
  action registry and the current state - unknown actions, unsupported actions and
  invalid inputs are dropped with a recorded caveat, never executed.
"""

from __future__ import annotations

from typing import Any

from drw.schema.serialization import to_plain
from drw.schema.si import (
    SIActionPreview,
    SIAnalysis,
    SIPlan,
    SIPlanStep,
    compute_plan_id,
)
from drw.si.actions import SIActionContext, SIActionRegistry, default_registry
from drw.si.context import build_context, context_summary_lines
from drw.si.provider import SIProvider, SIProviderError, provider_from_env

__all__ = ["plan_analysis"]

_DESIGN_HINTS = (
    "design",
    "experiment",
    "vary",
    "increase",
    "decrease",
    "sweep",
    "run",
    "test",
    "%",
)


def _step(
    index: int,
    purpose: str,
    action_id: str,
    inputs: dict[str, Any],
    *,
    expected_output: str = "",
    rationale: str = "",
    depends_on: tuple[str, ...] = (),
    requires_approval: bool = True,
) -> SIPlanStep:
    return SIPlanStep(
        step_id=f"step-{index}",
        purpose=purpose,
        action_id=action_id,
        inputs=inputs,
        expected_output=expected_output,
        scientific_rationale=rationale,
        depends_on=depends_on,
        approval="required" if requires_approval else "not_required",
        status="proposed",
    )


def _rule_based_steps(
    question: str,
    ctx: SIActionContext,
    context: dict[str, Any],
    *,
    missing: list[str],
    unsupported: list[str],
    open_questions: list[str],
) -> list[SIPlanStep]:
    lower = question.lower()
    experiments = context.get("experiments") or []
    datasets = context.get("datasets") or []
    calibrations = context.get("calibrations") or []
    real_datasets = [d for d in datasets if not d.get("synthetic")]
    latest_experiment = experiments[0]["experiment_id"] if experiments else None

    steps: list[SIPlanStep] = []
    index = 1
    steps.append(
        _step(
            index,
            "Inspect the durable state of this investigation.",
            "inspect_investigation",
            {},
            expected_output="objective, hypotheses, experiments, datasets, open questions",
            rationale="Establish what already exists before proposing new computation.",
            requires_approval=False,
        )
    )
    index += 1

    if ctx.model_id:
        steps.append(
            _step(
                index,
                f"Inspect the selected model {ctx.model_id}.",
                "inspect_model",
                {"model_id": ctx.model_id},
                expected_output="declared parameters, outputs and capabilities",
                rationale="Reason about capabilities that actually exist for this model.",
                requires_approval=False,
            )
        )
        index += 1

    wants_data = any(word in lower for word in ("data", "observ", "import", "dataset"))
    if wants_data or not datasets:
        steps.append(
            _step(
                index,
                "Inspect the available observation datasets.",
                "list_datasets",
                {},
                expected_output="datasets with source kind and a synthetic flag",
                rationale="Separate real observations from simulated data before anything else.",
                requires_approval=False,
            )
        )
        index += 1
        if not datasets:
            missing.append(
                "No observation dataset has been imported. Evaluation, calibration and "
                "validation all require empirical observations."
            )

    wants_design = any(word in lower for word in _DESIGN_HINTS)
    if wants_design and ctx.model_id:
        spec = _propose_spec(ctx.model_id, question, unsupported)
        if spec is not None:
            steps.append(
                _step(
                    index,
                    "Run an experiment that varies a parameter and compares outputs.",
                    "create_experiment",
                    {"spec": spec},
                    expected_output="a stored experiment with runs, comparisons and an evidence package",
                    rationale="A designed intervention is needed to observe the modelled response.",
                    depends_on=(f"step-{index - 1}",),
                )
            )
            index += 1

    wants_sensitivity = any(
        word in lower
        for word in ("sensitivity", "matters", "drive", "influence", "variance")
    )
    if wants_sensitivity:
        if latest_experiment:
            steps.append(
                _step(
                    index,
                    "Estimate global (Sobol) sensitivity of a scalar output.",
                    "sensitivity",
                    {"experiment_id": latest_experiment},
                    expected_output="first-/total-order indices with an inconclusive flag",
                    rationale="Quantifies how much each input contributes to output variance.",
                    depends_on=(f"step-{index - 1}",),
                )
            )
            index += 1
        else:
            missing.append(
                "A stored experiment is required before a sensitivity study can run."
            )

    wants_identifiability = any(
        word in lower for word in ("identif", "distinguish", "degenerate")
    )
    if wants_identifiability:
        if latest_experiment:
            steps.append(
                _step(
                    index,
                    "Test whether the selected parameters are locally distinguishable.",
                    "identifiability",
                    {"experiment_id": latest_experiment},
                    expected_output="a verdict with rank, condition number and directions",
                    rationale="Distinguishes 'cannot fit' from 'cannot tell these parameters apart'.",
                    depends_on=(f"step-{index - 1}",),
                )
            )
            index += 1
        else:
            missing.append(
                "A stored experiment is required before an identifiability study can run."
            )

    wants_calibration = any(
        word in lower
        for word in ("calibrat", "fit the", "fit my", "estimate the parameter")
    )
    if wants_calibration:
        if real_datasets:
            unsupported.append(
                "Calibration needs an explicit configuration: the free parameters with "
                "bounds and initials, an objective metric, an optimizer, a budget, and a "
                "dataset mapping. SI will not invent these; supply them and SI will "
                "propose the calibration step."
            )
        else:
            missing.append("Calibration requires an empirical dataset to fit against.")

    wants_validation = "validat" in lower
    if wants_validation:
        if not calibrations:
            missing.append(
                "Validation requires a persisted calibration to freeze first."
            )
        else:
            unsupported.append(
                "Validation needs an explicit configuration and one or more independent "
                "validation datasets with a mapping; SI will not fabricate them."
            )

    wants_model = any(
        phrase in lower
        for phrase in (
            "construct a model",
            "create a model",
            "build a model",
            "generate a model",
            "write a model",
            "define a model",
            "don't have a model",
            "dont have a model",
            "no model yet",
            "model from scratch",
        )
    )
    if wants_model:
        missing.append(
            "SI does not invent a model specification. Provide the variables, parameters, "
            "units and one rate equation per state variable (a relationship with 'rate_of'), "
            "or configure an LLM provider to propose a structured specification for review; "
            "create_model then compiles it (approval required)."
        )

    wants_simulation = any(
        word in lower
        for word in ("simulate", "simulation", "synthetic", "parameter recovery")
    )
    if wants_simulation:
        compiled = context.get("compiled_models") or []
        if compiled:
            unsupported.append(
                "Simulation needs a full SimulationSpec (parameter/initial-condition values, "
                "scenario, outputs and a window matching the model's); SI will not invent "
                "these. Supply them and SI will propose the simulate step. Compiled model(s) "
                "available: " + ", ".join(item["model_id"] for item in compiled) + "."
            )
        else:
            missing.append(
                "Simulation requires a model; create one first with create_model."
            )

    inspect_only = all(
        step.action_id.startswith("inspect_") or step.action_id == "list_datasets"
        for step in steps
    )
    if (not steps or inspect_only) and not open_questions:
        open_questions.append(
            "What quantity do you care about, and how should it change under a "
            "controlled intervention?"
        )

    return steps


def _propose_spec(
    model_id: str, question: str, unsupported: list[str]
) -> dict[str, Any] | None:
    from drw.models.registry import build_model
    from drw.planner import PlannerError, plan_experiment

    try:
        schema = build_model(model_id).describe()
    except KeyError:
        unsupported.append(f"Model {model_id!r} is not registered.")
        return None
    try:
        result = plan_experiment(model_id=model_id, question=question, schema=schema)
    except PlannerError as exc:
        unsupported.append(f"A configuration could not be proposed: {exc.message}")
        return None
    if result.spec is None:
        unsupported.append(
            "The existing planner could not build an experiment from this question."
        )
        return None
    return to_plain(result.spec)


def _merge_provider(
    ai: dict[str, Any],
    analysis: SIAnalysis,
    ctx: SIActionContext,
    registry: SIActionRegistry,
    caveats: list[str],
) -> bool:
    """Merge a provider's untrusted fields. Returns True when AI steps were used."""
    if ai.get("understanding") and isinstance(ai["understanding"], str):
        analysis.understanding = ai["understanding"].strip() or analysis.understanding

    for key, target in (
        ("state_summary", analysis.state_summary),
        ("known", analysis.known),
        ("missing_information", analysis.missing_information),
        ("unsupported_requests", analysis.unsupported_requests),
        ("caveats", analysis.caveats),
    ):
        value = ai.get(key)
        if isinstance(value, list):
            for item in value:
                if isinstance(item, str) and item.strip():
                    target.append(item.strip())

    ai_questions = ai.get("open_questions")
    if isinstance(ai_questions, list) and analysis.plan is not None:
        for item in ai_questions:
            if (
                isinstance(item, str)
                and item.strip()
                and item.strip() not in analysis.plan.open_questions
            ):
                analysis.plan.open_questions.append(item.strip())

    raw_steps = ai.get("steps")
    if not isinstance(raw_steps, list) or not raw_steps:
        caveats.append(
            "The AI provider proposed no steps; the rule-based plan is used."
        )
        return False

    converted: list[SIPlanStep] = []
    raw_for_converted: list[dict[str, Any]] = []
    for position, candidate in enumerate(raw_steps, start=1):
        if not isinstance(candidate, dict):
            caveats.append("Ignored a malformed AI step (not an object).")
            continue
        action_id = candidate.get("action_id")
        if not isinstance(action_id, str) or not registry.has(action_id):
            caveats.append(f"Ignored an AI step with unknown action {action_id!r}.")
            continue
        action = registry.get(action_id)
        if not action.supported:
            caveats.append(f"Ignored an AI step for unsupported action {action_id!r}.")
            continue
        inputs = candidate.get("inputs")
        inputs = inputs if isinstance(inputs, dict) else {}
        preview = action.preview(inputs, ctx)
        errors = [d for d in preview.input_diagnostics if d.level == "error"]
        if errors:
            caveats.append(
                f"Ignored AI step {action_id!r}: "
                + "; ".join(d.message for d in errors if d.message)
            )
            continue
        converted.append(
            SIPlanStep(
                step_id=f"step-{position}",
                purpose=_as_str(candidate.get("purpose")) or action.name,
                action_id=action_id,
                inputs=preview.inputs,
                expected_output=_as_str(candidate.get("expected_output")),
                scientific_rationale=_as_str(candidate.get("scientific_rationale")),
                depends_on=(),
                approval="not_required" if action.read_only else "required",
                status="proposed",
            )
        )
        raw_for_converted.append(candidate)

    if not converted:
        caveats.append(
            "No valid AI steps survived validation; the rule-based plan is used."
        )
        return False

    # Keep only dependencies that point at generated steps.
    known_ids = {step.step_id for step in converted}
    for step, candidate in zip(converted, raw_for_converted, strict=True):
        raw_deps = candidate.get("depends_on")
        if isinstance(raw_deps, list):
            step.depends_on = tuple(
                dep for dep in raw_deps if isinstance(dep, str) and dep in known_ids
            )

    if analysis.plan is not None:
        analysis.plan.steps = converted
        analysis.plan.used_ai = True
        analysis.plan.provider = "llm"
    return True


def _as_str(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def plan_analysis(
    question: str,
    ctx: SIActionContext,
    *,
    provider: SIProvider | None = None,
    registry: SIActionRegistry | None = None,
    context: dict[str, Any] | None = None,
) -> SIAnalysis:
    """Produce SI's structured analysis of ``question`` for the current state."""
    active_registry = registry or default_registry()
    active_context = (
        context
        if context is not None
        else build_context(ctx, question=question, registry=active_registry)
    )

    missing: list[str] = []
    unsupported: list[str] = []
    open_questions: list[str] = []
    steps = _rule_based_steps(
        question,
        ctx,
        active_context,
        missing=missing,
        unsupported=unsupported,
        open_questions=open_questions,
    )

    objective = question.strip() or (ctx.state.objective if ctx.state else "")
    plan = SIPlan(
        plan_id=compute_plan_id(objective, steps),
        objective=objective,
        steps=steps,
        rationale=_rule_based_rationale(steps),
        open_questions=list(open_questions),
    )

    analysis = SIAnalysis(
        question=question,
        understanding=_understanding(question, ctx),
        state_summary=context_summary_lines(active_context),
        known=_known(active_context),
        missing_information=missing,
        unsupported_requests=unsupported,
        caveats=[
            "SI proposes and interprets; DRW computes and records. Nothing runs without approval.",
        ],
        plan=plan,
        provider="rule-based",
        used_ai=False,
    )

    active_provider = provider if provider is not None else provider_from_env()
    if active_provider is not None:
        try:
            ai = active_provider.respond(question=question, context=active_context)
        except (SIProviderError, KeyError, ValueError, OSError):
            analysis.caveats.append(
                "The AI provider was unavailable; the deterministic rule-based plan is used."
            )
        else:
            if not isinstance(ai, dict) or not ai:
                analysis.caveats.append(
                    "The AI provider returned no usable plan; the rule-based plan is used."
                )
            else:
                analysis.provider = active_provider.name
                used_ai = _merge_provider(
                    ai, analysis, ctx, active_registry, analysis.caveats
                )
                analysis.used_ai = used_ai
                if used_ai and analysis.plan is not None:
                    analysis.plan.plan_id = compute_plan_id(
                        analysis.plan.objective, analysis.plan.steps
                    )
                    analysis.plan.rationale = (
                        _as_str(ai.get("rationale")) or analysis.plan.rationale
                    )

    return analysis


def _understanding(question: str, ctx: SIActionContext) -> str:
    model = f" the model {ctx.model_id}" if ctx.model_id else " the selected model"
    return (
        f"You are asking: {question.strip() or '(no question text)'}. "
        f"SI interprets this against{model}, the current investigation state and the "
        "available observations, then proposes an inspectable plan."
    )


def _known(context: dict[str, Any]) -> list[str]:
    known: list[str] = []
    model = context.get("model")
    if model:
        known.append(f"Model {model['model_id']} v{model['version']} is selected.")
    datasets = context.get("datasets") or []
    real = [d for d in datasets if not d.get("synthetic")]
    if real:
        known.append(f"{len(real)} empirical dataset(s) are available.")
    if context.get("experiments"):
        known.append(f"{len(context['experiments'])} experiment(s) are stored.")
    if context.get("calibrations"):
        known.append(f"{len(context['calibrations'])} calibration(s) are stored.")
    if context.get("validations"):
        known.append(f"{len(context['validations'])} validation(s) are stored.")
    return known


def _rule_based_rationale(steps: list[SIPlanStep]) -> str:
    if not steps:
        return "No supported step could be proposed from the current state."
    names = ", ".join(step.action_id for step in steps)
    return f"Proposed {len(steps)} step(s) from the current state, in order: {names}."


def preview_of(
    step: SIPlanStep, ctx: SIActionContext, registry: SIActionRegistry | None = None
) -> SIActionPreview:
    """Preview the action a step would run (used to show the user exactly what runs)."""
    active = registry or default_registry()
    return active.preview(step.action_id, step.inputs, ctx)
