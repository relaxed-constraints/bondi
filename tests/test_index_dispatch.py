"""Backend selection, namespace validation and unchanged lifecycle results."""

from unittest.mock import MagicMock

import pytest

import bondi
from bondi import CouchbaseConnection, FieldIndex, IndexSet, MongoConnection, couchbase, mongodb
from bondi import _index_creation as core
from bondi.deployment import Deployment


@pytest.mark.parametrize("backend", ["mongodb", "couchbase"])
@pytest.mark.parametrize("managed", [False, True])
@pytest.mark.parametrize(
    "action", ["create_index", "create_indexes", "remove_index", "remove_indexes"]
)
def test_dispatch_preserves_arguments_results_and_errors(
    backend, managed, action, tmp_path, monkeypatch
):
    module = mongodb if backend == "mongodb" else couchbase
    prefix = "mongo" if backend == "mongodb" else "couchbase"
    native_name = action.replace("_", f"_{prefix}_", 1)
    native = MagicMock(return_value=object())
    monkeypatch.setattr(module, native_name, native)
    connection = (
        MongoConnection("mongodb://example", "u", "p")
        if backend == "mongodb"
        else CouchbaseConnection("couchbase://example", "u", "p")
    )
    if managed:
        connection = Deployment(
            "dispatch",
            27019,
            "test:1",
            tmp_path,
            "project",
            backend=backend,
            username="u",
            password="p",
        ).connection
    target = (
        mongodb.MongoCollectionRef("db", "c")
        if backend == "mongodb"
        else couchbase.CouchbaseCollectionRef("b", "s", "c")
    )
    index = FieldIndex((("x", 1),))
    args = {"timeout": 12}
    if action.endswith("indexes"):
        args["indexes"] = IndexSet({"c": [index]})
        args.update({"database": "db"} if backend == "mongodb" else {"bucket": "b", "scope": "s"})
        if action == "create_indexes":
            args["replace"] = True
    else:
        args.update(collection=target, index=index)
    operation = getattr(bondi, action)
    assert operation(connection, **args) is native.return_value
    assert native.call_args.kwargs == args
    resolved = native.call_args.args[0]
    assert isinstance(resolved, MongoConnection if backend == "mongodb" else CouchbaseConnection)
    assert (resolved.username, resolved.password) == ("u", "p")
    failure = RuntimeError("backend failure")
    native.side_effect = failure
    with pytest.raises(RuntimeError) as caught:
        operation(connection, **args)
    assert caught.value is failure


@pytest.mark.parametrize("action", [bondi.create_indexes, bondi.remove_indexes])
@pytest.mark.parametrize(
    "conn,namespace",
    [
        (MongoConnection("mongodb://x"), {}),
        (MongoConnection("mongodb://x"), {"database": "db", "scope": "s"}),
        (MongoConnection("mongodb://x"), {"database": "db", "bucket": "b"}),
        (CouchbaseConnection("couchbase://x", "u", "p"), {"bucket": "b"}),
        (CouchbaseConnection("couchbase://x", "u", "p"), {"scope": "s"}),
        (
            CouchbaseConnection("couchbase://x", "u", "p"),
            {"database": "db", "bucket": "b", "scope": "s"},
        ),
    ],
)
def test_invalid_namespace_never_connects(action, conn, namespace, monkeypatch):
    client = MagicMock()
    monkeypatch.setattr(core, "_client", client)
    with pytest.raises(ValueError):
        action(conn, indexes=IndexSet({}), **namespace)
    client.assert_not_called()


@pytest.mark.parametrize("action", [bondi.create_index, bondi.remove_index])
def test_mismatched_target_never_connects(action, monkeypatch):
    client = MagicMock()
    monkeypatch.setattr(core, "_client", client)
    with pytest.raises(TypeError, match="collection"):
        action(
            MongoConnection("mongodb://x"),
            collection=couchbase.CouchbaseCollectionRef("b", "s", "c"),
            index=FieldIndex((("x", 1),)),
        )
    client.assert_not_called()


def test_backend_modules_have_no_compatibility_aliases():
    for module in [mongodb, couchbase]:
        for name in ["create_index", "create_indexes", "remove_index", "remove_indexes"]:
            assert not hasattr(module, name)


def test_unsupported_connection_is_rejected():
    with pytest.raises(TypeError, match="Expected MongoConnection"):
        bondi.create_indexes("mongodb://x", indexes=IndexSet({}), database="db")
