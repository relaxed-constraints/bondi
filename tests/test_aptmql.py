"""AptMQL sources use native BSON and the shared write/error contracts."""

import hashlib
import json
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from bson import BSON, Decimal128, ObjectId
from click.testing import CliRunner

from bondi import CouchbaseConnection, MongoConnection
from bondi._cli import cli as main
from bondi.data import LoadDataError, _aptmql, load_aptmql_dataset, load_aptmql_repository


@pytest.fixture
def hub(tmp_path, monkeypatch):
    files = {}
    calls = []

    def add(dataset, collection, rows, split="train"):
        filename = f"databases/{split}/{dataset}/dump/{collection}.bson"
        path = tmp_path / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"".join(BSON.encode(row) for row in rows))
        files[filename] = path
        return path

    class API:
        def dataset_info(self, repo, *, revision):
            calls.append(("resolve", repo, revision))
            return SimpleNamespace(sha="a" * 40)

        def list_repo_files(self, repo, *, repo_type, revision):
            assert revision == "a" * 40
            return [*files, "databases/train/beer_factory/dump/ignored.metadata.json", "README.md"]

    def download(repo, filename, *, repo_type, revision):
        assert repo == _aptmql.REPOSITORY and repo_type == "dataset" and revision == "a" * 40
        calls.append(("download", filename))
        return str(files[filename])

    monkeypatch.setattr(_aptmql, "HfApi", API)
    monkeypatch.setattr(_aptmql, "hf_hub_download", download)
    return SimpleNamespace(add=add, files=files, calls=calls)


@pytest.fixture
def writer(monkeypatch):
    class Writer:
        data = {}
        closed = 0

        def __init__(self, conn):
            pass

        def preflight(self, dest, quota):
            return bool(self.data.get(dest))

        def prepare(self, dest, mode, **kwargs):
            if mode == "replace" or dest not in self.data:
                self.data[dest] = {}

        def insert_batch(self, dest, batch):
            self.data[dest].update(batch)

        def upsert_one(self, dest, key, document):
            self.data[dest][key] = document

        def close(self):
            type(self).closed += 1

    monkeypatch.setattr("bondi.data._loader.MongoWriter", Writer)
    monkeypatch.setattr("bondi.data._loader.CouchbaseWriter", Writer)
    return Writer


