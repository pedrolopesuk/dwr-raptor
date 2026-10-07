# ADR-0029: Bounded model compilation and simulation

**Status:** Accepted

## Context

Milestone 13 introduced a structured, inspectable
:class:`~drw.schema.model_spec.ModelSpecification` and a
:class:`~drw.schema.simulation.SimulationSpec`, but deliberately **staged** both
executable paths: the SI actions ``create_model`` and ``simulate`` failed closed.
The engine, meanwhile, can already execute ODE models through
:class:`~drw.numerics.ode.OdeModel` and
:class:`~drw.execution.runner.Runner`, and the M11 observation/dataset stack can
store inspectable datasets.

The unsafe shortcut - an LLM writing and executing Python - remains rejected. The
question is how to make ``create_model`` and ``simulate`` **real** while staying
deterministic, inspectable, approval-controlled and provenance-preserving, and
without introducing a general compiler or a second model system.

## Decision

### A bounded ODE compiler (`drw.model_compiler`)

``compile_model_spec`` consumes only the structured specification and produces a
:class:`CompiledModel`: a projected :class:`~drw.schema.model.ModelSchema`, the
rate equations, the state/parameter order and the execution window, all
serializable. It never evaluates LLM-authored code: each expression is parsed with
the standard-library ``ast`` module and walked against a strict whitelist, then
frozen into a closure.

**Supported subset:** ``kind == "ode"``; state variables only; one rate equation
per state variable (a relationship with ``rate_of``); expressions over numeric
literals, the declared states/parameters, the independent variable ``t`` and the
constants ``pi``/``e``, using ``+ - * / **``, unary ``+/-`` and calls to a fixed
list of math functions (``sin``, ``cos``, ``exp``, ``sqrt``, …). No attribute
access, subscripts, comprehensions, lambdas, comparisons, imports or user calls.

**Unsupported constructs fail closed** with a stable code
(``unsupported_model_kind``, ``unsupported_variable_kind``,
``unsupported_relationship``, ``missing_rate_equation``,
``duplicate_rate_equation``, ``unsupported_expression``,
``invalid_execution_config``, …). Nothing is approximated.

### Content identity

``compile_hash`` depends on the source specification hash, the compiler id/version,
the state/parameter order, the rate expressions and the window, so a changed
specification (or compiler) yields a different identity. ``model_id =
"mdl-" + compile_hash[:12]``. :func:`compute_compile_hash` recomputes it, and the
store refuses a mismatch.

### A compiled-model store (`drw.model_store`)

Content-addressed, append-only and verifiable, mirroring the other DRW stores:
``<workspace>/models/<model_id>/{spec,schema,artifact,provenance,manifest}.json``.
The *artifact* holds validated expression **strings** (never code); closures are
rebuilt deterministically on load. The provenance records the compiler, the source
specification hash, the declared model name, the assumptions and the source
reference.

### Registry integration

:mod:`drw.models.registry` now merges built-in models with compiled ones:
``build_model``, ``model_schemas`` and ``list_models`` resolve a compiled model by
id from the store under ``DRW_WORKSPACE``; a built-in id always wins. The Runner's
``_resolve_isolation`` uses ``is_registered`` (rather than raw dict membership), so
a compiled model keeps subprocess isolation, and the isolated worker builds it from
the store. A compiled model therefore becomes first-class to experiments,
``describe_model`` and the whole engine.

### Simulation through the existing Runner (`drw.simulation`)

``simulate`` builds a **single deterministic run** (no factors, no comparisons)
from the ``SimulationSpec`` and executes it with the existing
:class:`~drw.execution.runner.Runner`. ``prepare_simulation`` validates everything
first (model resolvable, model hash matches, window matches the model's own
integration window, all parameters/initial conditions present and in bounds,
outputs are time-series) and fails closed otherwise; ``validate_simulation`` powers
the action preview without executing.

The run's time-series outputs are turned into an
:class:`~drw.schema.observation.ObservationSet` (a ``time`` coordinate and one
measurement per output) and a content-addressed dataset whose provenance is
``source_kind="synthetic"`` (via ``synthetic_provenance``), with the model id/hash,
parameter values, scenario, seed and simulation hash recorded in a
``PreprocessStep``. A :class:`~drw.schema.simulation.SimulationResult` is stored by
:class:`~drw.simulation_store.SimulationStore` (``simulations/<sim_id>``), keyed by
the specification hash so identical requests are idempotent.

### SI actions

``create_model`` and ``simulate`` are now **real** actions, still gated by explicit
approval and dependency ordering, with preview validators so a malformed provider
step cannot bypass validation. The interpretation layer states plainly that a
simulation is a consequence of a model, never evidence about the world.

### The empirical boundary

``assert_empirical`` continues to fail closed: a synthetic dataset is refused by
evaluation, calibration and validation. The simulation pipeline does not weaken it.

## Consequences

* The full flow works: ``ModelSpecification → compile → stored model → Runner →
  Simulation → synthetic dataset``, all deterministic, inspectable and
  provenance-preserving.
* **Bounded by design.** Only the ODE subset the engine can safely execute is
  compiled; every other model kind or construct fails closed with an explanation.
  Algebraic/discrete models, derived variables, non-rate relationships and
  arbitrary expression forms are **not** supported.
* **Simulation window.** The compiler bakes the integration window
  (``t_span``/``n_points``) into the model; a simulation must use the same window
  (``simulation_window_mismatch`` otherwise) because ``OdeModel`` fixes its grid at
  construction and the Runner does not carry a window. ``default_simulation_config``
  reads a model's window so callers need not guess.
* **Scalar outputs** are not part of the synthetic dataset (they share no time
  axis); requesting one explicitly fails closed; unrequested scalar outputs are
  reported as a diagnostic.
* **Dataset identity.** A synthetic dataset's artifact id includes its creation
  timestamp, so two identical simulations produce scientifically identical data
  (same ``science_hash``) with different artifact ids — matching DRW's existing
  ``content_hash`` vs ``science_hash`` model. Pass ``generated_at`` (or rely on the
  SI action's store-level idempotency) for a fully reproducible artifact.
* **Stochastic models** are not supported without an explicit seed; the current
  compiled family is deterministic ODEs.
* **Unmodified**: ``ExperimentSpec``, ``ModelSchema``, ``Runner``, the M11
  observation/dataset contracts, M12A/B/C, and the evidence format. Zero new
  dependencies.

## References

* ADR-0028 - Scientific Intelligence (the action registry this plugs into).
* `docs/ai/scientific-intelligence.md` - the operator/user guide.
* `docs/architecture/ADR-0005-isolated-execution.md` - isolation (a process
  boundary, not a sandbox; the compiler never emits code).
