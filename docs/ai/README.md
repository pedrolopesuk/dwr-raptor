# AI experiment planner

**Status: implemented as a proposal-only, optional layer** (Milestone 4).
See [ADR-0011](../architecture/ADR-0011-ai-planner.md).

The planner turns a research question into a structured `ExperimentSpec`. It is
deliberately *not* an autonomous agent: it proposes, the deterministic engine
validates and executes, and the researcher approves.

## Workflow

1. `POST /api/plan` (bridge op `plan_experiment`) with `model_id` and `question`
   (+ optional `context`).
2. Python selects the model from the **registry**, reads its declared parameters,
   outputs and capabilities, and builds a proposal.
3. If the question is too short to act on, the response has `spec: null` plus
   `questions` - the UI asks the user instead of guessing.
4. The proposal is validated with `validate_experiment`. Failures come back as
   diagnostics so it can be corrected.
5. The UI shows user input, AI suggestion, assumptions, open questions, a
   human-readable baseline/intervention/output/sampling summary, and validation
   status.
6. **Applying** a proposal only fills the editor. Execution still requires
   Validate → Review → Run. The planner never executes.

## Backends

| Backend | When | Behaviour |
| --- | --- | --- |
| Rule-based | Always (default) | Deterministic; parses parameter/percentage from the question; no key, no network. |
| LLM provider | Only if configured | Returns JSON fields; every field re-checked; failures fall back to rule-based. |

Configure the LLM provider **server-side** (never in the browser):

```bash
DRW_LLM_PROVIDER=openai           # "none" (default) disables it
DRW_LLM_API_KEY=...               # or OPENAI_API_KEY
DRW_LLM_MODEL=gpt-4o-mini
DRW_LLM_BASE_URL=https://api.openai.com/v1
```

## Safety and privacy

* No shell, no arbitrary Python, no arbitrary model import; only registered model
  ids reach execution.
* AI fields are individually checked against the model's factorable parameters,
  outputs and capabilities; unknown or out-of-range fields are ignored and
  recorded as assumptions.
* Model metadata and user text are passed as **data**, with a system prompt
  stating so. Prompt injection is mitigated, not eliminated.
* The planner never fabricates results, uncertainty or citations.
* **Data transmission:** when a provider is configured, the question, the
  user-supplied context and the model's declared metadata are sent to that
  provider. Simulation data, results and evidence are not.
* **Cost:** token usage/cost is the provider's; DRW does not meter it.
* **Keys:** read from the server environment in the bridge process; never returned
  to the client, logged, or bundled. `provider_status` reports only whether a
  provider is configured.
* With no provider configured (the default) nothing leaves the machine.

## Limitations

* OAT/delta only; no global sensitivity or uncertainty quantification.
* The LLM HTTP client is implemented but **not automatically tested** without a
  key; the rule-based planner and the merge/filter logic are thoroughly tested
  with a fake provider.
