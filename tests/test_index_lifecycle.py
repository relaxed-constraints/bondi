"""Replacement scope, protected indexes, repeatable removal and partial progress."""

from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from pymongo.errors import OperationFailure

from bondi import (
    CouchbaseConnection,
    FieldIndex,
    IndexCreationError,
    IndexRemovalError,
    IndexSet,
    MongoConnection,
)
from bondi import _index_creation as core
from bondi import couchbase as cb
from bondi import mongodb as mongo


def definition(name):
    return FieldIndex((("field", 1),), name=name)


@pytest.fixture(params=["mongodb", "couchbase"])
def env(request, monkeypatch):
    backend = request.param
    module = mongo if backend == "mongodb" else cb
    conn = (
        MongoConnection("mongodb://example")
        if backend == "mongodb"
        else CouchbaseConnection("couchbase://example", "user", "password")
    )
    namespace = {"database": "db"} if backend == "mongodb" else {"bucket": "b", "scope": "s"}
    target = (
        mongo.MongoCollectionRef("db", "one")
        if backend == "mongodb"
        else cb.CouchbaseCollectionRef("b", "s", "one")
    )
    client = MagicMock()
    opened, events = [], []
    primary = "_id_" if backend == "mongodb" else "custom_primary"
    state = {
        "one": {primary: True, "old": False, "external": False},
        "two": {primary: True, "other": False},
        "untouched": {"keep": False},
    }

    @contextmanager
    def owned(*args):
        opened.append(args)
        try:
            yield client
        finally:
            client.close()

    def existing(backend, client, target, timeout):
        events.append(("inspect", target.collection))
        return dict(state[target.collection])

    def drop(backend, client, target, name, timeout):
        events.append(("drop", target.collection, name))
        return state[target.collection].pop(name, None) is not None

    def create(backend, client, target, index, timeout):
        events.append(("create", target.collection, index.resolved_name))
        state[target.collection][index.resolved_name] = False
        return index.resolved_name

    monkeypatch.setattr(core, "_client", owned)
    monkeypatch.setattr(core, "_existing", existing)
    monkeypatch.setattr(core, "_drop", drop)
    monkeypatch.setattr(core, "_create", create)
    return SimpleNamespace(**locals())


def test_replace_clears_included_collections_including_empty_lists(env):
    e = env
    indexes = IndexSet({"one": [definition("new")], "two": []})
    result = e.module.create_indexes(e.conn, indexes=indexes, replace=True, **e.namespace)
    assert result == {"one": ["new"], "two": []}
    assert e.state == {
        "one": {e.primary: True, "new": False},
        "two": {e.primary: True},
        "untouched": {"keep": False},
    }
    assert e.events[:2] == [("inspect", "one"), ("inspect", "two")]
    assert e.events[-1] == ("create", "one", "new")
    assert len(e.opened) == 1
    e.client.close.assert_called_once()


def test_default_creation_does_not_remove_indexes(env):
    e = env
    e.module.create_indexes(e.conn, indexes=IndexSet({"one": [definition("new")]}), **e.namespace)
    assert set(e.state["one"]) == {e.primary, "old", "external", "new"}
    assert e.events == [("create", "one", "new")]


def test_empty_set_is_noop_but_empty_collection_clears(env):
    e = env
    assert e.module.create_indexes(e.conn, indexes=IndexSet({}), replace=True, **e.namespace) == {}
    assert not e.opened
    e.module.create_indexes(e.conn, indexes=IndexSet({"one": []}), replace=True, **e.namespace)
    assert e.state["one"] == {e.primary: True}


def test_remove_only_names_and_repeat(env):
    e = env
    indexes = IndexSet({"one": [definition("old"), definition("missing")], "two": []})
    assert e.module.remove_indexes(e.conn, indexes=indexes, **e.namespace) == {
        "one": ["old"],
        "two": [],
    }
    assert e.module.remove_indexes(e.conn, indexes=indexes, **e.namespace) == {"one": [], "two": []}
    assert e.state["one"] == {e.primary: True, "external": False}
    assert e.module.remove_index(e.conn, target=e.target, index=definition("external")) is True
    assert e.module.remove_index(e.conn, target=e.target, index=definition("external")) is False


