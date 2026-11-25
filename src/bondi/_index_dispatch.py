"""Public index operations dispatched from connection settings."""

from __future__ import annotations

from typing import TYPE_CHECKING

from bondi.connection import (
    CouchbaseConnection,
    MongoConnection,
    PostgresConnection,
    _validate_connection,
)
from bondi.indexes import FieldIndex, IndexSet

if TYPE_CHECKING:
    from bondi.couchbase.collection import CouchbaseCollectionRef
    from bondi.couchbase.indexes import CouchbaseIndex
    from bondi.mongodb.collection import MongoCollectionRef
    from bondi.mongodb.indexes import MongoIndex
    from bondi.postgresql import PostgresCollectionRef, PostgresIndex


def _operation(connection, action):
    from bondi import couchbase, mongodb, postgresql

    if isinstance(connection, PostgresConnection):
        return connection, getattr(postgresql, action.replace("_", "_postgres_", 1))

    conn = _validate_connection(connection)
    module, prefix = (
        (mongodb, "mongo") if isinstance(conn, MongoConnection) else (couchbase, "couchbase")
    )
    return conn, getattr(module, action.replace("_", f"_{prefix}_", 1))


def _namespace(conn, database, bucket, scope, schema):
    if isinstance(conn, PostgresConnection):
        if schema is None or any(x is not None for x in (database, bucket, scope)):
            raise ValueError("PostgreSQL requires schema only")
        return {"schema": schema}
    if schema is not None:
        raise ValueError("schema requires PostgreSQL")
    if isinstance(conn, MongoConnection):
        if database is None or bucket is not None or scope is not None:
            raise ValueError("MongoDB requires database and does not accept bucket or scope")
        return {"database": database}
    if database is not None or bucket is None or scope is None:
        raise ValueError("Couchbase requires bucket and scope and does not accept database")
    return {"bucket": bucket, "scope": scope}


def create_index(
    connection: MongoConnection | CouchbaseConnection | PostgresConnection,
    *,
    collection: MongoCollectionRef | CouchbaseCollectionRef | PostgresCollectionRef,
    index: FieldIndex | MongoIndex | CouchbaseIndex | PostgresIndex,
    timeout: float = 300.0,
) -> str:
    """Create one index using the connection's backend.

    Args:
        connection: Connection settings.
        collection: Collection matching the backend.
        index: Shared or matching native definition.
        timeout (float): Positive finite seconds for creation and readiness.

    Returns:
        The confirmed index name.

    Delegates to the matching backend. Backend validation,
    readiness and native errors are preserved. No index replacement is performed.
    """
    conn, operation = _operation(connection, "create_index")
    return operation(conn, collection=collection, index=index, timeout=timeout)


def create_indexes(
    connection: MongoConnection | CouchbaseConnection | PostgresConnection,
    *,
    indexes: IndexSet,
    database: str | None = None,
    bucket: str | None = None,
    scope: str | None = None,
    schema: str | None = None,
    timeout: float = 300.0,
    replace: bool = False,
) -> dict[str, list[str]]:
    """Create an IndexSet using the connection's backend.

    Args:
        connection: Connection settings.
        indexes (IndexSet): Collection-keyed shared or matching native definitions.
        database (str | None): Required for MongoDB; omit for Couchbase.
        bucket (str | None): Required for Couchbase; omit for MongoDB.
        schema (str | None): Required for PostgreSQL.
        scope (str | None): Required for Couchbase; omit for MongoDB.
        timeout (float): Positive finite seconds per inspection, removal or creation.
        replace (bool): Clear secondary indexes on included collections before creating.

    Returns:
        Collection names mapped to confirmed created index names.

    Missing or mixed namespace arguments fail before connecting. Replacement preserves
    primary indexes and is non-atomic. Backend IndexCreationError progress is preserved.
    """
    conn, operation = _operation(connection, "create_indexes")
    namespace = _namespace(conn, database, bucket, scope, schema)
    return operation(conn, indexes=indexes, timeout=timeout, replace=replace, **namespace)


def remove_index(
    connection: MongoConnection | CouchbaseConnection | PostgresConnection,
    *,
    collection: MongoCollectionRef | CouchbaseCollectionRef | PostgresCollectionRef,
    index: FieldIndex | MongoIndex | CouchbaseIndex | PostgresIndex,
    timeout: float = 300.0,
) -> bool:
    """Remove one named index using the connection's backend.

    Args:
        connection: Connection settings.
        collection: Collection matching the backend.
        index: Definition identifying the index name.
        timeout (float): Positive finite seconds per inspection or removal.

    Returns:
        True for a confirmed removal, False if already absent.

    Backend validation and errors are preserved. Protected primary indexes raise
    ValueError. Selection uses the explicit or generated name, not key equivalence.
    """
    conn, operation = _operation(connection, "remove_index")
    return operation(conn, collection=collection, index=index, timeout=timeout)


def remove_indexes(
    connection: MongoConnection | CouchbaseConnection | PostgresConnection,
    *,
    indexes: IndexSet,
    database: str | None = None,
    bucket: str | None = None,
    scope: str | None = None,
    schema: str | None = None,
    timeout: float = 300.0,
) -> dict[str, list[str]]:
    """Remove named definitions using the connection's backend.

    Args:
        connection: Connection settings.
        indexes (IndexSet): Collection-keyed definitions identifying index names.
        database (str | None): Required for MongoDB; omit for Couchbase.
        bucket (str | None): Required for Couchbase; omit for MongoDB.
        schema (str | None): Required for PostgreSQL.
        scope (str | None): Required for Couchbase; omit for MongoDB.
        timeout (float): Positive finite seconds per inspection or removal.

    Returns:
        Collection names mapped to confirmed removed index names; absent names omitted.

    Missing or mixed namespace arguments fail before connecting. Protected primary
    indexes are rejected before deletion. Backend IndexRemovalError progress is preserved.
    """
    conn, operation = _operation(connection, "remove_indexes")
    namespace = _namespace(conn, database, bucket, scope, schema)
    return operation(conn, indexes=indexes, timeout=timeout, **namespace)
