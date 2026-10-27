"""Native Couchbase query descriptions without an SDK connection."""

from dbrtoolkit.couchbase.executor import AsyncCouchbaseExecutor
from dbrtoolkit.couchbase.explain import summarize
from dbrtoolkit.couchbase.query import CouchbaseQuery
from dbrtoolkit.couchbase.sync_executor import CouchbaseExecutor

__all__ = ["CouchbaseExecutor", "CouchbaseQuery", "AsyncCouchbaseExecutor", "summarize"]
