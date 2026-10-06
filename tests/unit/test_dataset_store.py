"""Unit tests for M11B dataset storage, provenance and integrity."""

from __future__ import annotations

import json

import pytest

from drw.dataset_store import (
    DatasetCorruptedError,
    DatasetExistsError,
    DatasetNotFoundError,
    DatasetStore,
    DatasetStoreError,
    InvalidDatasetId,
)
from drw.observations import build_dataset
from drw.schema.observation import (
    DatasetFile,
    DatasetRef,
    ObservationSet,
    Provenance,
    Variable,
    short_dataset_id,
)
from drw.schema.serialization import sha256_hex

pytestmark = pytest.mark.unit

_IMPORTED_AT = "2026-01-01T00:00:00+00:00"


# ---------------------------------------------------------------------------
# Helpers.
# ---------------------------------------------------------------------------


def provenance(source_kind: str = "synthetic") -> Provenance:
    return Provenance(source_kind=source_kind, imported_at=_IMPORTED_AT, dataset_version="1.0.0")


def make_dataset(name="ds", temperature=300.0, *, source_kind="synthetic", files=()):
    variables = (
        Variable(name="t", kind="float", role="coordinate", unit="s"),
        Variable(
            name="temperature",
            kind="float",
            role="measurement",
            unit="K",
            depends_on=("t",),
        ),
    )
    observation_set = ObservationSet(
        coordinates=("t",),
        variables=variables,
        columns={"t": [0.0, 1.0], "temperature": [temperature, temperature + 1.0]},
    )
    return build_dataset(name, observation_set, provenance(source_kind), files=files)


def meta_path(store: DatasetStore, dataset_id: str):
    return store.dataset_dir(dataset_id) / "meta.json"


def rewrite(path, payload) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")


@pytest.fixture
def store(tmp_path) -> DatasetStore:
    return DatasetStore(tmp_path / "workspace")


# ---------------------------------------------------------------------------
# 1-4. Round trip, determinism, idempotency, overwrite refusal.
# ---------------------------------------------------------------------------


def test_save_load_round_trip(store):
    dataset = make_dataset("round trip", 300.0)
    store.save(dataset)
    loaded = store.load(dataset.dataset_id)
    assert loaded == dataset
    assert loaded.content_hash == dataset.content_hash
    assert loaded.dataset_id == dataset.dataset_id


def test_exact_dataset_reproduces_identical_content_hash(store):
    assert make_dataset("x", 300.0).content_hash == make_dataset("x", 300.0).content_hash


def test_saving_the_same_dataset_twice_is_idempotent(store):
    dataset = make_dataset("idem", 300.0)
    first = store.save(dataset)
    before = (first / "meta.json").read_bytes()
    again = store.save(dataset)
    assert again == first
    assert (first / "meta.json").read_bytes() == before
    assert store.load(dataset.dataset_id) == dataset


def test_different_dataset_cannot_overwrite_an_existing_id(store):
    dataset_a = make_dataset("a", 300.0)
    dataset_b = make_dataset("b", 301.0)
    assert dataset_a.dataset_id != dataset_b.dataset_id
    store.save(dataset_a)

    # Craft a dataset that claims A's id but carries different content (a
    # simulated short-id collision). model_copy does not re-validate, so this is
    # exactly the "a different dataset under an existing id" situation.
    colliding = dataset_b.model_copy(update={"dataset_id": dataset_a.dataset_id})
    with pytest.raises(DatasetExistsError, match=r"collision|immutable"):
        store.save(colliding)
    # A's stored dataset is untouched.
    assert store.load(dataset_a.dataset_id) == dataset_a


def test_short_id_collision_is_refused(store):
    dataset_a = make_dataset("a", 300.0)
    dataset_b = make_dataset("b", 301.0)
    store.save(dataset_a)
    colliding = dataset_b.model_copy(update={"dataset_id": dataset_a.dataset_id})
    with pytest.raises(DatasetExistsError):
        store.save(colliding)


# ---------------------------------------------------------------------------
# 5-11. Corruption and identity detection.
# ---------------------------------------------------------------------------


