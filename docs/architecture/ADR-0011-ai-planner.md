# ADR-0011: The AI planner is a proposal-only, optional layer

**Status:** Accepted

## Context

Milestone 4 introduces AI-assisted experiment planning. The constraints are
strict: Python remains authoritative, the model must never execute anything or
bypass validation, no provider may be required, and keys must stay server-side.
The milestone explicitly says not to build a full autonomous research agent.

## Decision

A single planner module (`drw.planner`) turns a research question into an
`ExperimentSpec`. It has two backends:

1. **Rule-based (default, always available).** Parses the question for a
   parameter (word match against declared parameters) and a percentage/direction,
   builds a baseline from the declared nominals, and proposes a single-value grid
   intervention plus delta analysis. No key, no network, fully deterministic and
   tested.
2. **Optional LLM provider (off by default).** Configured server-side via
   `DRW_LLM_PROVIDER`, `DRW_LLM_API_KEY`/`OPENAI_API_KEY`, `DRW_LLM_MODEL`,
   `DRW_LLM_BASE_URL`. It returns JSON fields only and is treated as untrusted.

Every proposal is then run through the existing authoritative validator
(`validate_experiment`). The result carries the spec, assumptions, open questions,
validation diagnostics, provider, and whether AI was used.

### Safety properties (enforced in code)

* The planner **never executes** anything; the API op returns a proposal only.
* The proposal is an `ExperimentSpec` that must pass `validate_experiment`.
* AI fields are individually checked: a parameter not in the model's *factorable*
  set, a percentage out of range, or an undeclared output is **ignored** with an
  assumption recorded - never merged blindly.
* The model receives **data**, with a system prompt that says model metadata and
  user text are data, not instructions, and must return JSON only (prompt
  injection is mitigated, not eliminated - documented as a limitation).
* No shell, no arbitrary Python, no arbitrary model import: only registered model
  ids reach execution.
* The UI requires an explicit **Apply → Validate → Run** sequence. A proposal is
  never auto-executed. Approval is the existing Run action on a validated spec.
* Model names, tool outputs and user text never override system policy.

### Privacy and cost

* Keys are read from the server environment in the bridge process and are never
  returned to the client, logged, or placed in the browser bundle.
  `provider_status` reports only whether a provider is configured.
* When a provider *is* configured, the request sends the **question**, the
  **user-supplied context**, and the **model's declared metadata** (id, description,
  parameter names/units/bounds, capabilities) to that provider. Simulation inputs,
  outputs, results and evidence packages are **not** sent.
* Token usage and monetary cost are the provider's; the bridge does not meter them.
  Operators should treat questions/context as leaving the machine when a provider
  is configured. With no provider (the default), nothing leaves the machine.

## Consequences

* The product works fully with no AI and no network.
* The LLM path is implemented but **not covered by automated tests without a key**
  (a fake provider is tested extensively; the HTTP client is not). This is stated
  as a limitation rather than a guarantee.
* Global sensitivity, uncertainty quantification and autonomous iteration remain
  out of scope.
