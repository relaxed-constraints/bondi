"""Dataset identity, splits, conversions and partial-write contracts."""

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from bson import ObjectId

from bondi import MongoConnection
from bondi.data import LoadDataError, load_documents, load_file
from bondi.data._values import convert, document_key
from bondi.data._writers import CouchbaseWriter, InsertBatchError
from bondi.mongodb import MongoCollectionRef


@pytest.fixture
def writer(monkeypatch):
    class MemoryWriter:
        backend = "mongodb"
        data = {}
        index_defs = []
        fail_on = None

        def __init__(self, target):
            pass

        def preflight(self, dest, quota):
            return bool(self.data.get(dest))

        def prepare(self, dest, mode):
            if mode == "replace" or dest not in self.data:
                self.data[dest] = {}

        def upsert_one(self, dest, key, document):
            if document.get("fail"):
                raise RuntimeError("secret connection details")
            self.data[dest][key] = document

        def insert_batch(self, dest, batch):
            for count, (key, document) in enumerate(batch):
                if document.get("fail"):
                    raise InsertBatchError(count, True, "write failed")
                self.data[dest][key] = document

        def indexes(self, dest, definitions):
            self.index_defs.extend(definitions)

        def close(self):
            pass

    monkeypatch.setattr("bondi.data._loader.MongoWriter", MemoryWriter)
    return MemoryWriter


def load(source, **kwargs):
    loader = load_file if isinstance(source, Path) else load_documents
    return loader(
        source,
        connection=MongoConnection("mongodb://unused"),
        collection=MongoCollectionRef("test", "items"),
        **kwargs,
    )


def test_modes_and_whole_document_upsert(writer):
    load([{"_id": "a", "old": 1}])
    with pytest.raises(LoadDataError, match="empty"):
        load([{"_id": "b"}])
    load([{"_id": "a", "new": 2}], mode="upsert")
    docs = writer.data[("test", None, "items")]
    assert list(docs.values()) == [{"_id": "a", "new": 2}]
    load([{"_id": "b"}], mode="replace")
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
    assert error.value.result.destinations["test.items"] == 1
    assert len(result) == 1
    with pytest.raises(LoadDataError) as error:
        load([{"_id": "b", "fail": True}], mode="upsert")
    assert error.value.result.uncertain_writes
    assert "secret" not in str(error.value)


@pytest.mark.parametrize("write_concern_failure", [False, True])
def test_mongo_partial_insert_counts(monkeypatch, write_concern_failure):
    from pymongo.errors import BulkWriteError

    client = MagicMock()
    collection = client["test"]["items"]
    collection.find_one.return_value = None
    collection.insert_many.side_effect = BulkWriteError(
        {
            "nInserted": 1,
            "writeErrors": [{"index": 1, "errmsg": "private details"}],
            "writeConcernErrors": [{"code": 64}] if write_concern_failure else [],
        }
    )
    monkeypatch.setattr("bondi.data._writers.MongoClient", lambda *args, **kwargs: client)

    with pytest.raises(LoadDataError, match="rows 0-2: MongoDB write") as caught:
        load([{"_id": i} for i in range(3)])

    result = caught.value.result
    assert "private" not in str(caught.value)
    assert result.uncertain_writes is write_concern_failure
    assert result.destinations == {"test.items": 0 if write_concern_failure else 1}
    assert result.source_counts == ({} if write_concern_failure else {"items:unsplit": 1})


