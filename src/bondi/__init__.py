"""A Python toolkit for document database research."""

from bondi.connection import CouchbaseConnection, MongoConnection
from bondi.indexes import FieldIndex, IndexCreationError, IndexRemovalError, IndexSet, load_index

__all__ = [
    "FieldIndex",
    "IndexSet",
    "load_index",
    "IndexCreationError",
    "IndexRemovalError",
    "MongoConnection",
    "CouchbaseConnection",
]
