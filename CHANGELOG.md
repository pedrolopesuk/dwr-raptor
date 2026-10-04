# Changelog

All notable changes to this project are documented in this file. The project
follows a milestone-oriented changelog; entries record *scientific* behaviour
changes explicitly (see the spec's AI coding loop, section 12.4).

## [Milestone 6] - Scientific trust: evidence verification

### Added

- **First-party evidence verification.** `drw.execution.evidence.verify_evidence`
  checks an evidence package against its manifest read-only: every declared
  artifact must exist, stay inside the manifest's directory, and match its recorded
  size and SHA-256. It reports `ok`, `missing`, `size_mismatch`, `hash_mismatch`,
  `invalid_path`, `invalid_entry` and `unreadable` per artifact. Undeclared files
  are listed in `extra_files` and are explicitly **not** verified (they do not, on
  their own, fail verification).
- **`drw verify` CLI subcommand** (exit 0 = verified, 1 = failed verification,
  2 = unusable manifest/path).
- **`verify_evidence` bridge op** (read-only) which resolves the manifest from the
  stored experiment (`experiment_id`) so arbitrary filesystem paths are never
  reachable from the web layer.

### Changed

- **Documentation corrected to match ADR-0006 and the code:** the relative-change
  rule in `drw/numerics/delta.py` and the acceptance matrix now reads
  `r = Δy/y_ref` where `|y_ref| > ε`, else `NaN` (flagged). No numerical change.

### Notes

- **Consistency, not cryptographic authenticity.** The manifest is not self-hashed
  or signed, so a successful verification does not protect against a party who can
  rewrite both the artifacts and the manifest. Nothing is written by verification.
- No change to experiment identity, deterministic ids, overwrite behaviour,
  schemas, model hashes, numerical methodology or the evidence format.
- Investigation and rationale: `docs/reports/milestone-6-investigation.md`.

## [Milestone 5] - Model-agnostic experiment workflow

### Added

- **Model picker (ADR-0012).** The researcher workspace now lists every
  registered model (`oscillator`, `predator-prey`, `lorenz`) and can start a new
  experiment from any of them. Creation reuses the existing
  `sample_experiment(model_id)` / `drw.demo.build_demo_experiment` path; **no new
  bridge operation or numerical code** was added.
- **Technical eligibility, explained.** `modelViability` derives whether a model
  can seed an experiment from its declared `capabilities` (a numeric parameter to
  vary and a comparable output). Ineligible models are disabled in the picker
  with the reason; the UI states that eligibility is technical, **not**
  scientific validity.
- **Authoritative metadata in the model panel.** `ModelPanel` now shows each
  parameter's `description` (and output descriptions) straight from the model
  schema, plus a "what this model supports" block (factorable parameters,
  outputs, sensitivity, limitations).
- **Demonstration labelling.** A newly seeded experiment is labelled in the UI as
  a **demonstration** (+10% on the first input), explicitly not a scientifically
  justified experiment.
- **Observation vs. conclusion.** The Results overview states that outputs are
  simulated results for the configured model/baseline/intervention - an observed
  simulation result, not an established scientific conclusion.
- Tests: web `Workspace.m5.test.tsx` (model selection, metadata, validation
  failure, result rendering, eligibility) and `modelViability` unit tests;
  Python `test_api_bridge.py` now asserts that **every** registered model seeds,
  validates and executes through the bridge.

### Changed

- `Workspace` loads a model's `capabilities` alongside the model list; the sample
  action is preserved as the predator-prey regression example.

### Notes

- **No persistence-semantics change.** Deterministic `exp-<hash12>` ids and
  identical-spec overwrite are documented, not altered. No Python core, bridge,
  schema or storage changes.
- A baseline timing flake in the Python-backed `Workspace.e2e.test.tsx` was
  recorded and fixed by allowing real subprocess startup (see
  `docs/reports/milestone-5-baseline.md`).
- Isolation remains a process boundary, **not** a sandbox (ADR-0005).

## [Milestone 4.5 - Carbon UI] - Design-system adoption

### Changed

- **UI migrated to the IBM Carbon Design System** (`@carbon/react` 1.117.0,
  `@carbon/styles`, `@carbon/icons-react`, Dart Sass). The custom
  `globals.css` design system was removed. Every primary screen (shell, sidebar,
  model/experiment editor, validation, review, planner, results tabs, tables,
  charts legend) now uses Carbon components and tokens.
- Application shell: Carbon `Header` + skip link; theme toggle between Carbon
  `g10` (light, default) and `g100` (dark), persisted in `localStorage`.
- Layout helpers use Carbon spacing/type tokens and CSS custom properties;
  no hard-coded hex values were introduced.

### Added

- **Automated accessibility suite** (`e2e/accessibility.spec.ts`): axe-core
  (light + dark) with a zero serious/critical gate, plus a keyboard test for the
  skip link, sample action, project select, baseline field and validation.
- Documentation: `docs/architecture/carbon-design-system.md`,
  `docs/testing/acceptance-matrix.md`,
  `docs/reports/milestone-4.5-baseline.md`,
  `docs/reports/milestone-4.5-final-acceptance.md`.

### Fixed

- axe `scrollable-region-focusable` (serious) caused by Carbon `CodeSnippet`'s
  non-focusable scrollable `<pre>`; the spec and evidence previews are now
  focusable `<pre>` elements (documented exception).
- jsdom lacked `ResizeObserver`/`matchMedia`, which Carbon components require;
  inert stubs added to the Vitest setup.
- The workspace context line now shows the active project name instead of
  "no project" before projects finish loading.

### Notes

- **No Python, bridge, schema or storage changes.** Scientific behaviour is
  unchanged; all 160 Python tests still pass.
- pnpm build scripts for the Carbon/IBM packages are explicitly declined
  (`allowBuilds: false`) because they ship prebuilt CSS/fonts.

## [Milestone 4.5] - Local launch and interactive acceptance

### Added

- **Windows launcher** `scripts/start-local.ps1` (root script `pnpm start:local`):
  checks Node/pnpm/Python, verifies the scientific core is importable, finds a free
  port, wires `DRW_PYTHON`/`DRW_WORKSPACE`, prints the URL, and never kills other
  processes or deletes data.
- **Live acceptance harness**: `apps/web/playwright.local.config.ts` and
  `apps/web/e2e/local-acceptance.spec.ts` drive the already-running app in Chromium
  and assert no console errors / 5xx responses.
- **Local run guide** `docs/local-run.md`; acceptance report
  `docs/reports/milestone-4.5-local-acceptance.md`.

No functional defects were found during the walkthrough; no scientific, contract
or UI behaviour changed.

## [Milestone 4] - Browser trust, projects, and AI experiment planning

### Added

- **Browser end-to-end tests (Playwright).** `apps/web/e2e/workspace.spec.ts` runs
  the production build in Chromium: open, load the sample, configure baseline and
  intervention, reject an invalid configuration, run, inspect plots and metrics,
  reload a saved experiment, export evidence, and exercise the timeout path.
  `pnpm --filter @drw/web e2e` builds and runs it.
- **Measured execution progress (ADR-0009).** A local job journal
  (`drw.jobs`, `<workspace>/jobs/<id>.jsonl`) records `started`,
  `run_completed` and `finished` events; the client supplies `job-<16 hex>`, polls
  the new `job_status` op, and the UI shows "k of n runs completed". No invented
  percentages. Cancellation semantics are unchanged (abort kills the child).
- **Minimal projects (ADR-0010).** `drw.store` gains `projects/<id>.json`,
  `create_project`, `list_projects`, and `project_id` on experiment metadata with
  a `project_id` filter for listings. Legacy experiments without a `project_id`
  are read as `default` and never rewritten. New ops `list_projects`,
  `create_project`; UI project selector and creation.
- **Model capabilities.** `drw.capabilities.model_capabilities` derives factorable
  / fixed / state / categorical parameters, time-series and scalar outputs,
  sampling and analysis methods, sensitivity availability, isolation and honest
  limitations. Exposed via `capabilities` and included in `describe_model`.
- **AI experiment planner (ADR-0011).** `drw.planner` proposes an `ExperimentSpec`
  from a question. Deterministic rule-based planner by default; optional
  server-side LLM provider (off unless configured). Proposals are validated by the
  authoritative Python validator, are never auto-executed, and require explicit
  approval. New ops `plan_experiment`, `planner_status`; UI planner panel with
  user input / AI suggestion / assumptions / open questions / validation and a
  human-readable preview.
- **Execution timeout control** in the review step, written into
  `execution.timeout_s`.

### Notes

- No new runtime dependencies: the bridge, journal, projects and planner use the
  standard library and existing packages. Playwright is a devDependency.
- The LLM HTTP client is not automatically tested without a key; the rule-based
  planner and the untrusted-field filtering are covered by tests with a fake
  provider.
- Isolation remains a process boundary (ADR-0005), not a sandbox.

## [Milestone 3] - Researcher-facing workspace

### Added

- **JSON bridge (`drw.api`, ADR-0008).** One-shot `python -m drw.api` boundary
  with ops `list_models`, `describe_model`, `sample_experiment`, `validate`,
  `run`, `list_experiments`, `get_experiment`, `evidence`, `export_evidence`,
  `sensitivity`, `environment`. Reuses the existing contracts and engine; no new
  Python dependency.
- **Local experiment store (`drw.store`).** Filesystem store per experiment
  (`spec.json`, `results.json`, `meta.json`, `evidence/`) with id validation and
  path-containment checks; reopening returns the stored spec unchanged.
- **Reusable OAT sensitivity (`drw.sensitivity`).** Extracted from the demo so the
  CLI, the bridge and the UI share one implementation.
- **Web workspace (`apps/web`).** Next.js App Router UI: model panel, baseline vs
  intervention editor, validate, review-before-run, run with cancel, and results
  organized into Overview / Plots / Metrics / Sensitivity / Reproducibility, with
  saved-experiment list and reopen. Route handlers call the bridge; TypeScript
  contains no scientific computation.
- **Web tests.** Pure helper tests, handler/bridge integration tests (node), UI
  state tests (validation, failure, cancellation, timeout) and a real end-to-end
  test that renders the UI and executes the Python core, including evidence export
  and reopen.

### Notes

- Isolation remains a process boundary (ADR-0005), not a security sandbox; the UI
  states this explicitly.
- A FastAPI `services/api` and browser-level (Playwright) tests are deferred; see
  ADR-0008.

## [Milestone 2] - Scientific trust and execution hardening

### Added

- **Isolated execution (ADR-0005).** `ExecutionSpec.isolation` (`subprocess`
  default). `drw.execution.worker` runs one model per process;
  `SubprocessExecutor` enforces `timeout_s` as a hard wall-clock limit, kills the
  process tree, redirects output to files in a private temp dir, always cleans up,
  and records deterministic failures (`timeout`, `cancelled`, `worker_crash`,
  `invalid_worker_response`, `worker_model_error`). `Runner.run(cancel_event=...)`
  supports cancellation. `RunRecord.isolation`/`timed_out` added.
- **Non-finite and missing-data handling (ADR-0006).** A run is `SUCCEEDED` only
  when every output value is finite; otherwise `FAILED` with `non_finite_output`.
  Comparisons mask non-finite pairs and report `valid_points` /
  `non_finite_points`. `ParameterSpec` now rejects non-finite nominal/bounds.
- **Analysis resilience.** An incompatible or missing output no longer aborts the
  experiment; it is reported (`comparison_failed`, `output_missing_for_comparison`)
  and the remaining outputs/variants still compare.
- **Sampling diagnostics.** `grid` + `n_samples` warns `n_samples_ignored`;
  stochastic sampling with a `steps` factor warns `factor_steps_ignored`.
- **Sensitivity interpretation.** The demo now reports normalized `elasticity`
  alongside `abs_delta`, flags bound-clamped perturbations, and states that OAT
  cannot detect interactions.
- **Independent numerical checks.** Error-vs-tolerance convergence against the
  analytic oscillator, RK45-vs-BDF agreement, and an analytic Lotka-Volterra
  equilibrium stationarity test.
- **Contract versioning (ADR-0007).** `analysis` accepted as an input alias for
  `analyses`; `schema_version_mismatch` warning. Schema drift and TS parity tests.
- **Environment hash refinement.** `environment_hash` excludes the interpreter
  path so identical environments agree across machines.
- **Run lifecycle docs.** `docs/architecture/run-lifecycle.md`; `TERMINAL_STATES`
  and `is_terminal` exported; the runner enforces transitions.

### Changed (scientific behaviour)

- A non-finite solve is now a `FAILED` run returning no outputs (was `SUCCEEDED`).
- Comparison metrics over partially non-finite series are now computed over finite
  pairs and are finite; previously they propagated `NaN` silently.
- `environment_hash` values change (interpreter path excluded).

## [Unreleased]

### Added

- **Repository bootstrap (INFRA-001).** pnpm workspace, Python package layout,
  CI workflow, lint/test configuration, and the specification's directory
  skeleton.
- **Foundational schemas (SCHEMA-001/002).** `ModelSchema` (parameters, units,
  bounds, roles, differentiability) and `ExperimentSpec` (hypothesis, baseline,
  factors, sampling, constraints, analyses, execution, verification, reporting),
  with deterministic canonical JSON hashing for provenance.
- **Run state machine (RUN-001).** Immutable run records with an explicit
  lifecycle (`DRAFT -> VALIDATED -> QUEUED -> RUNNING -> SUCCEEDED | FAILED`,
  then `ANALYZED -> VERIFIED -> EXPORTED`); retries create linked attempts.
- **ODE adapter (SCI-001).** `scipy.integrate.solve_ivp` wrapper with
  `auto`/`explicit`/`stiff` solver selection; solver choice and tolerances are
  recorded on every run.
- **Sampling (SCI-002).** Deterministic grid, random, Latin hypercube and Sobol
  designs with seeds; Sobol power-of-two guidance is surfaced as a warning.
- **Delta analysis (SCI-003).** Absolute and relative deltas with
  denominator-safety flagging, plus MAE/RMSE/max-abs/area/peak-shift/correlation
  metrics and explicit time-series alignment.
- **Golden models (SCI-004).** Mass-spring-damper (analytic reference),
  Lotka-Volterra predator-prey (conserved quantity), and Lorenz (determinism and
  divergence).
- **Local execution (SCI-005).** Deterministic local runner, environment
  fingerprinting, and an evidence package (manifest + hashes + results + report).
