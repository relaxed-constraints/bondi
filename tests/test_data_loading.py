"""Dataset identity, splits, conversions and partial-write contracts."""

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from bson import ObjectId

from bondi.data import LoadDataError, MongoConnection, load_data
from bondi.data._values import convert, document_key


@pytest.fixture
def writer(monkeypatch):
    class MemoryWriter:
        backend = "mongodb"
        data = {}
        markers = {}
        index_defs = []
        fail_on = None

        def __init__(self, target):
            pass

        def preflight(self, dest, quota):
            return bool(self.data.get(dest)), self.markers.get(dest)

        def prepare(self, dest, mode, namespace, *, claim=True):
            if mode == "replace" or dest not in self.data:
                self.data[dest] = {}
            if claim:
                self.markers[dest] = {"namespace": namespace, "loader": 1}

        def write_one(self, dest, key, document, mode):
            if document.get("fail"):
                raise RuntimeError("secret connection details")
            self.data[dest][key] = document

        def indexes(self, dest, definitions):
            self.index_defs.extend(definitions)

        def close(self):
            pass

    monkeypatch.setattr("bondi.data._loader.MongoWriter", MemoryWriter)
    return MemoryWriter


def load(source=None, **kwargs):
    return load_data(
        source,
        target=MongoConnection("mongodb://unused"),
        database="test",
        collection="items",
        **kwargs,
    )


def test_modes_ownership_and_whole_document_upsert(writer):
    load([{"_id": "a", "old": 1}])
    with pytest.raises(LoadDataError, match="empty"):
        load([{"_id": "b"}])
    load([{"_id": "a", "new": 2}], mode="upsert")
    docs = writer.data[("test", None, "items")]
    assert list(docs.values()) == [{"_id": "a", "new": 2}]
    writer.markers.clear()
    with pytest.raises(LoadDataError, match="ownership"):
        load([{"_id": "b"}], mode="replace")
    load([{"_id": "b"}], mode="replace", allow_unowned=True)
    assert list(docs.values()) == [{"_id": "a", "new": 2}]  # old map was replaced
    assert list(writer.data[("test", None, "items")].values()) == [{"_id": "b"}]


def test_generated_ids_stable_and_duplicates_preserved(writer):
    load([{"v": 1}, {"v": 1}], namespace="example")
    before = dict(writer.data[("test", None, "items")])
    assert len(before) == 2
    load([{"v": 1}, {"v": 1}], namespace="example", mode="replace")
    assert before == writer.data[("test", None, "items")]


def test_ids_and_partial_results(writer):
    with pytest.raises(LoadDataError, match="namespace") as missing_id:
        load([{"v": 1}])
    message = str(missing_id.value)
    assert "items:unsplit, shard 0, row 0" in message
    assert 'namespace="my-dataset" to generate stable IDs' in message
    assert 'id_field="field_name" to use an existing field' in message
    assert "add _id to each document" in message
    result = []
    with pytest.raises(LoadDataError, match="Duplicate") as error:
        load([{"_id": "a"}, {"_id": "a"}], mode="upsert", batch_size=1, on_progress=result.append)
    assert error.value.result.destinations["test/items"] == 1
    assert len(result) == 1
    with pytest.raises(LoadDataError) as error:
        load([{"_id": "b", "fail": True}], mode="upsert")
    assert error.value.result.uncertain_writes
    assert "secret" not in str(error.value)


def test_preflight_all_destinations_before_replace(writer):
    load_data(
        {"a": [{"_id": "a"}], "b": [{"_id": "b"}]}, target=MongoConnection("x"), database="test"
    )
    writer.markers.pop(("test", None, "b"))
    with pytest.raises(LoadDataError):
        load_data({"a": [], "b": []}, target=MongoConnection("x"), database="test", mode="replace")
    assert writer.data[("test", None, "a")]


def test_splits_merge_and_replace_scope(writer):
    manifest = {
        "version": 1,
        "namespace": "sample",
        "collections": {"items": {"splits": {"train": [{"v": 1}], "test": [{"v": 2}]}}},
    }
    r = load(manifest=manifest)
    assert set(r.destinations) == {"test/items_train", "test/items_test"}
    r = load(manifest=manifest, split="train", mode="replace")
    assert "test/items_test" not in r.destinations
    r = load(manifest=manifest, splits="merge")
    assert r.destinations == {"test/items": 2}
    assert len(writer.data[("test", None, "items")]) == 2


def test_duplicate_ids_across_merged_splits(writer):
    manifest = {
        "version": 1,
        "namespace": "sample",
        "collections": {"items": {"splits": {"train": [{"_id": "a"}], "test": [{"_id": "a"}]}}},
    }
    with pytest.raises(LoadDataError, match="Duplicate"):
        load(manifest=manifest, splits="merge", mode="upsert")


def test_extended_json_and_plain_wrappers(tmp_path, writer):
    path = tmp_path / "rows.jsonl"
    path.write_text('{"_id":"a","d":{"$date":"2020-01-01T00:00:00Z"}}\n')
    load(path, json_mode="plain")
    assert isinstance(next(iter(writer.data[("test", None, "items")].values()))["d"], dict)
    load(path, json_mode="extended", mode="replace")
    assert isinstance(next(iter(writer.data[("test", None, "items")].values()))["d"], datetime)


