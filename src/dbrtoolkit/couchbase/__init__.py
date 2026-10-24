"""Native Couchbase query descriptions without an SDK connection."""

from dbrtoolkit.couchbase.executor import AsyncCouchbaseExecutor
from dbrtoolkit.couchbase.explain import summarize
from dbrtoolkit.couchbase.query import CouchbaseQuery

__all__ = ["CouchbaseQuery", "AsyncCouchbaseExecutor", "summarize"]
