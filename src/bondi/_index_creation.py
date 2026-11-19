"""Backend index lifecycle adapters; no deployment lifecycle operations."""

import math
from collections.abc import Mapping
from contextlib import contextmanager
from datetime import timedelta
from time import monotonic

import pymongo
from pymongo import IndexModel, MongoClient

from bondi.connection import CouchbaseConnection, MongoConnection, _validate_connection
from bondi.indexes import FieldIndex, IndexCreationError, IndexRemovalError, IndexSet


def _validate(backend, connection, indexes, targets, timeout):
    from bondi.couchbase.collection import CouchbaseCollectionRef
    from bondi.couchbase.indexes import CouchbaseIndex
    from bondi.mongodb.collection import MongoCollectionRef
    from bondi.mongodb.indexes import MongoIndex

    if isinstance(timeout, bool) or not isinstance(timeout, (int, float)):
        raise TypeError("timeout must be a positive finite number of seconds")
    if not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("timeout must be positive and finite")
    if not isinstance(indexes, IndexSet):
        raise TypeError("indexes must be an IndexSet")
    indexes.validate()
    if not isinstance(targets, Mapping) or set(targets) != set(indexes):
        raise ValueError("targets must map exactly the collection names in indexes")
    conn = _validate_connection(connection)
    native, ref, credentials = (
        (MongoIndex, MongoCollectionRef, MongoConnection)
        if backend == "mongodb"
        else (CouchbaseIndex, CouchbaseCollectionRef, CouchbaseConnection)
    )
    if not isinstance(conn, credentials):
        raise TypeError(f"Connection must be for {backend}")
    for collection_name, definitions in indexes.items():
        if not isinstance(targets[collection_name], ref):
            raise TypeError(f"Incorrect collection type for {collection_name}")
        names = set()
        for index in definitions:
            if type(index) not in (FieldIndex, native):
                raise TypeError(f"Index kind {index.kind} is not supported by {backend}")
            # Serialization also checks BSON/JSON encodability before any side effects.
            name = index.resolved_name
            if name in names:
                raise ValueError(f"Duplicate resolved index name for {collection_name}: {name}")
            names.add(name)
            if backend == "mongodb":
                _mongo_model(index)
            else:
                _couchbase_statement(targets[collection_name], index)
    return conn


def _mongo_model(index):
    options = {}
    if index.kind == "mongodb":
        options.update(unique=index.unique, sparse=index.sparse)
        if index.partial_filter is not None:
            options["partialFilterExpression"] = index.partial_filter
    if index.keys == (("_id", 1),):
        if (
            index.name not in (None, "_id_")
            or options.get("sparse")
            or options.get("partialFilterExpression") is not None
        ):
            raise ValueError("The built-in _id index requires its default name and no filter")
        # The built-in index is always unique, even for a shared field definition.
        return None
    if index.name == "_id_":
        raise ValueError("_id_ is reserved for the built-in ascending _id index")
    return IndexModel(list(index.keys), name=index.resolved_name, **options)


def _quote(identifier):
    return "`" + identifier.replace("`", "``") + "`"


def _couchbase_statement(collection, index):
    expressions = []
    for position, (key, direction) in enumerate(index.keys):
        if type(index) is FieldIndex:
            key = ".".join(_quote(part) for part in key.split("."))
        key += " ASC" if direction == 1 else " DESC"
        if index.kind == "couchbase" and index.include_missing and position == 0:
            key += " INCLUDE MISSING"
        expressions.append(key)
    path = ".".join(
        _quote(value) for value in (collection.bucket, collection.scope, collection.collection)
    )
    statement = f"CREATE INDEX {_quote(index.resolved_name)} ON {path} ({', '.join(expressions)})"
    if index.kind == "couchbase" and index.condition is not None:
        statement += " WHERE " + index.condition
    # Explicitly request a build even on servers configured to defer by default.
    return statement + ' WITH {"defer_build": false}'


@contextmanager
def _client(backend, conn, timeout):
    if backend == "mongodb":
        credentials = {
            key: value
            for key, value in (("username", conn.username), ("password", conn.password))
            if value is not None
        }
        client = MongoClient(conn.uri, timeoutMS=timeout * 1000, **credentials)
    else:
        try:
            from couchbase.auth import PasswordAuthenticator
            from couchbase.cluster import Cluster
            from couchbase.options import ClusterOptions
        except ModuleNotFoundError as exc:
            if exc.name != "couchbase" and not (exc.name or "").startswith("couchbase."):
                raise
            raise ImportError("Install Couchbase support with: uv sync --extra couchbase") from exc

        client = Cluster(
            conn.uri, ClusterOptions(PasswordAuthenticator(conn.username, conn.password))
        )
    try:
        yield client
    finally:
        client.close()


def _create(backend, client, collection, index, timeout):
    if backend == "mongodb":
        with pymongo.timeout(timeout):
            native_collection = client[collection.database][collection.collection]
            model = _mongo_model(index)
            if model is None:
                # Confirm the built-in index exists, rather than inventing a success.
                existing = native_collection.index_information().get("_id_")
                if existing is None or list(existing["key"]) != [("_id", 1)]:
                    raise ValueError("Target has no compatible built-in _id index")
                return "_id_"
            return native_collection.create_indexes([model])[0]

    from couchbase.options import QueryOptions

    deadline = monotonic() + timeout
    client.query(
        _couchbase_statement(collection, index), QueryOptions(timeout=timedelta(seconds=timeout))
    ).execute()
    remaining = deadline - monotonic()
    if remaining <= 0:
        raise TimeoutError("Index creation exhausted the readiness deadline")
    native_collection = (
        client.bucket(collection.bucket).scope(collection.scope).collection(collection.collection)
    )
    native_collection.query_indexes().watch_indexes(
        [index.resolved_name], timeout=timedelta(seconds=remaining)
    )
    return index.resolved_name