def test_corrupted_meta_is_detected(store):
    dataset = make_dataset("meta", 300.0)
    store.save(dataset)
    meta_path(store, dataset.dataset_id).write_text("{not valid json", encoding="utf-8")
    with pytest.raises(DatasetCorruptedError):
        store.load(dataset.dataset_id)
    report = store.verify(dataset.dataset_id)
    assert report.ok is False
    assert any(check.name == "meta" and check.status == "unreadable" for check in report.checks)


def test_corrupted_schema_is_detected(store):
    dataset = make_dataset("schema", 300.0)
    store.save(dataset)
    directory = store.dataset_dir(dataset.dataset_id)
    rewrite(directory / "schema.json", {"coordinates": ["t"], "variables": []})
    with pytest.raises(DatasetCorruptedError):
        store.load(dataset.dataset_id)
    assert store.verify(dataset.dataset_id).ok is False


def test_corrupted_data_is_detected(store):
    dataset = make_dataset("data", 300.0)
    store.save(dataset)
    directory = store.dataset_dir(dataset.dataset_id)
    rewrite(directory / "data.json", {"columns": {"t": [0.0, 1.0], "temperature": [300.0]}})
    with pytest.raises(DatasetCorruptedError):
        store.load(dataset.dataset_id)
    assert store.verify(dataset.dataset_id).ok is False


def test_corrupted_provenance_is_detected(store):
    dataset = make_dataset("prov", 300.0)
    store.save(dataset)
    directory = store.dataset_dir(dataset.dataset_id)
    rewrite(directory / "provenance.json", {})
    with pytest.raises(DatasetCorruptedError):
        store.load(dataset.dataset_id)
    assert store.verify(dataset.dataset_id).ok is False


def test_wrong_content_hash_is_detected(store):
    dataset = make_dataset("hash", 300.0)
    store.save(dataset)
    path = meta_path(store, dataset.dataset_id)
    meta = json.loads(path.read_text(encoding="utf-8"))
    meta["content_hash"] = "0" * 64
    rewrite(path, meta)
    with pytest.raises(DatasetCorruptedError):
        store.load(dataset.dataset_id)
    report = store.verify(dataset.dataset_id)
    assert report.ok is False
    assert any(
        check.name == "content_hash" and check.status == "mismatch" for check in report.checks
    )


def test_wrong_dataset_id_is_detected(store):
    dataset = make_dataset("idd", 300.0)
    store.save(dataset)
    path = meta_path(store, dataset.dataset_id)
    meta = json.loads(path.read_text(encoding="utf-8"))
    meta["dataset_id"] = "ds-" + "0" * 12
    rewrite(path, meta)
    with pytest.raises(DatasetCorruptedError):
        store.load(dataset.dataset_id)
    report = store.verify(dataset.dataset_id)
    assert report.ok is False
    assert any(check.name == "dataset_id" and check.status == "mismatch" for check in report.checks)


def test_replaced_content_breaks_identity(store):
    dataset_a = make_dataset("a", 300.0)
    store.save(dataset_a)
    directory = store.dataset_dir(dataset_a.dataset_id)
    # Replace the payload with different scientific content (B's temperature).
    rewrite(directory / "data.json", {"columns": {"t": [0.0, 1.0], "temperature": [301.0, 302.0]}})
    report = store.verify(dataset_a.dataset_id)
    assert report.ok is False
    statuses = {check.name: check.status for check in report.checks}
    assert statuses["content_hash"] == "mismatch"
    assert statuses["identity"] == "mismatch"


def test_missing_required_file_is_detected(store):
    dataset = make_dataset("missing", 300.0)
    store.save(dataset)
    (store.dataset_dir(dataset.dataset_id) / "data.json").unlink()
    with pytest.raises(DatasetCorruptedError, match=r"data\.json"):
        store.load(dataset.dataset_id)
    report = store.verify(dataset.dataset_id)
    assert report.ok is False
    assert any(check.name == "data" and check.status == "missing" for check in report.checks)


