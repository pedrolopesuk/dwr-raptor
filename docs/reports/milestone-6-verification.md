# Milestone 6 - implementation report: evidence verification and documentation fix

Implements **D1 (first-party evidence verification)** and **D2 (documentation
drift)** from `docs/reports/milestone-6-investigation.md`, and nothing else. No
change to experiment identity, deterministic ids, overwrite behaviour, schemas,
model hashes, numerical methodology, or the evidence format. The investigation
(`milestone-6-investigation.md`) documents the findings and scope.

---

## 1. What changed

**D1 - `verify_evidence(manifest_path)`** (`packages/core/src/drw/execution/evidence.py`).
A read-only check of a package against its manifest:

* every artifact the manifest declares must **exist**, stay **inside the
  manifest's directory** (absolute paths and `..` escapes are rejected), and match
  its recorded **size** and **SHA-256**;
* per-artifact status: `ok`, `missing`, `size_mismatch`, `hash_mismatch`,
  `invalid_path`, `invalid_entry`, `unreadable`;
* the package is `ok` only when **no declared artifact failed**;
* **undeclared files** present in the directory are listed in `extra_files` and
  are explicitly **not** verified. They do not, on their own, fail verification -
  an exported store package legitimately contains `evidence.zip`, and the manifest
  itself is not an artifact. This behaviour is documented in the model docstring.
* a missing / unreadable / malformed manifest (bad JSON, not an object, no `files`
  list) raises `EvidenceVerificationError` (a `ValueError`).

**D1 - `drw verify` CLI subcommand** (`packages/core/src/drw/cli.py`). Prints each
artifact's status and a verdict. Exit codes: **0** verified, **1** verification
failed, **2** unusable manifest/path (raised as `ValueError`, handled by `main`).

**D1 - `verify_evidence` bridge op** (`packages/core/src/drw/api.py`). Read-only.
It takes an `experiment_id` (not a path), resolves the manifest via
`ExperimentStore.experiment_dir` (which validates the id and path containment), and
returns `{experiment_id, verification}`. An experiment with no evidence package →
`not_found`; an unusable manifest → `bad_request`; a failed verification is
returned as data with `verification.ok = false` (HTTP 200, mirroring `validate`).

**D2 - documentation correction.** `drw/numerics/delta.py` module docstring and
`docs/testing/acceptance-matrix.md` row 13 now state the implemented rule:
`r = Δy / y_ref` where `|y_ref| > ε`, else `NaN` (flagged) - matching ADR-0006.
No numerical code changed.

---

## 2. Files changed

| File | Change |
| --- | --- |
| `packages/core/src/drw/execution/evidence.py` | add `verify_evidence` + result models + `EvidenceVerificationError` |
| `packages/core/src/drw/cli.py` | add `verify` subcommand + handler + dispatch entry |
| `packages/core/src/drw/api.py` | add `op_verify_evidence`, register it, update the op list docstring |
| `packages/core/src/drw/numerics/delta.py` | docstring corrected (D2) |
| `tests/integration/test_evidence_verify.py` | **new** - 10 verifier tests |
| `tests/integration/test_cli.py` | + verify exit-code test |
| `tests/integration/test_api_bridge.py` | + 2 verify-op tests |
| `docs/testing/acceptance-matrix.md` | row 13 corrected; row 40 added; totals updated |
| `CHANGELOG.md`, `README.md` | M6 entry; `drw verify` documented |
| `docs/reports/milestone-6-verification.md` | this report |

---

## 3. Verification semantics (and its limits)

A successful verification means the package is **internally consistent** with its
manifest: the four declared artifacts are present and byte-for-byte match the
recorded sizes and SHA-256. It is **not** cryptographic authenticity: the manifest
is neither self-hashed nor signed, so a party able to rewrite both an artifact and
the manifest can make a tampered package verify. Verification is strictly
read-only - it never rewrites manifests, artifacts, experiment records, or stored
results (asserted by `test_verification_is_read_only`).

---

## 4. Commands and observed results

**Focused tests** (new + affected):
`.venv\Scripts\python.exe -m pytest -q tests/integration/test_evidence_verify.py tests/integration/test_cli.py tests/integration/test_api_bridge.py`
→ **38 passed** in 45.82s.

**Full suite / quality gates** (all run in this session):

| Command | Result |
| --- | --- |
| `.venv\Scripts\python.exe -m ruff check packages/core/src tests scripts` | All checks passed |
| `.venv\Scripts\python.exe -m pytest -q` | **179 passed** in 68.49s (was 166; +13 tests) |
| `pnpm -r typecheck` | exit 0 |
| `pnpm --filter @drw/experiment-spec test` | 5 pass / 0 fail |
| `pnpm --filter @drw/web test` | **44 passed** (6 files) in 62.55s |
| `pnpm --filter @drw/web build` | Compiled successfully; `/` 56.9 kB / 160 kB |
| `pnpm --filter @drw/web e2e:only` (Playwright/Chromium) | **4 passed** in 36.5s |

**Manual CLI demonstration** (`drw run … --out <tmp>` then `drw verify`):

```
--- verify (intact) ---
[OK] experiment-spec.json
[OK] model-schema.json
[OK] results.json
[OK] report.md
result: OK (4 verified, 0 failed)          exit=0
--- verify (tampered results.json) ---
[OK] experiment-spec.json
[OK] model-schema.json
[SIZE_MISMATCH] results.json (expected 162284 bytes, got 162285)
[OK] report.md
result: FAILED (3 verified, 1 failed)      exit=1
```

Coverage added: valid package; modified file (same size → `hash_mismatch`); size
mismatch; missing file; extra/undeclared file (reported, still `ok`); path-escape
entry (`invalid_path`, `ok=False`); malformed manifest and missing `files` list and
missing manifest (all raise); read-only assertion; CLI exit codes 0/1/2; bridge op
valid + tampered + unknown experiment (`not_found`).

---

## 5. Remaining limitations

* **No cryptographic authenticity** (unsigned manifest) - by design; stated in the
  code docstring, this report and the acceptance matrix.
* A **dangling entry cannot be distinguished from a correct one** if the manifest
  itself was edited to match - inherent to a consistency check.
* Bridge verification is scoped to **stored experiments** (`experiment_id`); there
  is no web UI button for it in this milestone (CLI + bridge op only).
* Pre-existing limitations from the investigation are unchanged and intentionally
  out of scope: structured solver fields, `t_span`/`n_points` metadata,
  `verification.checks` being inert, `ANALYZED/VERIFIED/EXPORTED` unused, and the
  "isolation is not a sandbox" caveat.

---

## 6. Checks not run

* Live (`local-acceptance.spec.ts`) browser run was **not** re-run this session;
  the isolated Chromium suite (`workspace.spec.ts` + `accessibility.spec.ts`) was.
* No cross-machine/cross-OS reproducibility test.
* `ruff format --check` remains non-clean repo-wide (pre-existing; not a CI gate).