@pytest.mark.parametrize("ambiguous", [False, True])
def test_couchbase_partial_insert_counts(monkeypatch, ambiguous):
    exceptions = pytest.importorskip("couchbase.exceptions")
    from bondi import CouchbaseConnection
    from bondi.couchbase import CouchbaseCollectionRef

    collection = MagicMock()
    error = (
        exceptions.AmbiguousTimeoutException if ambiguous else exceptions.DocumentExistsException
    )
    collection.insert_multi.return_value = SimpleNamespace(
        all_ok=False,
        results={document_key("later"): object()},
        exceptions={document_key("first"): error()},
    )
    monkeypatch.setattr(CouchbaseWriter, "__init__", lambda *args: None)
    monkeypatch.setattr(CouchbaseWriter, "preflight", lambda *args: False)
    monkeypatch.setattr(CouchbaseWriter, "prepare", lambda *args, **kwargs: None)
    monkeypatch.setattr(CouchbaseWriter, "close", lambda *args: None)
    monkeypatch.setattr(CouchbaseWriter, "_collection", lambda *args: collection)
    with pytest.raises(LoadDataError, match="Couchbase write failed") as caught:
        load_documents(
            [{"_id": "first"}, {"_id": "later"}],
            connection=CouchbaseConnection("couchbase://unused", "user", "password"),
            collection=CouchbaseCollectionRef("test", "scope", "items"),
        )

    result = caught.value.result
    assert result.destinations == {"test.scope.items": 1}
    assert result.source_counts == {"items:unsplit": 1}
    assert result.uncertain_writes is ambiguous


def test_extended_json_and_plain_wrappers(tmp_path, writer):
    path = tmp_path / "rows.jsonl"
    path.write_text('{"_id":"a","d":{"$date":"2020-01-01T00:00:00Z"}}\n')
    load(path, json_mode="plain")
    assert isinstance(next(iter(writer.data[("test", None, "items")].values()))["d"], dict)
    load(path, json_mode="extended", mode="replace")
    assert isinstance(next(iter(writer.data[("test", None, "items")].values()))["d"], datetime)


def test_formats(tmp_path, writer):
    import pyarrow as pa
    import pyarrow.parquet as pq

    paths = [tmp_path / "a.csv", tmp_path / "a.json", tmp_path / "a.parquet"]
    paths[0].write_text("_id,x\na,1\n")
    paths[1].write_text('[{"_id":"a","x":1}]')
    pq.write_table(pa.Table.from_pylist([{"_id": "a", "x": 1}]), paths[2])
    for path in paths:
        assert load(path, mode="replace").destinations["test.items"] == 1


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

    assert main(["dataset", "info", "adult"]) == 0
    assert "origami-ml/jsynth-data" in capsys.readouterr().out


def test_replace_clears_manually_populated_collection(writer):
    dest = ("test", None, "items")
    writer.data[dest] = {"old": {"_id": "old"}}
    load([{"_id": "new"}], mode="upsert")
    assert {doc["_id"] for doc in writer.data[dest].values()} == {"old", "new"}
    load([], mode="replace")
    assert writer.data[dest] == {}


@pytest.mark.parametrize("extension", ["json", "jsonl"])
def test_duplicate_json_keys_rejected(tmp_path, writer, extension):
    path = tmp_path / f"data.{extension}"
    path.write_text('{"_id":"a","nested":{"x":1,"x":2}}')
    with pytest.raises(LoadDataError, match="duplicate JSON key"):
        load(path)


def test_progress_failure_keeps_partial_counts(writer):
    def callback(result):
        result.destinations.clear()  # The callback receives an independent snapshot.
        raise RuntimeError("callback stopped")

    with pytest.raises(LoadDataError) as error:
        load([{"_id": "a"}, {"_id": "b"}], batch_size=1, on_progress=callback)
    assert error.value.result.destinations == {"test.items": 1}
    assert not error.value.result.uncertain_writes


def test_huggingface_objects(writer):
    import datasets

    data = datasets.Dataset.from_list([{"_id": "a"}], split="train")
    result = load(data)
    assert result.destinations == {"test.items": 1}


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
    with pytest.raises(TypeError, match="strings or None"):
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
    monkeypatch.setattr("bondi.data._cli.load_file", loader)
    assert (
        main(
            [
                "dataset",
                "load-file",
                "demo.jsonl",
                "--connection",
                str(path),
                "--database",
                "test",
                "--collection",
                "items",
            ]
        )
        == 0
    )
    target = loader.call_args.kwargs["connection"]
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
    monkeypatch.setattr("bondi.data._cli.load_file", loader)
    assert (
        main(
            [
                "dataset",
                "load-file",
                "demo.jsonl",
                "--connection",
                str(path),
                "--database",
                "test",
                "--collection",
                "items",
            ]
        )
        == 1
    )
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
    assert error.value.result.destinations == {"test.items": 1}


