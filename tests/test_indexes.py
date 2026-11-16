"""Reusable definitions, strict persistence and backend creation contracts."""

import json
from contextlib import contextmanager
from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest
from bson import Int64, ObjectId

from bondi import (
    CouchbaseConnection,
    FieldIndex,
    IndexCreationError,
    IndexSet,
    MongoConnection,
    load_index,
)
from bondi import _index_creation as creation
from bondi.couchbase import CouchbaseCollectionRef, CouchbaseIndex
from bondi.couchbase import create_couchbase_index as cb_create
from bondi.couchbase import create_couchbase_indexes as cb_many
from bondi.mongodb import MongoCollectionRef, MongoIndex
from bondi.mongodb import create_mongo_index as create_index
from bondi.mongodb import create_mongo_indexes as create_indexes


@pytest.mark.parametrize(
    "index",
    [
        FieldIndex((("customer_id", 1), ("created_at", -1))),
        MongoIndex((("email", 1),), unique=True),
        MongoIndex(
            (("x", 1),),
            partial_filter={
                "id": ObjectId(),
                "n": Int64(4),
                "time": datetime(2026, 1, 1),
            },
        ),
        CouchbaseIndex(
            (("DISTINCT ARRAY x FOR x IN `tags` END", 1),),
            condition="`active` = TRUE",
            include_missing=True,
        ),
    ],
)
def test_definition_roundtrip(index, tmp_path):
    path = tmp_path / "index.json"
    index.save(path)
    assert load_index(path) == index
    assert type(index).load(path) == index
    assert type(index).from_dict(index.to_dict()) == index
    assert index.resolved_name == load_index(path).resolved_name
    other = MongoIndex if type(index) is FieldIndex else FieldIndex
    with pytest.raises(ValueError):
        other.load(path)


def test_bson_and_copy_boundaries(tmp_path):
    predicate = {"n": {"$gt": Int64(2)}, "date": datetime(2026, 1, 1, tzinfo=UTC)}
    index = MongoIndex((("n", 1),), partial_filter=predicate)
    predicate["n"]["$gt"] = 9
    assert index.partial_filter["n"]["$gt"] == 2
    index.save(tmp_path / "mongo.json")
    restored = MongoIndex.load(tmp_path / "mongo.json")
    assert isinstance(restored.partial_filter["n"]["$gt"], Int64)
    assert restored.partial_filter["date"] == datetime(2026, 1, 1)
    data = index.to_dict()
    data["partial_filter"].clear()
    assert index.partial_filter


def test_index_set_shorthand_order_and_mixed_roundtrip(tmp_path):
    config = {
        "inventory": [{"fields": ["brandId"]}, {"fields": ["locationId"]}],
        "transactions": [{"keys": [["customerId", 1], ["created_at", -1]]}],
    }
    indexes = IndexSet.from_dict(config)
    config["inventory"][0]["fields"].clear()
    assert indexes["inventory"][0].keys == (("brandId", 1),)
    indexes["transactions"].append(CouchbaseIndex((("LOWER(email)", 1),)))
    indexes["transactions"].append(MongoIndex((("email", 1),), unique=True))
    indexes.save(tmp_path / "indexes.json")
    restored = IndexSet.load(tmp_path / "indexes.json")
    assert restored.to_dict() == indexes.to_dict()
    assert list(restored) == ["inventory", "transactions"]
    assert len(restored) == 2
    assert IndexSet.from_dict({}).to_dict() == {}
    copied = IndexSet(indexes)
    indexes["inventory"].clear()
    assert len(copied["inventory"]) == 2


@pytest.mark.parametrize(
    "data",
    [
        {"fields": ["x"], "keys": [["y", 1]]},
        {"fields": []},
        {"keys": [["x", True]]},
        {"keys": [["x", 0]]},
        {"keys": [["x", 1], ["x", -1]]},
        {"fields": ["a..b"]},
        {"kind": "future", "fields": ["x"]},
        {"kind": [], "keys": []},
        {"fields": ["x"], "typo": True},
        {"kind": "mongodb", "fields": ["x"]},
        {"kind": "mongodb", "keys": [["x", 1]], "unique": 1},
        {"kind": "mongodb", "keys": [["x", 1]], "sparse": True, "partial_filter": {}},
        {"kind": "couchbase", "keys": [["x", 1]], "include_missing": 1},
        {"kind": "couchbase", "keys": [["x", 1]], "condition": ""},
    ],
)
def test_reject_bad_configs(data):
    with pytest.raises((ValueError, TypeError)):
        IndexSet.from_dict({"things": [data]})


def test_mutation_validation_names_and_versions(tmp_path):
    index = FieldIndex((("x", 1),), name="same")
    with pytest.raises(ValueError, match="Duplicate"):
        IndexSet({"t": [index, index]})
    index.keys = (("x", False),)
    with pytest.raises(ValueError):
        index.save(tmp_path / "bad.json")
    for version in [None, True, 2]:
        path = tmp_path / "bad.json"
        path.write_text(
            json.dumps({"format_version": version, "kind": "field", "keys": [["x", 1]]})
        )
        with pytest.raises(ValueError):
            load_index(path)


