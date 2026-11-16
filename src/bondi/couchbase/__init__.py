"""Native Couchbase query descriptions without an SDK connection."""

from bondi.couchbase.collection import CouchbaseCollectionRef
from bondi.couchbase.executor import AsyncCouchbaseExecutor
from bondi.couchbase.explain import summarize
from bondi.couchbase.indexes import (
    CouchbaseIndex,
    create_couchbase_index,
    create_couchbase_indexes,
    remove_couchbase_index,
    remove_couchbase_indexes,
)
from bondi.couchbase.query import CouchbaseQuery
from bondi.couchbase.sync_executor import CouchbaseExecutor

__all__ = [
    "CouchbaseIndex",
    "create_couchbase_index",
    "create_couchbase_indexes",
    "remove_couchbase_index",
    "remove_couchbase_indexes",
    "CouchbaseCollectionRef",
    "CouchbaseExecutor",
    "CouchbaseQuery",
    "AsyncCouchbaseExecutor",
    "summarize",
]
