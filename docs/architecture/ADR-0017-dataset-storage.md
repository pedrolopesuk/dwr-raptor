# ADR-0017: Dataset storage, content addressing & integrity

**Status:** Accepted

## Context

M11A defined the universal observation/data contract (`Dataset`,
`ObservationSet`, `Variable`, `DatasetRef`, `ObservationMapping`) but persisted
nothing. M11B adds the storage/integrity layer beneath that contract: an
immutable, content-addressed local store for datasets, reusing the conventions of
`drw.store.ExperimentStore` and the canonical serialization/hashing of
`drw.schema.serialization`.

It is storage only: no import adapters, no calibration, no CLI/web.

## Decision

* **Layout.** Under the workspace root::

      <root>/datasets/<dataset_id>/
          meta.json          # identity + descriptive metadata + DatasetFile list
          schema.json        # coordinates + variables (the ObservationSet shape)
          data.json          # the columns (the observation payload)
          provenance.json    # the M11A Provenance object
          files/             # packaged referenced files (only when present)

  `<dataset_id>` is validated against `^ds-[0-9a-f]{12}$` and every resolved path
  is contained to the workspace (`DatasetStore.dataset_dir`), exactly like
  `ExperimentStore`. No database, no cloud, no new dependency.

* **Immutability / append-only.** Saving a new dataset creates its directory;
  saving the *exact same* dataset again is idempotent (no rewrite, `created_at`
  preserved); saving a *different* dataset under an existing id raises
  `DatasetExistsError` and never overwrites. There is no `update_dataset()`, no
  destructive mutation API, and a stored dataset stays readable.

* **Content addressing.** The **full** `content_hash` (canonical serialization of
  the scientific content) is authoritative; `dataset_id = "ds-" + hash[:12]`.
  `save` recomputes and checks the hash, and requires `dataset_id` to be the short
  hash of the content (rejecting corrupted identity metadata). A short id already
  bound to a different full hash is refused - two different full hashes can never
  silently resolve to the same id.

* **`DatasetRef`.** Carries `dataset_id`, the full `content_hash`, `name` and
  (storage-layer, non-identity) `created_at`. `DatasetStore.ref`/`list`/`resolve`
  reconstruct it; `resolve(content_hash)` looks a dataset up by its authoritative
  hash, and loading/resolving a corrupted or replaced dataset **fails** rather
  than silently selecting another.

* **Verification.** `DatasetStore.verify(dataset_id)` returns a structured
  `DatasetVerification` (per-check `ok`/`missing`/`unreadable`/`invalid`/
  `mismatch`/`not_packaged`, plus `errors`/`ok`). It checks: the directory and
  required files exist; JSON is readable; the dataset reconstructs; `meta.dataset_id`
  matches the directory; the stored `content_hash` matches the recomputed content;
  the id is the short hash of the content; each `DatasetFile` is internally valid;
  and any **packaged** file matches its declared SHA-256/size. It never repairs
  corruption - a failed verification stays failed.

* **Packaged vs external files.** `DatasetFile` metadata may describe files that
  are not present locally (synthetic/manual/derived datasets have none). A merely
  referenced file is reported `not_packaged` and is **never** claimed verified. A
  packaged file (present in `files/`) is hash-verified. `DatasetStore.package_file`
  copies a local file into `files/` **only** when its bytes match the declared
  metadata, and never overwrites - it is a portability primitive, not an adapter
  (no download/fetch).

* **Listing.** `list()` reads only `meta.json` (never the payload), validates the
  id format, ignores unrelated directories and identity-inconsistent entries, and
  returns references in a deterministic order (newest first, id tiebreak).

## Consequences

* An M11A `Dataset` can be persisted, loaded, listed, referenced and
  cryptographically verified without touching the experiment/evidence
  architecture; `ExperimentStore`, `EvidenceManifest` and storage layouts are
  unchanged.
* A dataset directory is self-contained for copying between workspaces once its
  referenced files are packaged into `files/`.
* Observation integrity is **not** model validity, calibration or a scientific
  conclusion; passing `verify` proves the stored bytes match the declared content
  and identity, nothing more.
* Import adapters (CSV first), the import UX, CLI/bridge ops, and packaging during
  import are M11C; FITS/Parquet/HDF5/NetCDF adapters are later and optional. No
  database or cloud storage exists because the local-first, single-user,
  content-addressed filesystem store is sufficient and keeps the workspace
  portable.

## Boundary

M11B owns persistence, identity, immutability and integrity verification. It owns
no import/parse logic, no UI, no calibration and no N-D array storage.