def test_cli_list_readable_and_json(capsys):
    import json

    from bondi._cli import main
    from bondi.data import list_datasets

    assert main(["dataset", "list"]) == 0
    text = capsys.readouterr().out
    assert text.startswith("Available datasets")
    assert "Source" in text and "Description" in text
    assert "origami-ml/jsynth-data" in text
    for name in list_datasets():
        assert name in text
    assert main(["dataset", "list", "--json"]) == 0
    assert json.loads(capsys.readouterr().out) == list_datasets()


def test_cli_empty_catalogue(monkeypatch, capsys):
    from bondi._cli import main

    monkeypatch.setattr("bondi.data._cli.list_datasets", lambda: {})
    assert main(["dataset", "list"]) == 0
    assert capsys.readouterr().out == "No datasets available.\n"
    assert main(["dataset", "list", "--json"]) == 0
    assert capsys.readouterr().out == "{}\n"


def test_cli_missing_database_message(monkeypatch, capsys):
    from unittest.mock import Mock

    from bondi._cli import main

    monkeypatch.setattr(
        "bondi.deployment.get_deployment",
        lambda name: SimpleNamespace(connection=MongoConnection("mongodb://unused")),
    )
    constructor = Mock()
    monkeypatch.setattr("bondi.data._loader.MongoWriter", constructor)
    assert (
        main(
            [
                "dataset",
                "load-file",
                "adult.jsonl",
                "--deployment",
                "notebook-datasets",
                "--collection",
                "adult",
            ]
        )
        == 1
    )
    output = capsys.readouterr()
    assert not output.out
    assert "MongoDB requires a destination database" in output.err
    assert "--database NAME" in output.err
    constructor.assert_not_called()


@pytest.fixture
def hub(monkeypatch):
    from types import SimpleNamespace

    from bondi.data import _sources

    data = {
        "users": {"train": [{"value": 1}], "test": [{"value": 2}]},
        "posts": {"train": [{"value": 3}], "test": [{"value": 4}]},
    }
    calls = []
    resolutions = []

    def resolve(repo, revision):
        resolutions.append((repo, revision))
        return SimpleNamespace(sha="fixed-commit", card_data=None)

    def rows(repo, *, name, revision, split, streaming):
        calls.append((name, revision, split, streaming))
        return iter(data[name][split])

    library = SimpleNamespace(
        get_dataset_config_names=lambda *a, **k: list(data),
        get_dataset_split_names=lambda repo, config, **k: list(data[config]),
        load_dataset_builder=lambda *a, **k: SimpleNamespace(config=SimpleNamespace()),
        load_dataset=rows,
    )
    api = SimpleNamespace(HfApi=lambda: SimpleNamespace(dataset_info=resolve))
    monkeypatch.setattr(
        _sources, "import_module", lambda module: api if module == "huggingface_hub" else library
    )
    return data, calls, resolutions


@pytest.mark.parametrize("streaming", [False, True])
def test_hf_combines_splits_into_exact_destination(writer, hub, streaming):
    from bondi.data import load_hf_dataset

    result = load_hf_dataset(
        "org/forum",
        dataset="users",
        connection=MongoConnection("x"),
        collection=MongoCollectionRef("test", "chosen"),
        streaming=streaming,
    )
    assert result.destinations == {"test.chosen": 2}
    assert result.source_counts == {"users:test": 1, "users:train": 1}
    assert all(source["revision"] == "fixed-commit" for source in result.sources)
    assert {row[1] for row in hub[1]} == {"fixed-commit"}
    assert len(hub[2]) == 1
    assert all(call[3] is streaming for call in hub[1])
    before = dict(writer.data[("test", None, "chosen")])
    load_hf_dataset(
        "org/forum",
        dataset="users",
        split="train",
        connection=MongoConnection("x"),
        collection=MongoCollectionRef("test", "chosen"),
        streaming=streaming,
        mode="replace",
    )
    after = writer.data[("test", None, "chosen")]
    assert len(after) == 1 and set(after) <= set(before)


