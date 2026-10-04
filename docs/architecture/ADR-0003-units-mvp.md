# ADR-0003: Minimal unit system for the MVP

**Status:** Accepted

## Context

The specification repeatedly requires units to be first-class ("Never compare
outputs with incompatible units without an explicit conversion", section 5.7;
"scalar + unit + provenance metadata", section 9.3). It does not name a unit
library. A full dimensional-analysis library (`pint`) is heavy, adds a dependency
for every model author, and its behaviour is not needed to satisfy the MVP rule.

## Decision

Implement a **small, explicit unit system** in `drw.schema.units`:

* Known symbols (`s`, `min`, `m`, `kg`, `K`, `1/s`, `count`, `%`, ...) map to a
  physical dimension and a base scale.
* **Unknown symbols are opaque units**, with the symbol itself as the dimension
  (`"prey"`, `"predator"`, `"N/m"`). Two opaque units are compatible only when
  identical, which is exactly the safety property we need.
* `units_compatible(a, b)` and `convert(value, a, b)` enforce the rule; compared
  outputs are always tagged with their unit.

Full dimensional analysis (compound dimensions, SI prefixes, symbolic algebra) is
**deferred** to an optional `pint`-backed adapter behind the same interface.

## Consequences

* The MVP can distinguish `1/s` from `count` and refuse a nonsensical comparison
  without pulling in a heavyweight dependency.
* Compound units are treated as opaque labels, so `kg*m/s**2` and `N` are *not*
  recognized as the same dimension yet. This is documented as a known limitation
  rather than a silent assumption.
* `%` is modelled as a dimensionless unit with scale `0.01`, so converting `50%`
  to `dimensionless` yields `0.5`.
