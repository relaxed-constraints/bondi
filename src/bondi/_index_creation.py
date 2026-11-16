"""Backend adapters for index creation; no deployment lifecycle operations."""

import math
from collections.abc import Mapping
from contextlib import contextmanager
from datetime import timedelta
from time import monotonic

import pymongo
from pymongo import IndexModel, MongoClient

from bondi.connection import CouchbaseConnection, MongoConnection, normalize_connection
from bondi.indexes import FieldIndex, IndexCreationError, IndexSet


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
        raise ValueError("targets must map exactly the logical names in indexes")
    conn = normalize_connection(connection)
    native, ref, credentials = (
        (MongoIndex, MongoCollectionRef, MongoConnection)
        if backend == "mongodb"
        else (CouchbaseIndex, CouchbaseCollectionRef, CouchbaseConnection)
    )
    if not isinstance(conn, credentials):
        raise TypeError(f"Connection must be for {backend}")
    for logical, definitions in indexes.items():
        if not isinstance(targets[logical], ref):
            raise TypeError(f"Incorrect target type for {logical}")
        names = set()
        for index in definitions:
            if type(index) not in (FieldIndex, native):
                raise TypeError(f"Index kind {index.kind} is not supported by {backend}")
            # Serialization also checks BSON/JSON encodability before any side effects.
            name = index.resolved_name
            if name in names:
                raise ValueError(f"Duplicate resolved index name for {logical}: {name}")
            names.add(name)
            if backend == "mongodb":
                _mongo_model(index)
            else:
                _couchbase_statement(targets[logical], index)
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


def _couchbase_statement(target, index):
    expressions = []
    for position, (key, direction) in enumerate(index.keys):
        if type(index) is FieldIndex:
            key = ".".join(_quote(part) for part in key.split("."))
        key += " ASC" if direction == 1 else " DESC"
        if index.kind == "couchbase" and index.include_missing and position == 0:
            key += " INCLUDE MISSING"
        expressions.append(key)
    path = ".".join(_quote(value) for value in (target.bucket, target.scope, target.collection))
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


def _create(backend, client, target, index, timeout):
    if backend == "mongodb":
        with pymongo.timeout(timeout):
            collection = client[target.database][target.collection]
            model = _mongo_model(index)
            if model is None:
                # Confirm the built-in index exists, rather than inventing a success.
                existing = collection.index_information().get("_id_")
                if existing is None or list(existing["key"]) != [("_id", 1)]:
                    raise ValueError("Target has no compatible built-in _id index")
                return "_id_"
            return collection.create_indexes([model])[0]

    from couchbase.options import QueryOptions

    deadline = monotonic() + timeout
    client.query(
        _couchbase_statement(target, index), QueryOptions(timeout=timedelta(seconds=timeout))
    ).execute()
    remaining = deadline - monotonic()
    if remaining <= 0:
        raise TimeoutError("Index creation exhausted the readiness deadline")
    collection = client.bucket(target.bucket).scope(target.scope).collection(target.collection)
    collection.query_indexes().watch_indexes(
        [index.resolved_name], timeout=timedelta(seconds=remaining)
    )
    return index.resolved_name


def create_one(backend, connection, target, index, timeout):
    indexes = IndexSet({"target": [index]})
    conn = _validate(backend, connection, indexes, {"target": target}, timeout)
    with _client(backend, conn, timeout) as client:
        return _create(backend, client, target, indexes["target"][0], timeout)


def create_many(backend, connection, indexes, targets, timeout):
    conn = _validate(backend, connection, indexes, targets, timeout)
    # Freeze the operation's inputs after preflight; caller mutations cannot alter this batch.
    indexes = IndexSet(indexes)
    targets = dict(targets)
    completed = {logical: [] for logical in indexes}
    if not any(indexes.values()):
        return completed
    with _client(backend, conn, timeout) as client:
        for logical, definitions in indexes.items():
            for position, index in enumerate(definitions):
                try:
                    name = _create(backend, client, targets[logical], index, timeout)
                except Exception as exc:
                    raise IndexCreationError(completed, logical, position) from exc
                completed[logical].append(name)
    return completed
