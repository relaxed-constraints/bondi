"""Native Couchbase query descriptions without an SDK connection."""

from bondi.couchbase.collection import CouchbaseCollectionRef
from bondi.couchbase.executor import AsyncCouchbaseExecutor
from bondi.couchbase.explain import summarize
from bondi.couchbase.query import CouchbaseQuery
from bondi.couchbase.sync_executor import CouchbaseExecutor

__all__ = [
    "CouchbaseCollectionRef",
    "CouchbaseExecutor",
    "CouchbaseQuery",
    "AsyncCouchbaseExecutor",
    "summarize",
]