def test_hf_selection_errors_before_writes(writer, hub):
    from bondi.data import load_hf_dataset, load_hf_repository

    kwargs = dict(connection=MongoConnection("x"), collection=MongoCollectionRef("db", "c"))
    with pytest.raises(ValueError, match="Specify dataset"):
        load_hf_dataset("org/forum", **kwargs)
    with pytest.raises(ValueError, match="Unknown dataset"):
        load_hf_dataset("org/forum", dataset="missing", **kwargs)
    with pytest.raises(ValueError, match="absent"):
        load_hf_dataset("org/forum", dataset="users", split="validation", **kwargs)
    hub[0]["users"].pop("train")
    with pytest.raises(ValueError, match="absent"):
        load_hf_repository(
            "org/forum", connection=MongoConnection("x"), database="db", split="train"
        )
    assert writer.data == {}


def test_hf_repository_names_revision_and_partial_failure(writer, hub):
    from bondi.data import load_hf_repository

    result = load_hf_repository("org/forum", connection=MongoConnection("x"), database="db")
    assert list(result) == ["posts", "users"]
    assert result["users"].destinations == {"db.users": 2}
    assert len(hub[2]) == 1
    assert {call[1] for call in hub[1]} == {"fixed-commit"}
    hub[0]["users"]["train"] = [{"fail": True}]
    with pytest.raises(LoadDataError) as error:
        load_hf_repository(
            "org/forum", connection=MongoConnection("x"), database="db", mode="replace"
        )
    assert error.value.result.destinations["db.posts"] == 2
    assert error.value.result.destinations["db.users"] == 1
    assert error.value.result.uncertain_writes


def test_hf_duplicate_ids_across_splits(writer, hub):
    from bondi.data import load_hf_dataset

    hub[0]["users"] = {"train": [{"_id": "same"}], "test": [{"_id": "same"}]}
    with pytest.raises(LoadDataError, match="Duplicate"):
        load_hf_dataset(
            "org/forum",
            dataset="users",
            connection=MongoConnection("x"),
            collection=MongoCollectionRef("db", "c"),
        )


def test_hf_single_config_and_invalid_repository_names(writer, hub):
    from bondi.data import load_hf_dataset, load_hf_repository

    hub[0].pop("posts")
    assert load_hf_dataset(
        "org/forum", connection=MongoConnection("x"), collection=MongoCollectionRef("db", "c")
    ).destinations == {"db.c": 2}
    hub[0]["bad/name"] = hub[0]["users"]
    before = dict(writer.data)
    with pytest.raises(ValueError, match="Destination names"):
        load_hf_repository("org/forum", connection=MongoConnection("x"), database="db")
    assert writer.data == before


def test_collection_refs_and_old_interface_removed(writer):
    import bondi.data
    from bondi.couchbase import CouchbaseCollectionRef

    ref = CouchbaseCollectionRef("bucket", "_default", "items")
    assert ref == CouchbaseCollectionRef("bucket", "_default", "items")
    assert len({ref, ref}) == 1
    with pytest.raises(ValueError):
        CouchbaseCollectionRef("", "_default", "items")
    with pytest.raises(TypeError, match="connection backend"):
        load_documents([], connection=MongoConnection("x"), collection=ref)
    with pytest.raises(TypeError, match="iterable"):
        load_documents(
            {"items": []}, connection=MongoConnection("x"), collection=MongoCollectionRef("db", "c")
        )
    assert not hasattr(bondi.data, "load_data")
    with pytest.raises(TypeError):
        load([], manifest={})


def test_extended_json_documents(writer):
    load([{"_id": "a", "date": {"$date": "2020-01-01T00:00:00Z"}}], json_mode="extended")
    assert isinstance(next(iter(writer.data[("test", None, "items")].values()))["date"], datetime)


