# ADR-0020: Dataset scientific identity vs artifact identity

**Status:** Accepted

## Context

M11 `Dataset.content_hash` covers the *science **and** the provenance* (provenance
is part of the hashed payload), so two otherwise-identical imports differ if their
`imported_at`/source metadata differ. Evaluation and (future) calibration need to
reason about "same measurements, different provenance" without changing M11.

## Decision

* **`content_hash` remains the authoritative artifact identity** (science +
  provenance). `DatasetRef` carries it; evidence, evaluation and future calibration
  reference exactly this hash. **M11 behaviour is unchanged** — no field is added
  to `Dataset`, nothing is persisted, and identity semantics are untouched.
* **Introduce a derived `science_hash`** (`drw.observations.science_hash`) computed
  on demand, never stored, never part of `content_hash`. Its canonical payload is:
  `schema_version`; `coordinates` (sorted); `variables` (sorted by name) with
  `{name, kind, role, unit, depends_on (sorted), uncertainty, quality}`; and the
  `columns` values.
* **Excluded** from `science_hash`: `provenance`, `created_at`, source filename,
  source URI, `imported_at`, adapter metadata and `DatasetFile` transport metadata.
* **Semantics:** equal `science_hash` + different `content_hash` ⇒ the same
  scientific content recorded with different provenance (two distinct **artifact**
  identities that share a science identity). Equal `content_hash` ⇒ the exact same
  artifact.

## Consequences

* Evidence/calibration keep referencing the exact artifact (`content_hash`); the
  science hash is purely additive and lets a consumer say "identical science,
  different provenance".
* The canonical definition is rigorous (sorted lists, declared fields) and covered
  by tests; if it could not be defined rigorously the ADR would have said so
  rather than improvising.
* No change to M11 storage, `DatasetRef`, evidence or reproducibility semantics.

## Consumers

* **Evaluation (M12A)** records `dataset.content_hash` in its provenance (exact
  artifact) and may surface `science_hash` for de-duplication/reporting.
* **Calibration (M12B)** should reference the artifact hash for exact
  reproducibility and may use `science_hash` to detect "same measurements".
