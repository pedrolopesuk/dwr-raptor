# ADR-0025: Calibration identity, provenance & persistence

**Status:** Accepted

## Context

A calibration search must be reproducible and its result a content-addressable
artifact, like the rest of DRW. It must be possible to answer "what exactly was
searched?" separately from "what was found?".

## Decision

Two distinct identities, reusing canonical serialization (`content_hash`):

* **`calibration_hash` — the REQUEST.** A canonical payload of
  `CalibrationConfig` excluding non-scientific metadata (`notes`). It covers:
  schema version; `model_ref` + `model_hash`; the free parameter selections
  (name, lower, upper, initial, scale) in **canonical name order**; fixed values;
  the objective; the optimizer name and full config; the budget; the seed; the
  execution template; `dataset.content_hash` **and** `dataset.science_hash`; the
  canonical mapping; the `EvaluationConfig`; the identifiability mode; the data
  role. Changing any scientifically meaningful setting changes the hash.
* **`result_hash` — the OUTCOME.** A canonical payload of the `CalibrationResult`
  (best candidate, status, convergence, full bounded candidate history,
  diagnostics, provenance). **Wall-clock durations are excluded** (the outcome
  identity is the deterministic candidate search, not how long it took), so two
  equivalent runs produce identical `result_hash`.

**Provenance** records: experiment id, spec hash, model id + model hash,
environment hash, **SciPy version**, dataset `content_hash` + `science_hash`,
mapping hash, evaluation-config hash and the best candidate's `evaluation_hash`.

**Persistence (Phase D):** a separate content-addressed `CalibrationStore`
(ADR-0017 principles) at `<workspace>/calibrations/<calibration_id>/` with
`config.json`, `result.json` (history omitted), `history.json`, `provenance.json`
and a `manifest.json` of SHA-256 hashes. `calibration_id = "cal-" + result_hash[:12]`.
Append-only, idempotent for an identical payload, rejects a different payload under
an existing id, and verifies file hashes and re-derives the result hash.

**No `EvidenceManifest` change** and no persistence in the pure core; storage is a
separate step the CLI/bridge invoke explicitly (`--persist` / `persist=true`).

## Consequences

* The reproducibility guarantee: *within a reproducibly equivalent execution
  environment, an identical calibration identity and deterministic execution
  produce identical candidate parameters, ordering, objective sequence, history,
  best candidate and `result_hash`.* `calibration_hash` alone does **not** promise
  identical results across arbitrary environments (SciPy/model versions may
  differ); those are captured by provenance instead.
* Evidence-package integration of calibrations is deferred (additive, later).
