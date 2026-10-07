"""Deterministic interpretation of SI execution results.

Interpretation is template-driven, not model-generated: the same structured result
always yields the same reading. Every interpretation separates what the result
**establishes** from what it **does not**, so a good fit is never read as truth.
"""

from __future__ import annotations

from drw.schema.si import SIExecutionResult, SIInterpretation

__all__ = ["interpret", "next_step_suggestions"]

_READ = (
    "This was a read-only inspection. It reports what exists in the investigation; "
    "it is not a scientific result.",
    [],  # establishes
    ["Any scientific or causal claim: nothing was computed."],
    [],
    [],  # next_steps
)

_TEMPLATES: dict[str, tuple[str, list[str], list[str], list[str], list[str]]] = {
    "create_experiment": (
        "The model ran for the configured baseline and interventions. These are "
        "simulation outputs - consequences of the model and its assumptions - not "
        "evidence about the world.",
        [
            "The model produced the reported outputs for the configured inputs.",
            "A reproducible experiment, result and evidence package were recorded.",
        ],
        [
            "That the model is correct, or matches reality.",
            "Any parameter estimate, causal claim or scientific conclusion.",
        ],
        [
            "Every output is conditioned on the model, its assumptions and the chosen inputs."
        ],
        [
            "Evaluate the model against empirical observations under an explicit mapping.",
            "Calibrate parameters if observations are available.",
        ],
    ),
    "evaluate": (
        "The model output was compared with empirical observations under the configured "
        "mapping and metrics, over the aligned usable points reported.",
        [
            "The model's agreement with these observations, to the reported degree, "
            "under this mapping and these metrics.",
        ],
        [
            "That the model is true or correct.",
            "That it will generalise to other conditions or datasets.",
            "Any causal relationship.",
        ],
        [
            "Agreement depends on the mapping, the metric and the quality of the observations.",
            "Excluded observations and residuals should be inspected, not just the headline metric.",
        ],
        [
            "Calibrate parameters against the calibration data.",
            "Validate on independent observations not used for fitting.",
        ],
    ),
    "calibrate": (
        "Calibration searched bounded parameter values to minimise the configured "
        "objective against the calibration observations. Convergence is not certainty.",
        [
            "A point estimate of the free parameters that minimises the objective on "
            "the calibration data.",
        ],
        [
            "Parameter uncertainty or a confidence region.",
            "That the model is valid, or that the parameters are identifiable.",
            "That the estimate generalises to other data.",
        ],
        [
            "The objective depends on the mapping, metric and observation quality.",
            "Invalid evaluations are excluded, not fabricated.",
        ],
        [
            "Validate the frozen calibration against independent observations.",
            "Run an identifiability study before trusting individual parameters.",
        ],
    ),
    "validate": (
        "Validation tested the frozen calibrated model against independent observations "
        "- a genuinely out-of-sample test. Agreement, independence and any acceptance "
        "criterion are separate axes.",
        [
            "The frozen model's agreement with independent observations, to the reported degree.",
            "Whether the claimed independence dimensions were mechanically verified.",
        ],
        [
            "That the model is true or correct.",
            "Causality.",
            "That agreement implies prediction outside the tested conditions.",
        ],
        [
            "Validation cannot refit; a poor result is not fixed by re-calibrating on the same data.",
            "An acceptance threshold is a user decision rule, not scientific truth.",
        ],
        [
            "Sensitivity, identifiability or uncertainty analysis.",
            "Design an experiment to discriminate competing hypotheses.",
        ],
    ),
    "sensitivity": (
        "This is a variance-based sensitivity study. It is descriptive: it apportions "
        "output variance to independent inputs and is not a causal analysis.",
        [
            "How output variance is apportioned to the modelled inputs under independent "
            "input assumptions.",
        ],
        [
            "Causality.",
            "That the model is valid.",
            "Generalisation to other conditions.",
        ],
        ["Indices assume independent inputs and are finite-sample estimates."],
        [
            "Identifiability, if the concern is which parameters the data can distinguish.",
            "Uncertainty analysis for the sampled design.",
        ],
    ),
    "identifiability": (
        "This is a local, structural identifiability study at the baseline and targets. "
        "It is not global identifiability and not practical identifiability from noisy data.",
        [
            "Whether the selected parameters are locally distinguishable at this baseline."
        ],
        [
            "Global identifiability.",
            "Practical identifiability from noisy, finite observations.",
            "That the model is valid.",
        ],
        [
            "A well-conditioned result is local; it does not guarantee identifiability elsewhere."
        ],
        [
            "Validation on independent observations.",
            "Calibration, to obtain a point estimate.",
        ],
    ),
    "create_model_spec": (
        "A structured model specification was validated and stored as an inspectable "
        "artifact. It has not been compiled into an executable model and has not been validated.",
        ["That an inspectable, content-addressed model specification now exists."],
        [
            "That the model is executable: run create_model to compile it.",
            "That the model is scientifically valid.",
        ],
        ["The specification's relationships are symbolic and are not executed."],
        ["Review the specification, then compile it with create_model."],
    ),
    "create_model": (
        "The model specification was compiled into an executable, content-addressed model "
        "artifact. Its rate equations are a bounded arithmetic form, validated by the "
        "compiler - never generated code.",
        [
            "That an executable model derived from the specification now exists and is "
            "traceable to it by content hash.",
        ],
        [
            "That the model is scientifically valid or that it matches reality.",
            "That its assumptions are true.",
        ],
        [
            "The model's behaviour follows entirely from its equations, parameters and "
            "assumptions."
        ],
        [
            "Simulate the model to inspect its behaviour under specified conditions.",
            "Compare it with empirical observations via evaluation, calibration and validation.",
        ],
    ),
    "simulate": (
        "The model was executed through the Runner and its outputs were stored as an "
        "explicitly SYNTHETIC dataset. These values are consequences of the model and its "
        "assumptions - they are not evidence about the world.",
        [
            "What the model produces under the specified parameters, scenario and window.",
            "A reproducible, provenance-carrying synthetic dataset for testing, experiment "
            "design or parameter-recovery studies.",
        ],
        [
            "That the model describes reality.",
            "Any empirical or causal claim: the data was generated by the model itself.",
        ],
        [
            "Synthetic data is refused by empirical evaluation, calibration and validation."
        ],
        [
            "Compare the model against real observations with evaluation and calibration.",
            "Test whether calibration recovers known parameters (parameter recovery).",
        ],
    ),
    "propose_model": _READ,
    "validate_model_spec": _READ,
    "propose_simulation": _READ,
}

