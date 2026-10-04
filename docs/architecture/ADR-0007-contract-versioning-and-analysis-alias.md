# ADR-0007: Contract naming, aliasing and versioning

**Status:** Accepted

## Context

Two contract issues were outstanding from the audit:

1. The specification (section 7.3) names the analyses list `analysis[]`, while the
   Pydantic model uses `analyses`. Ambiguity A5 left this "resolved by
   documentation" only, so an AI- or user-authored spec using the specification's
   own field name would be rejected.
2. `ExperimentSpec.schema_version` was accepted but never checked, and nothing
   prevented the committed JSON Schemas from drifting away from the Pydantic
   models or from the TypeScript mirror.

## Decision

**Aliasing.** `ExperimentSpec` accepts the specification's singular `analysis`
key on input via a `mode="before"` validator and canonicalises it to `analyses`.
Supplying both is an error. The canonical field name - and therefore the JSON
Schema property - is `analyses`. This is input compatibility without a second
representation.

**Versioning.** `validate_experiment` emits a `schema_version_mismatch` warning
when `spec.schema_version` differs from the engine's `EXPERIMENT_SCHEMA_VERSION`.
It is a warning, not an error, because a compatible spec from a nearby version
should still be usable; a hard version gate would be a later, deliberate change.

**Drift detection.** `tests/integration/test_schema_contract.py` regenerates the
JSON Schemas and asserts they are byte-identical to the committed files, validates
an example spec against the schema with `jsonschema`, and asserts the required
field set. The TypeScript package has a matching test that reads the same
committed schema and asserts the guard's required fields and canonical names
agree. If the Python contract changes without regenerating, CI fails with a clear
message.

## Consequences

* `analysis:` and `analyses:` both work; only `analyses` is emitted.
* Schema drift is now a test failure rather than a silent divergence.
* The TS mirror remains hand-written, but its agreement with the generated schema
  on the load-bearing fields (required set, canonical names, `execution`) is
  tested. Full structural parity would require generating the TS types; that is
  deferred until the web app exists.