@pytest.fixture
def client(monkeypatch):
    client = MagicMock()
    calls = []

    @contextmanager
    def open_client(backend, conn, timeout):
        calls.append((backend, conn, timeout))
        try:
            yield client
        finally:
            client.close()

    monkeypatch.setattr(creation, "_client", open_client)
    client.open_calls = calls
    return client


def test_mongo_native_model_and_single_return(client):
    collection = client["db"]["c"]
    collection.create_indexes.return_value = ["email"]
    name = create_index(
        MongoConnection("mongodb://example"),
        target=MongoCollectionRef("db", "c"),
        index=MongoIndex(
            (("email", -1),), name="email", unique=True, partial_filter={"active": True}
        ),
    )
    assert name == "email"
    model = collection.create_indexes.call_args.args[0][0].document
    assert list(model["key"].items()) == [("email", -1)]
    assert model["unique"] and model["partialFilterExpression"] == {"active": True}
    client.close.assert_called_once()


def test_builtin_id_reuse_and_conflicts(client):
    collection = client["db"]["c"]
    collection.index_information.return_value = {"_id_": {"key": [("_id", 1)]}}
    assert (
        create_index(
            MongoConnection("mongodb://example"),
            target=MongoCollectionRef("db", "c"),
            index=FieldIndex((("_id", 1),)),
        )
        == "_id_"
    )
    collection.create_indexes.assert_not_called()
    with pytest.raises(ValueError):
        create_index(
            MongoConnection("mongodb://example"),
            target=MongoCollectionRef("db", "c"),
            index=FieldIndex((("_id", 1),), name="other"),
        )
    assert len(client.open_calls) == 1


def test_batch_reuses_client_and_reports_partial_failure(client):
    indexes = IndexSet.from_dict(
        {"one": [{"fields": ["a"]}], "two": [{"fields": ["b"]}, {"fields": ["c"]}]}
    )
    client["db"]["one"].create_indexes.side_effect = [["a"], ["b"], RuntimeError("server failed")]
    with pytest.raises(IndexCreationError) as caught:
        create_indexes(
            MongoConnection("mongodb://example"),
            indexes=indexes,
            database="db",
        )
    assert caught.value.completed == {"one": ["a"], "two": ["b"]}
    assert (caught.value.target, caught.value.position) == ("two", 1)
    assert str(caught.value.__cause__) == "server failed"
    assert len(client.open_calls) == 1
    client.close.assert_called_once()


def test_batch_preflight_and_empty_set_do_not_connect(client):
    indexes = IndexSet({"t": [FieldIndex((("x", 1),)), CouchbaseIndex((("y", 1),))]})
    with pytest.raises(TypeError):
        create_indexes(
            MongoConnection("mongodb://example"),
            indexes=indexes,
            database="db",
        )
    with pytest.raises(ValueError):
        create_indexes(
            MongoConnection("mongodb://example"), indexes=IndexSet({"t": []}), database=""
        )
    assert (
        create_indexes(MongoConnection("mongodb://example"), indexes=IndexSet({}), database="db")
        == {}
    )
    assert not client.open_calls


def test_couchbase_ddl_paths_expressions_and_wait(client):
    pytest.importorskip("couchbase")
    conn = CouchbaseConnection("couchbase://example", "u", "p")
    target = CouchbaseCollectionRef("buck`et", "scope", "things")
    shared = FieldIndex((("item.brandId", -1),), name="brand`index")
    assert cb_create(conn, target=target, index=shared) == "brand`index"
    ddl = client.query.call_args.args[0]
    assert "`buck``et`.`scope`.`things`" in ddl
    assert "`brand``index`" in ddl and "(`item`.`brandId` DESC)" in ddl
    client.query.return_value.execute.assert_called_once()
    manager = client.bucket.return_value.scope.return_value.collection.return_value.query_indexes()
    assert manager.watch_indexes.call_args.args == (["brand`index"],)
    assert 0 < manager.watch_indexes.call_args.kwargs["timeout"].total_seconds() <= 300

    native = CouchbaseIndex(
        (("DISTINCT ARRAY t FOR t IN `tags` END", 1),),
        condition="`active` = TRUE",
        include_missing=True,
    )
    cb_create(conn, target=target, index=native)
    ddl = client.query.call_args.args[0]
    assert "END ASC INCLUDE MISSING" in ddl
    assert 'WHERE `active` = TRUE WITH {"defer_build": false}' in ddl


def test_wrong_connection_and_nonfinite_timeout(client):
    for timeout in [True, 0, float("inf"), float("nan")]:
        with pytest.raises((TypeError, ValueError)):
            create_index(
                MongoConnection("mongodb://example"),
                target=MongoCollectionRef("db", "c"),
                index=FieldIndex((("x", 1),)),
                timeout=timeout,
            )
    with pytest.raises(TypeError):
        cb_many(MongoConnection("mongodb://example"), indexes=IndexSet({}), bucket="b", scope="s")
    assert not client.open_calls