@pytest.mark.parametrize("backend", ["mongodb", "couchbase"])
def test_native_bson_types_destinations_and_provenance(hub, writer, backend):
    oid = ObjectId()
    date = datetime(2026, 1, 1, tzinfo=UTC)
    rows = [{"_id": oid, "parent": oid, "date": date, "literal": {"$numberInt": "17"}}]
    path = hub.add("beer_factory", "brands", rows)
    hub.add("beer_factory", "reviews", [{"_id": 2, "brandId": oid}])
    hub.add("other", "items", [{"_id": 3}], split="dev")
    target = (
        MongoConnection("mongodb://unused")
        if backend == "mongodb"
        else CouchbaseConnection("couchbase://unused", "user", "password")
    )
    kwargs = (
        {"database": "renamed"}
        if backend == "mongodb"
        else {"bucket": "research", "scope": "renamed"}
    )
    progress = []
    results = load_aptmql_dataset(
        "beer_factory",
        connection=target,
        revision="tag",
        batch_size=1,
        on_progress=progress.append,
        **kwargs,
    )
    assert list(results) == ["brands", "reviews"]
    assert len([c for c in hub.calls if c[0] == "download"]) == 2
    assert hub.calls[0] == ("resolve", _aptmql.REPOSITORY, "tag")
    assert len(progress) == 2 and writer.closed == 2
    dest = (
        ("renamed", None, "brands") if backend == "mongodb" else ("research", "renamed", "brands")
    )
    stored = next(iter(writer.data[dest].values()))
    assert stored["_id"] == (oid if backend == "mongodb" else str(oid))
    assert stored["parent"] == stored["_id"]
    assert stored["date"] == (date if backend == "mongodb" else "2026-01-01T00:00:00.000Z")
    assert stored["literal"] == {"$numberInt": "17"}
    info = results["brands"].sources[0]
    assert info["revision"] == "a" * 40 and info["split"] == "train"
    assert info["sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()
    assert results["brands"].source_counts == {"beer_factory.brands:train": 1}


@pytest.mark.parametrize("backend", ["mongodb", "couchbase"])
def test_repository_separates_datasets_with_same_collection(hub, writer, backend):
    hub.add("zeta", "items", [{"_id": 1}], split="dev")
    hub.add("alpha", "items", [{"_id": 1}])
    target = (
        MongoConnection("mongodb://unused")
        if backend == "mongodb"
        else CouchbaseConnection("couchbase://unused", "user", "pass")
    )
    kwargs = {} if backend == "mongodb" else {"bucket": "research"}
    results = load_aptmql_repository(connection=target, **kwargs)
    assert list(results) == ["alpha", "zeta"]
    assert len([c for c in hub.calls if c[0] == "resolve"]) == 1
    assert len(writer.data) == 2
    assert all(sum(r["items"].destinations.values()) == 1 for r in results.values())
    assert (
        ("alpha", None, "items") in writer.data
        if backend == "mongodb"
        else ("research", "alpha", "items") in writer.data
    )


def test_failure_keeps_counts_from_previous_databases_and_closes_stream(hub, writer):
    hub.add("alpha", "items", [{"_id": 1}])
    path = hub.add("zeta", "items", [{"_id": 1}, {"_id": 1}])
    with pytest.raises(LoadDataError, match="Duplicate") as caught:
        load_aptmql_repository(connection=MongoConnection("mongodb://unused"), batch_size=1)
    assert caught.value.result.destinations == {"alpha.items": 1, "zeta.items": 1}
    assert caught.value.result.source_counts == {"alpha.items:train": 1, "zeta.items:train": 1}
    assert len(caught.value.result.sources) == 2
    assert writer.closed == 2
    path.unlink()  # Reader has exited its file context after failure.


def test_bad_bson_is_reported_with_partial_receipt(hub, writer):
    path = hub.add("beer_factory", "brands", [{"_id": 1}])
    path.write_bytes(path.read_bytes() + b"\x05\x00\x00\x00x")
    with pytest.raises(LoadDataError) as caught:
        load_aptmql_dataset(
            "beer_factory", connection=MongoConnection("mongodb://unused"), batch_size=1
        )
    assert caught.value.result.destinations == {"beer_factory.brands": 1}


def test_unsupported_couchbase_values_fail_explicitly(hub, writer):
    hub.add("beer_factory", "brands", [{"_id": 1, "price": Decimal128("1.25")}])
    target = CouchbaseConnection("couchbase://unused", "user", "pass")
    with pytest.raises(LoadDataError, match="decimal_mode"):
        load_aptmql_dataset("beer_factory", connection=target, bucket="research")
    result = load_aptmql_dataset(
        "beer_factory", connection=target, bucket="research", decimal_mode="string"
    )
    assert result["brands"].conversions == {"decimal_string": 1}


@pytest.mark.parametrize("problem", ["missing", "ambiguous", "bad_name", "bucket", "mode"])
def test_invalid_selection_has_no_writes(hub, writer, problem):
    hub.add("beer_factory", "brands", [{"_id": 1}])
    kwargs = {}
    selected = "beer_factory"
    if problem == "missing":
        selected = "missing"
    if problem == "ambiguous":
        hub.add("beer_factory", "other", [{"_id": 1}], split="dev")
    if problem == "bad_name":
        kwargs["database"] = "../bad"
    if problem == "bucket":
        kwargs["bucket"] = "wrong"
    if problem == "mode":
        kwargs["json_mode"] = "extended"
    with pytest.raises(ValueError):
        load_aptmql_dataset(selected, connection=MongoConnection("mongodb://unused"), **kwargs)
    assert not writer.data


def test_download_failure_precedes_all_writes(hub, writer, monkeypatch):
    hub.add("beer_factory", "brands", [{"_id": 1}])
    monkeypatch.setattr(
        _aptmql, "hf_hub_download", lambda *a, **kw: (_ for _ in ()).throw(OSError())
    )
    with pytest.raises(OSError):
        load_aptmql_dataset("beer_factory", connection=MongoConnection("mongodb://unused"))
    assert not writer.data


@pytest.mark.parametrize("repository", [False, True])
@pytest.mark.parametrize("backend", ["mongodb", "couchbase"])
def test_cli_loads_and_serializes_results(hub, writer, tmp_path, monkeypatch, repository, backend):
    hub.add("beer_factory", "brands", [{"_id": 1}])
    conn = tmp_path / "connection.json"
    config = {"backend": backend, "uri": f"{backend}://unused"}
    if backend == "couchbase":
        config.update(username="user", password_env="BONDI_TEST_PASSWORD")
        monkeypatch.setenv("BONDI_TEST_PASSWORD", "test")
    conn.write_text(json.dumps(config))
    command = (
        ["dataset", "load-aptmql-repository"]
        if repository
        else ["dataset", "load-aptmql", "beer_factory"]
    )
    if backend == "couchbase":
        command += ["--bucket", "research"]
    result = CliRunner().invoke(main, [*command, "--connection", str(conn), "--revision", "tag"])
    assert result.exit_code == 0, result.output
    output = json.loads(result.output)
    if repository:
        output = output["beer_factory"]
    destination = "beer_factory.brands" if backend == "mongodb" else "research.beer_factory.brands"
    assert output["brands"]["destinations"] == {destination: 1}
    if repository:
        result = CliRunner().invoke(main, [*command, "--connection", str(conn), "--database", "x"])
        assert result.exit_code != 0