# ---------------------------------------------------------------------------
# 12-14. Refs, resolve and listing.
# ---------------------------------------------------------------------------


def test_dataset_ref_round_trip_and_resolve(store):
    dataset = make_dataset("ref", 300.0)
    store.save(dataset)
    reference = store.ref(dataset.dataset_id)
    assert reference.dataset_id == dataset.dataset_id
    assert reference.content_hash == dataset.content_hash
    assert reference.name == dataset.name
    assert reference.created_at is not None
    assert DatasetRef.model_validate(reference.model_dump()) == reference
    assert store.resolve(dataset.content_hash) == reference
    with pytest.raises(DatasetNotFoundError):
        store.resolve("0" * 64)


def test_listing_is_deterministic(store):
    datasets = [make_dataset(f"ds-{index}", 300.0 + index) for index in range(3)]
    for dataset in datasets:
        store.save(dataset)
    first = store.list()
    second = store.list()
    assert first == second
    assert {ref.dataset_id for ref in first} == {dataset.dataset_id for dataset in datasets}


def test_empty_store_lists_nothing(store):
    assert store.list() == []
    assert store.exists("ds-" + "0" * 12) is False


def test_multiple_datasets_are_all_loadable(store):
    datasets = [make_dataset(f"multi-{index}", 300.0 + index) for index in range(3)]
    for dataset in datasets:
        store.save(dataset)
    for dataset in datasets:
        assert store.load(dataset.dataset_id) == dataset


# ---------------------------------------------------------------------------
# 15-19. Synthetic / manual / derived datasets without files.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("source_kind", ["synthetic", "manual", "derived"])
def test_datasets_without_files_round_trip_and_verify(store, source_kind):
    dataset = make_dataset(f"{source_kind}-data", 300.0, source_kind=source_kind)
    store.save(dataset)
    assert store.load(dataset.dataset_id) == dataset
    report = store.verify(dataset.dataset_id)
    assert report.ok is True and report.errors == 0
    assert not any(check.name.startswith("file:") for check in report.checks)


# ---------------------------------------------------------------------------
# 20-22. DatasetFile metadata, packaging and honest reporting.
# ---------------------------------------------------------------------------


def _file_entry(data: bytes, name="obs.csv", role="source") -> DatasetFile:
    return DatasetFile(name=name, sha256=sha256_hex(data), size_bytes=len(data), role=role)


def test_dataset_file_metadata_without_bytes_is_not_falsely_verified(store):
    payload = b"t,temperature\n0,300\n1,301\n"
    dataset = make_dataset("withfile", 300.0, files=(_file_entry(payload),))
    store.save(dataset)
    report = store.verify(dataset.dataset_id)
    # The referenced file is not present locally: reported, never verified.
    assert report.ok is True  # not an error
    file_check = next(check for check in report.checks if check.name == "file:obs.csv")
    assert file_check.status == "not_packaged"


def test_packaged_file_is_hash_verified(store, tmp_path):
    payload = b"t,temperature\n0,300\n1,301\n"
    dataset = make_dataset("packaged", 300.0, files=(_file_entry(payload),))
    store.save(dataset)

    source = tmp_path / "source-obs.csv"
    source.write_bytes(payload)
    destination = store.package_file(dataset.dataset_id, source, name="obs.csv")
    assert destination.read_bytes() == payload

    report = store.verify(dataset.dataset_id)
    assert report.ok is True
    file_check = next(check for check in report.checks if check.name == "file:obs.csv")
    assert file_check.status == "ok"


def test_package_file_rejects_bytes_that_do_not_match(store, tmp_path):
    dataset = make_dataset("pack-mismatch", 300.0, files=(_file_entry(b"declared"),))
    store.save(dataset)
    source = tmp_path / "wrong.bin"
    source.write_bytes(b"different")
    with pytest.raises(DatasetStoreError, match="do not match"):
        store.package_file(dataset.dataset_id, source, name="obs.csv")