_DEFAULT = (
    "This step completed. Review the structured result for what it produced.",
    [],
    ["A scientific conclusion: interpretation depends on the specific analysis."],
    [],
    [],
)


def _reading(action_id: str) -> tuple[str, list[str], list[str], list[str], list[str]]:
    if (
        action_id.startswith(("inspect_", "list_", "propose_"))
        and action_id not in _TEMPLATES
    ):
        return _READ
    return _TEMPLATES.get(action_id, _DEFAULT)


def _failure_text(result: SIExecutionResult) -> str:
    if result.status == "unsupported":
        return f"Not performed: {result.summary} Nothing was run and no result was produced."
    code = result.error_code or "error"
    detail = result.error_message or result.summary
    return f"The step failed ({code}): {detail} No result was produced."


def interpret(
    result: SIExecutionResult, *, interpretation_id: str, at: str
) -> SIInterpretation:
    """Build a deterministic interpretation of an execution result."""
    if result.status in ("failed", "unsupported"):
        text = _failure_text(result)
        return SIInterpretation(
            interpretation_id=interpretation_id,
            step_id=result.step_id,
            action_id=result.action_id,
            text=text,
            establishes=[],
            does_not_establish=[
                "Anything: the step did not produce a usable result.",
                "That the underlying capability is unavailable if the failure was an input error.",
            ],
            limitations=[
                "Do not treat a failed or unsupported step as evidence for or against a model."
            ],
            next_steps=next_step_suggestions(result.action_id),
            artifacts=dict(result.artifacts),
            at=at,
        )

    text, establishes, does_not, limitations, next_steps = _reading(result.action_id)
    return SIInterpretation(
        interpretation_id=interpretation_id,
        step_id=result.step_id,
        action_id=result.action_id,
        text=text,
        establishes=list(establishes),
        does_not_establish=list(does_not),
        limitations=list(limitations),
        next_steps=list(next_steps),
        artifacts=dict(result.artifacts),
        at=at,
    )


def next_step_suggestions(action_id: str) -> list[str]:
    """The scientifically justified next actions after an action."""
    _, _, _, _, next_steps = _reading(action_id)
    return list(next_steps)