def test_protected_request_prevents_all_removal(env):
    e = env
    protected = FieldIndex((("_id", 1),)) if e.backend == "mongodb" else definition(e.primary)
    indexes = IndexSet({"one": [definition("old")], "two": [protected]})
    with pytest.raises(ValueError, match="protected"):
        e.module.remove_indexes(e.conn, indexes=indexes, **e.namespace)
    assert not any(event[0] == "drop" for event in e.events)
    with pytest.raises(ValueError, match="protected"):
        e.module.remove_index(e.conn, target=e.target, index=protected)
    assert e.state["one"]["old"] is False


@pytest.mark.parametrize("operation", ["replace", "remove"])
def test_invalid_late_definition_prevents_connection(env, operation):
    e = env
    indexes = IndexSet({"one": [definition("old")], "two": [definition("bad")]})
    indexes["two"][0].keys = (("x", 9),)
    with pytest.raises(ValueError):
        if operation == "replace":
            e.module.create_indexes(e.conn, indexes=indexes, replace=True, **e.namespace)
        else:
            e.module.remove_indexes(e.conn, indexes=indexes, **e.namespace)
    assert not e.opened


def test_invalid_replace_flag_prevents_connection(env):
    e = env
    with pytest.raises(TypeError, match="boolean"):
        e.module.create_indexes(e.conn, indexes=IndexSet({"one": []}), replace=1, **e.namespace)
    assert not e.opened


def test_replacement_failure_reports_removed_and_created(env, monkeypatch):
    e = env

    def create(backend, client, target, index, timeout):
        if index.name == "fail":
            raise TimeoutError("build failed")
        return e.create(backend, client, target, index, timeout)

    monkeypatch.setattr(core, "_create", create)
    with pytest.raises(IndexCreationError) as caught:
        e.module.create_indexes(
            e.conn,
            indexes=IndexSet({"one": [definition("new"), definition("fail")]}),
            replace=True,
            **e.namespace,
        )
    error = caught.value
    assert error.completed == {"one": ["new"]}
    assert error.removed == {"one": ["old", "external"]}
    assert (error.phase, error.target, error.position) == ("create", "one", 1)
    assert isinstance(error.__cause__, TimeoutError)
    e.client.close.assert_called_once()


@pytest.mark.parametrize("replace", [False, True])
def test_removal_failure_reports_progress(env, monkeypatch, replace):
    e = env

    def drop(backend, client, target, name, timeout):
        if name == "external":
            raise RuntimeError("denied")
        return e.drop(backend, client, target, name, timeout)

    monkeypatch.setattr(core, "_drop", drop)
    indexes = IndexSet({"one": [definition("old"), definition("external")]})
    error_type = IndexCreationError if replace else IndexRemovalError
    with pytest.raises(error_type) as caught:
        if replace:
            e.module.create_indexes(e.conn, indexes=indexes, replace=True, **e.namespace)
        else:
            e.module.remove_indexes(e.conn, indexes=indexes, **e.namespace)
    error = caught.value
    assert error.phase == "remove" and error.index_name == "external"
    assert (error.removed if replace else error.completed) == {"one": ["old"]}
    assert not any(event[0] == "create" for event in e.events)
    e.client.close.assert_called_once()


def test_inspection_failure_prevents_deletion(env, monkeypatch):
    e = env

    def existing(backend, client, target, timeout):
        if target.collection == "two":
            raise RuntimeError("unavailable")
        return e.existing(backend, client, target, timeout)

    monkeypatch.setattr(core, "_existing", existing)
    with pytest.raises(IndexCreationError) as caught:
        e.module.create_indexes(
            e.conn, indexes=IndexSet({"one": [], "two": []}), replace=True, **e.namespace
        )
    assert caught.value.phase == "inspect"
    assert caught.value.removed == {"one": [], "two": []}
    assert not any(event[0] == "drop" for event in e.events)


