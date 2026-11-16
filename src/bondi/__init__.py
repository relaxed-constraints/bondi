"""A Python toolkit for document database research."""

from bondi._index_dispatch import create_index, create_indexes, remove_index, remove_indexes
from bondi.connection import CouchbaseConnection, MongoConnection
from bondi.indexes import FieldIndex, IndexCreationError, IndexRemovalError, IndexSet, load_index

__all__ = [
    "create_index",
    "create_indexes",
    "remove_index",
    "remove_indexes",
    "FieldIndex",
    "IndexSet",
    "load_index",
    "IndexCreationError",
    "IndexRemovalError",
    "MongoConnection",
    "CouchbaseConnection",
]
