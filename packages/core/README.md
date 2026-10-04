# drw-core

The scientific core of the Differential Research Workbench. This is a pure
Python package (no network, no framework) that owns the typed contracts and the
deterministic numerical primitives the rest of the platform is built on.

Modules:

| Module | Responsibility |
| --- | --- |
| `drw.schema` | `ModelSchema`, `ExperimentSpec`, `ModelResult`, `RunRecord`, units, deterministic serialization. |
| `drw.numerics` | ODE adapter (SCI-001), sampling (SCI-002), time alignment, delta analysis (SCI-003), comparison metrics. |
| `drw.models` | Golden reference models: mass-spring-damper, Lotka-Volterra predator-prey, Lorenz. |
| `drw.execution` | Local run engine, environment fingerprinting, evidence packaging (SCI-005). |
| `drw.cli` | `python -m drw` command line entry points. |

Install for development from the repository root:

```bash
python -m pip install -e "packages/core[dev]"
```

See the repository root `README.md` for the documented end-to-end commands.
