"""PostgreSQL queries, executors and document tables."""

from .collection import PostgresCollectionRef
from .executor import AsyncPostgresExecutor
from .explain import summarize
from .indexes import (
    PostgresIndex,
    create_postgres_index,
    create_postgres_indexes,
    postgres_index_name,
    remove_postgres_index,
    remove_postgres_indexes,
)
from .query import PostgresQuery
from .sync_executor import PostgresExecutor

__all__ = [
    "PostgresCollectionRef",
    "AsyncPostgresExecutor",
    "PostgresExecutor",
    "PostgresQuery",
    "summarize",
    "PostgresIndex",
    "postgres_index_name",
    "create_postgres_index",
    "create_postgres_indexes",
    "remove_postgres_index",
    "remove_postgres_indexes",
]