def test_native_mongo_inspection_and_missing_errors():
    client = MagicMock()
    collection = client["db"]["c"]
    target = mongo.MongoCollectionRef("db", "c")
    collection.index_information.return_value = {"_id_": {}, "external": {}}
    assert core._existing("mongodb", client, target, 1) == {"_id_": True, "external": False}
    for code in (26, 27):
        collection.drop_index.side_effect = OperationFailure("absent", code=code)
        assert core._drop("mongodb", client, target, "external", 1) is False
    collection.drop_index.side_effect = OperationFailure("unauthorized", code=13)
    with pytest.raises(OperationFailure):
        core._drop("mongodb", client, target, "external", 1)
    collection.drop_index.side_effect = None
    assert core._drop("mongodb", client, target, "external", 1) is True
    collection.drop_index.assert_called_with("external")


def test_native_couchbase_inspection_and_missing_errors():
    pytest.importorskip("couchbase")
    from couchbase.exceptions import QueryIndexNotFoundException

    client = MagicMock()
    target = cb.CouchbaseCollectionRef("b", "s", "c")
    collection = client.bucket.return_value.scope.return_value.collection.return_value
    manager = collection.query_indexes.return_value
    manager.get_all_indexes.return_value = [
        SimpleNamespace(name="custom_primary", is_primary=True),
        SimpleNamespace(name="a`b", is_primary=False),
    ]
    assert core._existing("couchbase", client, target, 2) == {"custom_primary": True, "a`b": False}
    assert core._drop("couchbase", client, target, "a`b", 2) is True
    assert manager.drop_index.call_args.args == ("a`b",)
    assert manager.drop_index.call_args.kwargs["timeout"].total_seconds() == 2
    manager.drop_index.side_effect = QueryIndexNotFoundException()
    assert core._drop("couchbase", client, target, "a`b", 2) is False
    manager.drop_index.side_effect = TimeoutError("unknown outcome")
    with pytest.raises(TimeoutError):
        core._drop("couchbase", client, target, "a`b", 2)


def test_empty_removal_does_not_connect(env):
    e = env
    assert e.module.remove_indexes(e.conn, indexes=IndexSet({"one": []}), **e.namespace) == {
        "one": []
    }
    assert not e.opened


def test_removal_inspection_error_has_no_side_effects(env, monkeypatch):
    e = env

    def existing(backend, client, target, timeout):
        if target.collection == "two":
            raise TimeoutError("catalog unavailable")
        return e.existing(backend, client, target, timeout)

    monkeypatch.setattr(core, "_existing", existing)
    with pytest.raises(IndexRemovalError) as caught:
        e.module.remove_indexes(
            e.conn,
            indexes=IndexSet({"one": [definition("old")], "two": [definition("other")]}),
            **e.namespace,
        )
    error = caught.value
    assert (error.phase, error.target, error.position) == ("inspect", "two", None)
    assert error.completed == {"one": [], "two": []}
    assert not any(event[0] == "drop" for event in e.events)
    e.client.close.assert_called_once()


def test_removal_uses_generated_name_and_frozen_inputs(env, monkeypatch):
    e = env
    index = FieldIndex((("field", -1),))
    name = index.resolved_name
    e.state["one"][name] = False
    indexes = IndexSet({"one": [index]})

    def existing(backend, client, target, timeout):
        indexes["one"][0].name = "external"
        return e.existing(backend, client, target, timeout)

    monkeypatch.setattr(core, "_existing", existing)
    assert e.module.remove_indexes(e.conn, indexes=indexes, **e.namespace) == {"one": [name]}
    assert "external" in e.state["one"]