@pytest.mark.parametrize("command", ["load-hf", "load-hf-repository"])
@pytest.mark.parametrize("streaming", [False, True])
def test_cli_hf_dispatch(writer, hub, monkeypatch, capsys, command, streaming):
    import json

    from bondi._cli import main

    monkeypatch.setattr(
        "bondi.deployment.get_deployment",
        lambda name: SimpleNamespace(connection=MongoConnection("mongodb://unused")),
    )
    args = ["dataset", command, "org/forum", "--deployment", "db", "--database", "demo"]
    if command == "load-hf":
        args += ["--dataset", "users", "--collection", "exact", "--split", "train"]
    if streaming:
        args += ["--streaming"]
    assert main(args) == 0
    assert all(call[3] is streaming for call in hub[1])
    payload = json.loads(capsys.readouterr().out)
    if command == "load-hf":
        assert payload["destinations"] == {"demo.exact": 1}
    else:
        assert set(payload) == {"users", "posts"}
        assert payload["users"]["destinations"] == {"demo.users": 2}


def test_cli_couchbase_ref_and_options(monkeypatch, capsys):
    from unittest.mock import Mock

    from bondi import CouchbaseConnection
    from bondi._cli import main
    from bondi.couchbase import CouchbaseCollectionRef
    from bondi.data import LoadDataResult

    target = CouchbaseConnection("couchbase://unused", "u", "p")
    monkeypatch.setattr(
        "bondi.deployment.get_deployment", lambda name: SimpleNamespace(connection=target)
    )
    loader = Mock(return_value=LoadDataResult("couchbase"))
    monkeypatch.setattr("bondi.data._cli.load_file", loader)
    assert (
        main(
            [
                "dataset",
                "load-file",
                "input.jsonl",
                "--deployment",
                "db",
                "--bucket",
                "b",
                "--scope",
                "s",
                "--collection",
                "c",
                "--bucket-memory-mb",
                "256",
                "--json-mode",
                "extended",
                "--id-field",
                "key",
            ]
        )
        == 0
    )
    assert loader.call_args.kwargs["collection"] == CouchbaseCollectionRef("b", "s", "c")
    assert loader.call_args.kwargs["bucket_memory_mb"] == 256
    assert loader.call_args.kwargs["json_mode"] == "extended"
    assert loader.call_args.kwargs["id_field"] == "key"


@pytest.mark.parametrize("option", ["--manifest", "--splits", "--indexes", "--allow-unowned"])
def test_removed_cli_options_rejected(option):
    from click.testing import CliRunner

    from bondi._cli import cli

    result = CliRunner().invoke(
        cli,
        [
            "dataset",
            "load-file",
            "data.jsonl",
            "--collection",
            "c",
            option,
            "x",
        ],
    )
    assert result.exit_code == 2
    assert "No such option" in result.output


def test_extended_wrappers_do_not_relax_native_datetime_policy(writer):
    with pytest.raises(LoadDataError, match="naive datetime"):
        load(
            [
                {
                    "_id": "a",
                    "native": datetime(2020, 1, 1),
                    "wrapper": {"$date": "2020-01-01T00:00:00Z"},
                }
            ],
            json_mode="extended",
        )
    load(
        [
            {
                "_id": "a",
                "native": datetime(2020, 1, 1),
                "wrapper": {"$date": "2020-01-01T00:00:00Z"},
            }
        ],
        json_mode="extended",
        naive_datetimes="utc",
    )
    row = next(iter(writer.data[("test", None, "items")].values()))
    assert row["native"] == row["wrapper"]


def test_couchbase_destination_labels_in_progress_and_errors(writer, monkeypatch):
    from bondi import CouchbaseConnection
    from bondi.couchbase import CouchbaseCollectionRef

    class FakeCouchbaseWriter(writer):
        def prepare(self, dest, mode, quota=None):
            super().prepare(dest, mode)

    monkeypatch.setattr("bondi.data._loader.CouchbaseWriter", FakeCouchbaseWriter)
    progress = []
    with pytest.raises(LoadDataError) as error:
        load_documents(
            [{"_id": "a"}, {"_id": "b", "fail": True}],
            connection=CouchbaseConnection("couchbase://unused", "user", "password"),
            collection=CouchbaseCollectionRef("bucket", "scope", "items"),
            batch_size=1,
            on_progress=progress.append,
        )
    assert progress[0].destinations == {"bucket.scope.items": 1}
    assert error.value.result.destinations == {"bucket.scope.items": 1}