def test_formats(tmp_path, writer):
    pytest.importorskip("pyarrow")
    import pyarrow as pa
    import pyarrow.parquet as pq

    paths = [tmp_path / "a.csv", tmp_path / "a.json", tmp_path / "a.parquet"]
    paths[0].write_text("_id,x\na,1\n")
    paths[1].write_text('[{"_id":"a","x":1}]')
    pq.write_table(pa.Table.from_pylist([{"_id": "a", "x": 1}]), paths[2])
    for path in paths:
        assert load(path, mode="replace", allow_unowned=True).destinations["test/items"] == 1


def test_couchbase_conversion():
    settings = {"naive_datetimes": "error", "decimal_mode": "error"}
    counts = {}
    oid = ObjectId()
    result = convert(
        {"nested": [oid, datetime(2020, 1, 1, 0, 0, 0, 123456, tzinfo=UTC)]},
        "couchbase",
        settings,
        counts,
    )
    assert result["nested"] == [str(oid), "2020-01-01T00:00:00.123Z"]
    for value in [2**53, Decimal("1.1"), float("inf"), b"bytes", datetime(2020, 1, 1)]:
        with pytest.raises(ValueError):
            convert({"x": value}, "couchbase", settings, {})
    settings["decimal_mode"] = "string"
    assert convert(Decimal("1.1"), "couchbase", settings, {}) == "1.1"
    assert document_key(123) != document_key("123")


def test_cli_catalog(capsys):
    from bondi._cli import main

    assert main(["datasets", "info", "adult"]) == 0
    assert "origami-ml/jsynth-data" in capsys.readouterr().out


def test_upsert_does_not_claim_existing_unowned_data(writer):
    dest = ("test", None, "items")
    writer.data[dest] = {"old": {"_id": "old"}}
    load([{"_id": "new"}], mode="upsert")
    assert dest not in writer.markers
    with pytest.raises(LoadDataError, match="ownership"):
        load([], mode="replace")


@pytest.mark.parametrize("extension", ["json", "jsonl"])
def test_duplicate_json_keys_rejected(tmp_path, writer, extension):
    if extension == "json":
        pytest.importorskip("ijson")
    path = tmp_path / f"data.{extension}"
    path.write_text('{"_id":"a","nested":{"x":1,"x":2}}')
    with pytest.raises(LoadDataError, match="duplicate JSON key"):
        load(path)


def test_manifest_destinations_indexes_and_collisions(writer):
    manifest = {
        "version": 1,
        "namespace": "x",
        "collections": {
            "logical": {"source": [{"_id": "a"}], "collection": "physical", "database": "other"}
        },
        "index_profiles": {
            "baseline": {
                "mongodb": [{"collection": "logical", "name": "lookup", "keys": [["field", 1]]}]
            }
        },
    }
    result = load(manifest=manifest, indexes="baseline")
    assert result.destinations == {"other/physical": 1}
    assert writer.index_defs[0]["name"] == "lookup"
    manifest["collections"]["second"] = manifest["collections"]["logical"]
    with pytest.raises(ValueError, match="same destination"):
        load(manifest=manifest)


def test_progress_failure_keeps_partial_counts(writer):
    def callback(result):
        result.destinations.clear()  # The callback receives an independent snapshot.
        raise RuntimeError("callback stopped")

    with pytest.raises(LoadDataError) as error:
        load([{"_id": "a"}, {"_id": "b"}], batch_size=1, on_progress=callback)
    assert error.value.result.destinations == {"test/items": 1}
    assert not error.value.result.uncertain_writes


def test_huggingface_objects(writer):
    datasets = pytest.importorskip("datasets")
    data = datasets.Dataset.from_list([{"_id": "a"}], split="train")
    result = load(data)
    assert result.destinations == {"test/items_train": 1}
    split_data = datasets.DatasetDict({"test": datasets.Dataset.from_list([{"_id": "b"}])})
    result = load(split_data)
    assert result.destinations == {"test/items_test": 1}


def test_read_configured_hub_source(monkeypatch, tmp_path, writer):
    from types import SimpleNamespace

    from bondi.data import _sources

    path = tmp_path / "train.jsonl"
    path.write_text('{"value":1}\n')
    revisions = []

    class Hub:
        @staticmethod
        def HfApi():
            return SimpleNamespace(dataset_info=lambda *a, **k: SimpleNamespace(sha="pinned"))

        @staticmethod
        def hf_hub_download(*args, **kwargs):
            revisions.append(kwargs["revision"])
            return str(path)

    monkeypatch.setattr(_sources, "optional", lambda module: Hub)
    result = load("adult", split="train")
    assert result.destinations == {"test/items_train": 1}
    assert result.sources[0]["revision"] == "pinned"
    assert set(revisions) == {"pinned"}


