# ADR-0018: CSV observation adapter & dataset import

**Status:** Accepted

## Context

M11A defined the universal observation contract and M11B added immutable,
content-addressed dataset storage. Neither knows how to *read* a file. M11C adds
the first ingestion path - **CSV** - chosen because it needs zero new dependency
(stdlib `csv`) and is universal across the five target domains. The internal
scientific model must stay separate from import/export: nothing in
`ObservationSet`/`Dataset`/`DatasetStore` may know about CSV.

## Decision

* **Adapter boundary.** An `ObservationAdapter` protocol
  (`drw/adapters/__init__.py`) exposes a stable `id`/`version` and three
  operations - `can_handle` (cheap format check), `inspect` (advisory,
  non-persistent) and `read` (parse + build a validated `Dataset`). Adapters are
  registered in a small registry (mirroring `drw.models.registry`); CSV is the
  first, registered as `csv` v`1.0.0`.
* **Inspection vs import.** `CsvAdapter.inspect(source)` reads the file and
  returns advisory structure only - column names, inferred *primitive* kind
  (int/float/bool/categorical/datetime), row count, a preview, missing/non-finite
  counts, and candidate coordinate/measurement/uncertainty/quality roles. It
  persists nothing and never turns a suggestion into scientific semantics.
  `CsvAdapter.read(source, config)` parses under an explicit `CsvImportConfig` and
  builds the M11A `Dataset` (validated).
* **Structural vs scientific inference.** Structural inference (primitive kind) is
  safe and performed. Scientific semantics - units, physical quantity, coordinate
  meaning, measurement/uncertainty/quality meaning, domain - are **never**
  inferred; they come only from the configuration. Column roles are required in
  the configuration (no role is ever assumed).
* **Explicit configuration.** `CsvImportConfig` declares, per column, the role,
  optional name/kind/unit, `depends_on` coordinates, uncertainty (companion
  column(s) or inline), quality flag column, per-column missing codes, and
  datetime format; plus dataset name/description/version/labels, delimiter/header
  overrides, global missing codes, and explicit non-finite/invalid policies
  (`error` by default, or `missing`). Companion references use the destination
  variable names and are validated by the M11A contract.
* **Missing/invalid/non-finite.** Empty cells and configured sentinels become
  explicit *missing* (`null`); non-finite (`nan`/`inf`) and type-invalid cells are
  detected and, by default, **fail the import with diagnostics** (they are not
  storable in M11A). A deliberate policy may map them to missing. Quality flags
  live in a companion column and never delete rows.
* **Datetime.** ISO-8601 via the standard library (or an explicit `strptime`
  format), normalised to ISO; no astronomical time system (JD/MJD/TAI/TT/GPS).
* **Import path.** `import_csv(source, config, store, dry_run=False)` is the single
  parse -> validate -> `Dataset` -> `DatasetStore.save` path (the CLI and bridge
  share it, so persistence is never duplicated). A `dry_run` validates and returns
  the computed `DatasetRef` without writing anything; a failed import leaves no
  partial dataset.
* **Local-first and contained.** The bridge reads only files under
  `<workspace>/dataset-sources/` (a bare relative filename, contained; absolute
  paths and `..` escapes are rejected). No browser upload to a cloud service. The
  CLI reads any local path (a local, trusted user, like `drw run`).
* **Interfaces.** CLI `drw dataset inspect|import|list|describe|verify`; bridge ops
  `list_dataset_sources`, `inspect_dataset`, `import_dataset`, `list_datasets`,
  `describe_dataset` (alias `get_dataset`), `verify_dataset`; web "Import a
  dataset (CSV)" and "Datasets" panels that distinguish **Detected / Suggested /
  Configured / Validated**.

## Consequences

* A researcher can turn a CSV into an immutable, verifiable dataset without any
  domain-specific code, and the same contract represents astrophysics, space,
  physics, biology and climate data (the adapter only ever produces `Variable`s).
* Import integrity is explicit: imports are the only mutating operation, are
  idempotent for identical content, and a changed scientific value yields a
  different identity. `DatasetStore` verification confirms the stored bytes match
  the declared content.
* Importing a dataset proves **observation integrity only** - never model validity,
  calibration or a scientific conclusion.
* Future adapters (Parquet, HDF5, NetCDF, FITS) implement the same protocol and
  register under new ids; FITS/astronomy specifics stay entirely inside such an
  adapter. N-D array payloads and interpolation/resampling remain out of scope
  (M12+).

## Boundary

M11C owns parsing, inspection, configuration, and the CLI/bridge/web surfaces for
CSV import. It does not own storage (M11B), the core contract (M11A), calibration/
fitting/residuals (M12), or any non-CSV format.
