# ADR-0028: Scientific Intelligence (SI) is a controlled orchestration layer

**Status:** Accepted

> **Update (M14):** the two capabilities this ADR deliberately staged - model
> compilation (`create_model`) and the simulate-to-dataset pipeline (`simulate`) -
> are now implemented as bounded, approval-gated actions. See
> [ADR-0029](./ADR-0029-controlled-model-compilation-and-simulation.md). Everything
> else in this record still holds.

## Context

DRW already implements a rigorous computational loop: models, experiments, the
isolated `Runner`, datasets (M11), evaluation (M12A), calibration (M12B) and
validation (M12C), plus local/global sensitivity and identifiability (M9/M10). The
next bottleneck is not another primitive but **intelligence**: turning a
natural-language research question into an inspectable, approved, reproducible
investigation.

The constraints are the same as the existing AI planner's (ADR-0011) but broader:
SI must orchestrate the whole loop, not just propose one `ExperimentSpec`. It must
never execute arbitrary code or shell, never bypass validation or approval, never
fabricate results, and must keep the distinction between synthetic and empirical
observations. It must also leave a clean path toward two capabilities DRW needs
next - **model generation** and **simulation** - without locking DRW into an
LLM-generated-code architecture.

## Decision

Introduce SI as a Python-first layer (`drw/si`, `drw/schema/si.py`) that the web
UI and CLI drive through the existing JSON bridge. SI is **structured state plus a
controlled action registry**, never a generic chatbot beside the engine.

1. **Structured state, not a transcript.** `SIInvestigationState` is the durable
   scientific memory (objective, hypotheses, referenced models/datasets/
   experiments/calibrations/validations, unresolved questions, decisions, messages,
   plans, executions, interpretations), stored append-only-ish at
   `<workspace>/si/<investigation_id>.json` (`drw/si/store.py`). The conversation is
   an interface to this state.

2. **A plan is a graph of inspectable steps.** `SIPlan`/`SIPlanStep` carry an
   action id, deterministic inputs, purpose, expected output, scientific rationale,
   dependencies, approval state and execution status. `SIAnalysis` records what SI
   understood, what exists, what is missing, what it cannot do, and the plan.

3. **A controlled action registry** (`drw/si/actions.py`). Every capability SI can
   invoke is a registered `SIAction` with a stable id, category, read-only flag,
   approval requirement, declared effect and an executor that delegates to an
   existing DRW capability. Read-only actions run without approval; every action
   that creates or modifies an artifact requires explicit approval
   (`drw/si/executor.py`). Actions the engine cannot perform (`create_model`,
   `simulate`) are registered as `supported=False` and fail closed with an
   explanation - SI never pretends.

4. **A deliberate context layer** (`drw/si/context.py`). SI reasons over compact
   structured summaries and references (project, investigation state, model
   capabilities, dataset source kinds, experiments/calibrations/validations), never
   a raw dump of results or simulation data.

5. **A provider abstraction with a deterministic fallback** (`drw/si/provider.py`,
   `drw/si/planner.py`). The rule-based planner reasons over the context and reuses
   the existing experiment planner to build a real spec; it needs no key and no
   network. An optional LLM provider (same server-side `DRW_LLM_*` environment as
   ADR-0011) returns **untrusted** fields; the planner validates every field
   against the registry and the current state - unknown actions, unsupported
   actions and invalid inputs are dropped with a recorded caveat, never executed.

6. **Interpretation is deterministic** (`drw/si/interpreter.py`). The same
   structured result always yields the same reading, and every interpretation
   separates what the result *establishes* from what it *does not*.

7. **Model generation is a structured specification, not code**
   (`drw/schema/model_spec.py`, `drw/model_spec_store.py`). A `ModelSpecification`
   is declarative and inspectable (variables, parameters, units, symbolic
   relationships, assumptions, initial/boundary conditions, domain, provenance,
   content identity). `specification_to_schema` projects it onto the engine's
   `ModelSchema` (the extension point for a future controlled compiler).
   Compilation to executable code is **staged**: `compilation_supported()` reports
   it honestly, and `create_model` fails closed.

8. **Simulation and synthetic data are first-class and clearly separated**
   (`drw/schema/simulation.py`). `SimulationSpec` is reproducible (source model +
   hash, parameters, scenario, initial/boundary conditions, config, outputs) and
   `SimulationResult` is synthetic by construction. The M11 `SourceKind` already
   includes `"synthetic"`; `synthetic_provenance` marks generated data and
   `assert_empirical` **fails closed** when synthetic data would be used as evidence
   for evaluation / calibration / validation. The generate-a-dataset pipeline is
   staged (`simulation_supported()`), and `simulate` fails closed meanwhile.

9. **Interfaces.** Bridge ops `si_state`, `si_ask`, `si_preview`, `si_execute`,
   `si_reject`, `si_actions`, `si_provider`; CLI `drw si actions|state|ask|preview|
   execute`; a web SI page that renders the conversation, the plan, action
   previews, approval controls, execution status and the interpretation. **Manual
   remains the direct control layer over the same underlying state.**

## Safety properties (enforced in code)

* SI never executes shell, Python or any code it generates; it only dispatches
  registered action ids through the registry.
* A step that creates or modifies an artifact cannot run without explicit approval
  (`approval_required`), and a step cannot run before its dependencies have.
* The LLM is optional; with no provider configured nothing leaves the machine, and
  every AI field is validated before use.
* Synthetic observations are never used as empirical evidence.
* Failed and unsupported steps are recorded as such; results are never fabricated.
* A good fit is never described as proof the model is true: interpretations always
  state what a result does not establish.

## Consequences

* A user can ask a question in an investigation and experience the full loop:
  understand -> inspect -> identify missing information -> propose an explicit plan
  -> review -> approve -> execute a real supported operation -> persist -> interpret
  -> propose the next step - with durable, structured investigation memory.
* The web SI page is now the primary AI interface; the older proposal-only planner
  (`drw.planner`, ADR-0011) remains as the spec builder the SI rule-based planner
  reuses.
* **Staged (declared but not executable)**: model compilation and the
  simulate-to-dataset pipeline. Both are registered actions that fail closed with
  an explanation, and both have schemas, identity and provenance ready for the next
  milestone.
* No existing scientific contract was changed: `ExperimentSpec`, `ModelSchema`,
  `Runner`, `RunRecord`, `EvidenceManifest`, the dataset/observation contracts, M12A
  evaluation, M12B calibration and M12C validation are unmodified. SI only calls
  them.

## References

* `docs/ai/scientific-intelligence.md` - operator/user guide.
* ADR-0011 - the AI planner (the spec builder SI reuses).
* ADR-0016/0017 - the observation model and dataset storage (`source_kind`).
* ADR-0019/0022/0027 - evaluation, calibration and validation boundaries.