@pytest.mark.parametrize(
    ("tagged", "mode", "effective"),
    [
        (True, None, "extended"),
        (True, "auto", "extended"),
        (True, "plain", "plain"),
        (False, None, "plain"),
        (False, "extended", "extended"),
    ],
)
@pytest.mark.parametrize("streaming", [False, True])
@pytest.mark.parametrize("compressed", [False, True])
def test_hf_jsonl_preserves_missing_null_and_extended_types(
    writer, hub, monkeypatch, tmp_path, tagged, mode, effective, streaming, compressed
):
    from io import StringIO
    from types import SimpleNamespace

    from bson.int64 import Int64

    from bondi.data import _sources, load_hf_repository

    library = _sources.import_module("datasets")
    api = _sources.import_module("huggingface_hub")
    filename = "data/users.jsonl.gz" if compressed else "data/users.jsonl"
    path = f"hf://datasets/org/forum@fixed-commit/{filename}"
    rows = (
        '{"_id":"missing","when":{"$date":"2024-01-02T03:04:05Z"}}\n'
        '{"_id":"null","optional":null,"count":{"$numberLong":"9007199254740993"}}\n'
    )
    library.load_dataset_builder = lambda *a, **k: SimpleNamespace(
        config=SimpleNamespace(data_files={"train": [path]})
    )

    def open_file(filename, mode, **options):
        assert filename == path
        assert mode == "rt"
        return StringIO(rows)

    import gzip
    from unittest.mock import Mock

    # Cache paths need not retain the source extension.
    cached = tmp_path / "cached-blob"
    cached.write_bytes(gzip.compress(rows.encode()) if compressed else rows.encode())
    download = Mock(return_value=str(cached))
    remote_open = Mock(side_effect=open_file)
    resolve = Mock(
        return_value=SimpleNamespace(
            repo_id="org/forum",
            repo_type="dataset",
            revision="fixed-commit",
            path_in_repo=filename,
        )
    )
    monkeypatch.setattr(api, "hf_hub_download", download, raising=False)
    monkeypatch.setattr(
        api,
        "HfFileSystem",
        lambda: SimpleNamespace(open=remote_open, resolve_path=resolve),
        raising=False,
    )
    monkeypatch.setattr(library, "get_dataset_config_names", lambda *a, **k: ["users"])
    api.HfApi = lambda: SimpleNamespace(
        dataset_info=lambda *a, **k: SimpleNamespace(
            sha="fixed-commit", card_data={"tags": ["mongodb-extended-json"]} if tagged else None
        )
    )
    options = {} if mode is None else {"json_mode": mode}
    result = load_hf_repository(
        "org/forum",
        connection=MongoConnection("x"),
        database="db",
        split="train",
        streaming=streaming,
        **options,
    )
    if streaming:
        download.assert_not_called()
        resolve.assert_not_called()
        remote_open.assert_called_once()
    else:
        remote_open.assert_not_called()
        resolve.assert_called_once_with(path)
        download.assert_called_once_with(
            repo_id="org/forum", filename=filename, repo_type="dataset", revision="fixed-commit"
        )
    assert result["users"].settings["json_mode"] == effective
    docs = {row["_id"]: row for row in writer.data[("db", None, "users")].values()}
    assert "optional" not in docs["missing"]
    assert docs["null"]["optional"] is None
    if effective == "extended":
        assert docs["missing"]["when"].isoformat() == "2024-01-02T03:04:05+00:00"
        assert isinstance(docs["null"]["count"], Int64)
        assert docs["null"]["count"] == 9007199254740993
    else:
        assert docs["missing"]["when"] == {"$date": "2024-01-02T03:04:05Z"}
        assert docs["null"]["count"] == {"$numberLong": "9007199254740993"}
