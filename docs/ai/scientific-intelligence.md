# Scientific Intelligence (SI)

**Status: implemented as a controlled orchestration layer**
(Milestone 13). See [ADR-0028](../architecture/ADR-0028-scientific-intelligence.md).

SI is the AI interface of an investigation. It turns a research question into a
structured, inspectable plan and drives DRW's existing capabilities through a
controlled action registry. It is **not** a generic chatbot: SI proposes and
interprets, DRW computes and records, and nothing runs without explicit approval.

## The loop

```
Question
  -> SI understands it (and says so)
  -> SI inspects the current scientific state
  -> SI identifies what is missing / what it cannot do
  -> SI proposes an explicit, structured plan (steps with action + inputs)
  -> the user reviews a step and its exact inputs
  -> the user approves it (only for steps that create/modify an artifact)
  -> DRW executes a real supported operation
  -> the result is persisted and SI interprets it
       (what it establishes / what it does not)
  -> SI proposes the next scientifically justified step
```

The conversation is an interface to **durable state** (`<workspace>/si/<id>.json`),
not the source of truth. SI never executes shell or Python, never invents results,
and never blurs synthetic data with empirical observations.

## Guardrails

* **Read-only actions** (inspect/list) run without approval.
* **Actions that create or modify an artifact** (run an experiment, calibrate,
  validate, evaluate, sensitivity, identifiability, store a specification, **compile
  a model**, **simulate**) require an explicit approval and show their exact inputs
  first.
* An action the engine cannot perform is listed but **fails closed** with a
  structured explanation rather than pretending.
* **Synthetic data is never evidence.** Evaluation, calibration and validation
  refuse a dataset whose provenance is synthetic.
* **A fit is not truth.** Every interpretation lists what the result does *not*
  establish.

## Interfaces

Bridge ops: `si_state`, `si_ask`, `si_preview`, `si_execute`, `si_reject`,
`si_actions`, `si_provider`.

CLI:

```bash
python -m drw si actions
python -m drw si state <investigation_id>
python -m drw si ask <investigation_id> "Design an experiment to see how alpha changes the prey peak." --model predator-prey
python -m drw si preview <investigation_id> step-4 --model predator-prey
python -m drw si execute <investigation_id> step-4 --model predator-prey --approve
```

Web: the **SI** page of an investigation (or the project overview). It shows the
conversation, the current plan, each step's access class (read-only vs. requires
approval), a preview of exactly what a step will run, the execution status and the
interpretation.

## Providers

The deterministic **rule-based planner** is always available and is the default;
it reuses the existing experiment planner to build a real `ExperimentSpec` when a
design is requested. An optional LLM provider is configured **server-side** with
the same variables as the AI planner:

```bash
DRW_LLM_PROVIDER=openai DRW_LLM_API_KEY=... DRW_LLM_MODEL=gpt-4o-mini
```

Every field the provider returns is untrusted: unknown actions, unsupported
actions and invalid inputs are dropped with a recorded caveat, never executed.
With no provider configured nothing leaves the machine.

## Model generation and simulation (implemented, bounded)

* A model is a **structured specification**, not generated code:
  `ModelSpecification` (variables, parameters, units, symbolic relationships,
  assumptions, initial/boundary conditions, domain, provenance, content identity).
  It is validated and can be stored durably (`create_model_spec`), then compiled
  into an executable, content-addressed model artifact by **`create_model`**
  (`drw.model_compiler` + `drw.model_store`). The compiled model is registered,
  readable by `describe_model`, and executable by the existing `Runner`.
* A **simulation** is reproducible and synthetic by construction: **`simulate`**
  runs a `SimulationSpec` through the existing `Runner` and stores its outputs as an
  explicitly synthetic dataset (`drw.simulation` + `drw.simulation_store`).
  `synthetic_provenance` marks the dataset and `assert_empirical` refuses to use it
  as evidence in evaluation, calibration or validation.

Both actions still require **explicit approval** and run through the same action
registry; the interpretation states that a simulation is a consequence of a model,
not evidence about the world.

### What the compiler supports (and what it refuses)

Supported: `kind = "ode"`, state variables only, **one rate equation per state
variable** (a relationship with `rate_of`), with expressions over the declared
states/parameters, `t`, the constants `pi`/`e`, `+ - * / **`, unary `+/-` and a
fixed list of math functions (`sin`, `cos`, `exp`, `sqrt`, …). No code, no imports,
no attribute access, no user calls.

Refused **closed** (with a structured reason, never approximated): other model
kinds, `derived` variables, non-rate relationships, missing/duplicate rate
equations, any expression outside the grammar, or an invalid execution window.

Simulation additionally requires the model to be resolvable, its hash to match, the
`SimulationSpec` window to match the model's own integration window (see
`drw.simulation.default_simulation_config`), every parameter/initial condition to be
present and in bounds, and every requested output to be time-series.

