"""Public index operations dispatched from deployment or connection settings."""

from bondi.connection import MongoConnection, normalize_connection


def _operation(connection, action):
    from bondi import couchbase, mongodb

    conn = normalize_connection(connection)
    module, prefix = (
        (mongodb, "mongo") if isinstance(conn, MongoConnection) else (couchbase, "couchbase")
    )
    return conn, getattr(module, action.replace("_", f"_{prefix}_", 1))


def _namespace(conn, database, bucket, scope):
    if isinstance(conn, MongoConnection):
        if database is None or bucket is not None or scope is not None:
            raise ValueError("MongoDB requires database and does not accept bucket or scope")
        return {"database": database}
    if database is not None or bucket is None or scope is None:
        raise ValueError("Couchbase requires bucket and scope and does not accept database")
    return {"bucket": bucket, "scope": scope}


def create_index(connection, *, target, index, timeout=300.0) -> str:
    """Create one index using the deployment or connection's backend.

    Args:
        connection (Deployment | MongoConnection | CouchbaseConnection): Connection settings.
        target (MongoCollectionRef | CouchbaseCollectionRef): Collection matching the backend.
        index (FieldIndex | MongoIndex | CouchbaseIndex): Shared or matching native definition.
        timeout (float): Positive finite seconds for creation and readiness.

    Returns:
        The confirmed index name.

    Delegates to create_mongo_index or create_couchbase_index. Backend validation,
    readiness and native errors are preserved. No index replacement is performed.
    """
    conn, operation = _operation(connection, "create_index")
    return operation(conn, target=target, index=index, timeout=timeout)


def create_indexes(
    connection, *, indexes, database=None, bucket=None, scope=None, timeout=300.0, replace=False
) -> dict[str, list[str]]:
    """Create an IndexSet using the deployment or connection's backend.

    Args:
        connection (Deployment | MongoConnection | CouchbaseConnection): Connection settings.
        indexes (IndexSet): Collection-keyed shared or matching native definitions.
        database (str | None): Required for MongoDB; omit for Couchbase.
        bucket (str | None): Required for Couchbase; omit for MongoDB.
        scope (str | None): Required for Couchbase; omit for MongoDB.
        timeout (float): Positive finite seconds per inspection, removal or creation.
        replace (bool): Clear secondary indexes on included collections before creating.

    Returns:
        Collection names mapped to confirmed created index names.

    Missing or mixed namespace arguments fail before connecting. Replacement preserves
    primary indexes and is non-atomic. Backend IndexCreationError progress is preserved.
    """
    conn, operation = _operation(connection, "create_indexes")
    namespace = _namespace(conn, database, bucket, scope)
    return operation(conn, indexes=indexes, timeout=timeout, replace=replace, **namespace)


def remove_index(connection, *, target, index, timeout=300.0) -> bool:
    """Remove one named index using the deployment or connection's backend.

    Args:
        connection (Deployment | MongoConnection | CouchbaseConnection): Connection settings.
        target (MongoCollectionRef | CouchbaseCollectionRef): Collection matching the backend.
        index (FieldIndex | MongoIndex | CouchbaseIndex): Definition identifying the index name.
        timeout (float): Positive finite seconds per inspection or removal.

    Returns:
        True for a confirmed removal, False if already absent.

    Backend validation and errors are preserved. Protected primary indexes raise
    ValueError. Selection uses the explicit or generated name, not key equivalence.
    """
    conn, operation = _operation(connection, "remove_index")
    return operation(conn, target=target, index=index, timeout=timeout)


def remove_indexes(
    connection, *, indexes, database=None, bucket=None, scope=None, timeout=300.0
) -> dict[str, list[str]]:
    """Remove named definitions using the deployment or connection's backend.

    Args:
        connection (Deployment | MongoConnection | CouchbaseConnection): Connection settings.
        indexes (IndexSet): Collection-keyed definitions identifying index names.
        database (str | None): Required for MongoDB; omit for Couchbase.
        bucket (str | None): Required for Couchbase; omit for MongoDB.
        scope (str | None): Required for Couchbase; omit for MongoDB.
        timeout (float): Positive finite seconds per inspection or removal.

    Returns:
        Collection names mapped to confirmed removed index names; absent names omitted.

    Missing or mixed namespace arguments fail before connecting. Protected primary
    indexes are rejected before deletion. Backend IndexRemovalError progress is preserved.
    """
    conn, operation = _operation(connection, "remove_indexes")
    namespace = _namespace(conn, database, bucket, scope)
    return operation(conn, indexes=indexes, timeout=timeout, **namespace)