def test_numeric_ids_do_not_depend_on_bson_width(writer):
    from bson import Int64

    assert document_key(123) == document_key(Int64(123))
    with pytest.raises(LoadDataError, match="Duplicate"):
        load([{"_id": 123}, {"_id": Int64(123)}], mode="upsert")


@pytest.mark.parametrize(
    "credentials",
    [{}, {"username": "u"}, {"password": ""}, {"username": "user@host", "password": "p@ss:/%"}],
)
def test_mongo_credentials_forwarded_without_encoding(monkeypatch, credentials):
    from unittest.mock import MagicMock

    from bondi.data._writers import MongoWriter

    client = MagicMock()
    monkeypatch.setattr("bondi.data._writers.MongoClient", client)
    target = MongoConnection(
        "mongodb://uri-user:uri-pass@localhost/?authSource=admin", **credentials
    )
    writer = MongoWriter(target)
    client.assert_called_once_with(target.uri, timeoutMS=30000, **credentials)
    assert repr(target) == "MongoConnection()"
    writer.close()
    client.return_value.close.assert_called_once()


@pytest.mark.parametrize("field", ["username", "password"])
def test_invalid_mongo_credential_type(field):
    with pytest.raises(ValueError, match="strings or None"):
        MongoConnection("mongodb://localhost", **{field: 123})


@pytest.mark.parametrize("with_password", [False, True])
def test_cli_mongo_password_env(tmp_path, monkeypatch, capsys, with_password):
    import json
    from unittest.mock import MagicMock

    from bondi._cli import main
    from bondi.data import LoadDataResult

    config = {
        "backend": "mongodb",
        "uri": "mongodb://localhost/?authSource=admin",
        "username": "user",
    }
    if with_password:
        config["password_env"] = "BONDI_TEST_PASSWORD"
    monkeypatch.setenv("BONDI_TEST_PASSWORD", "p@ss:/%")
    path = tmp_path / "connection.json"
    path.write_text(json.dumps(config))
    loader = MagicMock(return_value=LoadDataResult("mongodb"))
    monkeypatch.setattr("bondi.data._cli.load_data", loader)
    assert main(["datasets", "load", "demo", "--connection", str(path), "--database", "test"]) == 0
    target = loader.call_args.kwargs["target"]
    assert target.username == "user"
    assert target.password == ("p@ss:/%" if with_password else None)
    assert "p@ss:/%" not in capsys.readouterr().out


def test_cli_missing_mongo_password_env_fails_before_loading(tmp_path, monkeypatch, capsys):
    import json
    from unittest.mock import MagicMock

    from bondi._cli import main

    path = tmp_path / "connection.json"
    path.write_text(
        json.dumps(
            {
                "backend": "mongodb",
                "uri": "mongodb://localhost",
                "password_env": "BONDI_TEST_PASSWORD",
            }
        )
    )
    monkeypatch.delenv("BONDI_TEST_PASSWORD", raising=False)
    loader = MagicMock()
    monkeypatch.setattr("bondi.data._cli.load_data", loader)
    assert main(["datasets", "load", "demo", "--connection", str(path), "--database", "test"]) == 1
    loader.assert_not_called()
    assert "password_env" in capsys.readouterr().err


def test_generated_id_format_and_identity_inputs():
    import hashlib
    import json
    import re

    from bondi.data._values import generated_id

    parts = ["example", "items", "train", 0, 7]
    value = generated_id(*parts)
    assert re.fullmatch(r"gen:[0-9a-f]{24}", value)
    assert value == "gen:" + hashlib.sha256(json.dumps(parts).encode()).hexdigest()[:24]
    assert value == generated_id(*parts)
    for index, replacement in enumerate(["other", "users", "test", 1, 8]):
        changed = parts.copy()
        changed[index] = replacement
        assert generated_id(*changed) != value


def test_generated_id_collisions_are_rejected(writer, monkeypatch):
    monkeypatch.setattr("bondi.data._loader.generated_id", lambda *args: "gen:" + "a" * 24)
    with pytest.raises(LoadDataError, match="Duplicate incoming document ID") as error:
        load([{"v": 1}, {"v": 2}], namespace="collision-test", mode="upsert", batch_size=1)
    assert error.value.result.destinations == {"test/items": 1}


def test_cli_list_readable_and_json(capsys):
    import json

    from bondi._cli import main
    from bondi.data import list_datasets

    assert main(["datasets", "list"]) == 0
    text = capsys.readouterr().out
    assert text.startswith("Available datasets")
    assert "Source" in text and "Description" in text
    assert "Packaged with BONDI" in text
    assert "origami-ml/jsynth-data" in text
    for name in list_datasets():
        assert name in text
    assert main(["datasets", "list", "--json"]) == 0
    assert json.loads(capsys.readouterr().out) == list_datasets()


def test_cli_empty_catalogue(monkeypatch, capsys):
    from bondi._cli import main

    monkeypatch.setattr("bondi.data._cli.list_datasets", lambda: {})
    assert main(["datasets", "list"]) == 0
    assert capsys.readouterr().out == "No datasets available.\n"
    assert main(["datasets", "list", "--json"]) == 0
    assert capsys.readouterr().out == "{}\n"