def test_packaged_file_is_never_overwritten(store, tmp_path):
    payload = b"declared"
    dataset = make_dataset("pack-immutable", 300.0, files=(_file_entry(payload),))
    store.save(dataset)
    source = tmp_path / "obs.csv"
    source.write_bytes(payload)
    destination = store.package_file(dataset.dataset_id, source, name="obs.csv")
    destination.write_bytes(b"tampered")
    with pytest.raises(DatasetExistsError, match="overwrite"):
        store.package_file(dataset.dataset_id, source, name="obs.csv")


def test_packaged_file_tamper_is_detected(store, tmp_path):
    payload = b"declared"
    dataset = make_dataset("pack-tamper", 300.0, files=(_file_entry(payload),))
    store.save(dataset)
    source = tmp_path / "obs.csv"
    source.write_bytes(payload)
    store.package_file(dataset.dataset_id, source, name="obs.csv")
    (store.dataset_dir(dataset.dataset_id) / "files" / "obs.csv").write_bytes(b"tampered!")
    report = store.verify(dataset.dataset_id)
    assert report.ok is False
    assert any(check.name == "file:obs.csv" and check.status == "mismatch" for check in report.checks)


# ---------------------------------------------------------------------------
# 23-24. Containment and invalid ids.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("bad_id", ["nope", "exp-000000000000", "ds-xyz", "../../etc", "ds-0123"])
def test_invalid_dataset_ids_are_rejected(store, bad_id):
    with pytest.raises(InvalidDatasetId):
        store.dataset_dir(bad_id)
    with pytest.raises(InvalidDatasetId):
        store.load(bad_id)
    assert store.exists(bad_id) is False


def test_path_traversal_in_packaged_file_is_rejected(store, tmp_path):
    payload = b"escape"
    entry = DatasetFile(name="../escape.csv", sha256=sha256_hex(payload), size_bytes=len(payload))
    dataset = make_dataset("traversal", 300.0, files=(entry,))
    store.save(dataset)
    source = tmp_path / "escape.csv"
    source.write_bytes(payload)
    with pytest.raises(InvalidDatasetId):
        store.package_file(dataset.dataset_id, source, name="../escape.csv")
    # Verification reports the unsafe name rather than following it.
    report = store.verify(dataset.dataset_id)
    assert report.ok is False
    assert any(check.status == "invalid" for check in report.checks)


# ---------------------------------------------------------------------------
# 25-26. In-memory mutation and tamper (no silent repair).
# ---------------------------------------------------------------------------


def test_in_memory_mutation_after_save_does_not_alter_persistence(store):
    dataset = make_dataset("mutable", 300.0)
    store.save(dataset)
    dataset.observation_set.columns["temperature"][0] = 999.0  # mutate the in-memory copy
    loaded = store.load(dataset.dataset_id)
    assert loaded.observation_set.columns["temperature"] == [300.0, 301.0]


def test_tampered_dataset_is_not_silently_repaired(store):
    dataset = make_dataset("tamper", 300.0)
    store.save(dataset)
    directory = store.dataset_dir(dataset.dataset_id)
    data_file = directory / "data.json"
    rewrite(data_file, {"columns": {"t": [0.0, 1.0], "temperature": [999.0, 1000.0]}})
    tampered_bytes = data_file.read_bytes()

    with pytest.raises(DatasetCorruptedError):
        store.load(dataset.dataset_id)
    report = store.verify(dataset.dataset_id)
    assert report.ok is False
    # Verification is read-only: the tampered bytes are untouched, not repaired.
    assert data_file.read_bytes() == tampered_bytes


# ---------------------------------------------------------------------------
# Scientific integrity: one changed value changes identity.
# ---------------------------------------------------------------------------


def test_one_changed_scientific_value_changes_identity(store):
    dataset_a = make_dataset("experiment", 300.0)
    store.save(dataset_a)
    reloaded = store.load(dataset_a.dataset_id)
    assert reloaded.content_hash == dataset_a.content_hash

    dataset_b = make_dataset("experiment", 301.0)
    assert dataset_b.content_hash != dataset_a.content_hash
    assert dataset_b.dataset_id != dataset_a.dataset_id
    assert short_dataset_id(dataset_b.content_hash) == dataset_b.dataset_id