def test_strict_file_envelopes(tmp_path):
    for payload in [
        {"format_version": 1, "keys": [["x", 1]]},
        {"format_version": 1, "kind": "field", "keys": [["x", 1]], "unexpected": 1},
        {"format_version": 1, "kind": "index_set", "indexes": {}, "unexpected": 1},
    ]:
        path = tmp_path / "bad.json"
        path.write_text(json.dumps(payload))
        loader = IndexSet.load if payload.get("kind") == "index_set" else load_index
        with pytest.raises(ValueError):
            loader(path)


def test_generated_name_collision_and_mutated_batch_preflight(client):
    index = FieldIndex((("x", 1),))
    other = FieldIndex((("y", 1),), name=index.resolved_name)
    indexes = IndexSet({"t": [index, other]})
    with pytest.raises(ValueError, match="Duplicate resolved"):
        create_indexes(
            MongoConnection("mongodb://example"),
            indexes=indexes,
            database="db",
        )
    indexes["t"][1].keys = (("y", 7),)
    with pytest.raises(ValueError):
        create_indexes(
            MongoConnection("mongodb://example"),
            indexes=indexes,
            database="db",
        )
    assert not client.open_calls


def test_connection_reexports_and_deployment_credentials(tmp_path):
    from bondi.connection import normalize_connection
    from bondi.data import MongoConnection as DataMongoConnection
    from bondi.deployment import Deployment

    assert DataMongoConnection is MongoConnection
    deployment = Deployment(
        "test", 27019, "mongo:8.0.16", tmp_path, "test", username="researcher", password="secret"
    )
    conn = normalize_connection(deployment)
    assert conn.uri == deployment.uri
    assert (conn.username, conn.password) == ("researcher", "secret")
    assert "secret" not in repr(conn)


def test_owned_mongo_client_closes_on_failure(monkeypatch):
    fake = MagicMock()
    fake["db"]["c"].create_indexes.side_effect = RuntimeError("failed")
    constructor = MagicMock(return_value=fake)
    monkeypatch.setattr(creation, "MongoClient", constructor)
    with pytest.raises(RuntimeError, match="failed"):
        create_index(
            MongoConnection("mongodb://example", username="u", password="p"),
            target=MongoCollectionRef("db", "c"),
            index=FieldIndex((("x", 1),)),
        )
    fake.close.assert_called_once()
    assert constructor.call_args.kwargs["username"] == "u"
    assert constructor.call_args.kwargs["password"] == "p"


@pytest.mark.parametrize("backend", ["mongodb", "couchbase"])
def test_batch_collection_names_resolve_within_namespace(client, monkeypatch, backend):
    calls = []

    def create(backend, client, target, index, timeout):
        calls.append(target)
        return index.resolved_name

    monkeypatch.setattr(creation, "_create", create)
    indexes = IndexSet.from_dict(
        {"inventory": [{"fields": ["brandId"]}], "transactions": [{"fields": ["customerId"]}]}
    )
    if backend == "mongodb":
        result = create_indexes(
            MongoConnection("mongodb://example"), indexes=indexes, database="beer_factory"
        )
        expected = [MongoCollectionRef("beer_factory", name) for name in indexes]
    else:
        result = cb_many(
            CouchbaseConnection("couchbase://example", "u", "p"),
            indexes=indexes,
            bucket="research",
            scope="beer_factory",
        )
        expected = [CouchbaseCollectionRef("research", "beer_factory", name) for name in indexes]
    assert calls == expected
    assert list(result) == ["inventory", "transactions"]
    assert all(len(names) == 1 for names in result.values())
    assert len(client.open_calls) == 1


@pytest.mark.parametrize("bucket,scope", [("", "s"), ("b", ""), ("b", None)])
def test_empty_couchbase_batch_still_validates_namespace(client, bucket, scope):
    with pytest.raises((TypeError, ValueError)):
        cb_many(
            CouchbaseConnection("couchbase://example", "u", "p"),
            indexes=IndexSet({}),
            bucket=bucket,
            scope=scope,
        )
    assert not client.open_calls


@pytest.mark.parametrize("field", ["Model Year", "item.Model Year", " café ", "a`b", "123"])
def test_shared_field_names_preserved_and_escaped(field, tmp_path):
    index = FieldIndex(((field, 1),))
    path = tmp_path / "index.json"
    index.save(path)
    assert FieldIndex.load(path) == index
    assert list(creation._mongo_model(index).document["key"].items()) == [(field, 1)]
    quoted = ".".join("`" + part.replace("`", "``") + "`" for part in field.split("."))
    statement = creation._couchbase_statement(CouchbaseCollectionRef("b", "s", "c"), index)
    assert f"({quoted} ASC)" in statement


@pytest.mark.parametrize("field", ["", ".year", "year.", "item..year", "Model\0Year"])
def test_shared_field_paths_reject_empty_segments_and_nulls(field):
    with pytest.raises(ValueError):
        FieldIndex(((field, 1),))