def create_one(backend, connection, collection, index, timeout):
    indexes = IndexSet({"target": [index]})
    conn = _validate(backend, connection, indexes, {"target": collection}, timeout)
    with _client(backend, conn, timeout) as client:
        return _create(backend, client, collection, indexes["target"][0], timeout)


def _existing(backend, client, collection, timeout):
    """Return name-to-protected flags, including indexes created outside BONDI."""
    if backend == "mongodb":
        with pymongo.timeout(timeout):
            return {
                name: name == "_id_"
                for name in client[collection.database][collection.collection].index_information()
            }
    manager = (
        client.bucket(collection.bucket)
        .scope(collection.scope)
        .collection(collection.collection)
        .query_indexes()
    )
    return {
        index.name: index.is_primary
        for index in manager.get_all_indexes(timeout=timedelta(seconds=timeout))
    }


def _drop(backend, client, collection, name, timeout):
    """Return whether the server acknowledged removal; tolerate only missing indexes."""
    if backend == "mongodb":
        try:
            with pymongo.timeout(timeout):
                client[collection.database][collection.collection].drop_index(name)
        except pymongo.errors.OperationFailure as exc:
            if exc.code not in (26, 27):  # NamespaceNotFound or IndexNotFound
                raise
            return False
    else:
        from couchbase.exceptions import QueryIndexNotFoundException

        manager = (
            client.bucket(collection.bucket)
            .scope(collection.scope)
            .collection(collection.collection)
            .query_indexes()
        )
        try:
            manager.drop_index(name, timeout=timedelta(seconds=timeout))
        except QueryIndexNotFoundException:
            return False
    return True


def create_many(backend, connection, indexes, targets, timeout, replace=False):
    if type(replace) is not bool:
        raise TypeError("replace must be a boolean")
    conn = _validate(backend, connection, indexes, targets, timeout)
    # Freeze inputs after preflight; caller mutations cannot alter this batch.
    indexes = IndexSet(indexes)
    targets = dict(targets)
    completed = {name: [] for name in indexes}
    removed = {name: [] for name in indexes}
    if not indexes or (not replace and not any(indexes.values())):
        return completed
    with _client(backend, conn, timeout) as client:
        if replace:
            plan = {}
            # Discover every collection before deleting anything.
            for collection_name in indexes:
                try:
                    plan[collection_name] = [
                        name
                        for name, protected in _existing(
                            backend, client, targets[collection_name], timeout
                        ).items()
                        if not protected
                    ]
                except Exception as exc:
                    raise IndexCreationError(
                        completed, collection_name, None, removed=removed, phase="inspect"
                    ) from exc
            for collection_name, names in plan.items():
                for name in names:
                    try:
                        if _drop(backend, client, targets[collection_name], name, timeout):
                            removed[collection_name].append(name)
                    except Exception as exc:
                        raise IndexCreationError(
                            completed,
                            collection_name,
                            None,
                            removed=removed,
                            phase="remove",
                            index_name=name,
                        ) from exc
        for collection_name, definitions in indexes.items():
            for position, index in enumerate(definitions):
                try:
                    name = _create(backend, client, targets[collection_name], index, timeout)
                except Exception as exc:
                    raise IndexCreationError(
                        completed, collection_name, position, removed=removed
                    ) from exc
                completed[collection_name].append(name)
    return completed


def _removal_inputs(backend, connection, indexes, targets, timeout):
    conn = _validate(backend, connection, indexes, targets, timeout)
    indexes = IndexSet(indexes)
    for definitions in indexes.values():
        for index in definitions:
            if backend == "mongodb" and _mongo_model(index) is None:
                raise ValueError("Cannot remove the protected MongoDB _id index")
    return conn, indexes, dict(targets)


def _check_protected(existing, definitions):
    for index in definitions:
        if existing.get(index.resolved_name):
            raise ValueError(f"Cannot remove protected primary index: {index.resolved_name}")


def remove_one(backend, connection, collection, index, timeout):
    conn, indexes, _ = _removal_inputs(
        backend, connection, IndexSet({"target": [index]}), {"target": collection}, timeout
    )
    definition = indexes["target"][0]
    with _client(backend, conn, timeout) as client:
        existing = _existing(backend, client, collection, timeout)
        _check_protected(existing, [definition])
        return definition.resolved_name in existing and _drop(
            backend, client, collection, definition.resolved_name, timeout
        )


def remove_many(backend, connection, indexes, targets, timeout):
    conn, indexes, targets = _removal_inputs(backend, connection, indexes, targets, timeout)
    completed = {name: [] for name in indexes}
    if not any(indexes.values()):
        return completed
    with _client(backend, conn, timeout) as client:
        existing = {}
        for collection_name, definitions in indexes.items():
            if not definitions:
                continue
            try:
                existing[collection_name] = _existing(
                    backend, client, targets[collection_name], timeout
                )
            except Exception as exc:
                raise IndexRemovalError(completed, collection_name, None, phase="inspect") from exc
            # A protected-name request aborts the entire batch before any deletion.
            _check_protected(existing[collection_name], definitions)
        for collection_name, definitions in indexes.items():
            for position, index in enumerate(definitions):
                name = index.resolved_name
                if name not in existing[collection_name]:
                    continue
                try:
                    if _drop(backend, client, targets[collection_name], name, timeout):
                        completed[collection_name].append(name)
                except Exception as exc:
                    raise IndexRemovalError(
                        completed, collection_name, position, index_name=name
                    ) from exc
    return completed
