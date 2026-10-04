# Scientific methods

Each implemented method has a short verification note (specification section
13.3): what is being verified, against what reference, at what tolerance, and
when the result is *not* expected to match.

| Method | Note |
| --- | --- |
| ODE integration | [ode-integration.md](./ode-integration.md) |
| Differential analysis | [differential-analysis.md](./differential-analysis.md) |
| Parameter sampling | [sampling.md](./sampling.md) |

Conventions used throughout:

* The **reference** (baseline) series comes first in every metric signature; a
  positive delta means the variant is larger.
* Every numeric artifact carries its **unit** and, for series, the coordinate
  axis and axis unit.
* Every alignment that involves interpolation is **disclosed** in diagnostics.
