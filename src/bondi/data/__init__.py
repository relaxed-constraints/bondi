"""Read datasets and load their documents into MongoDB or Couchbase."""

from ._loader import load_data
from ._sources import dataset_info, list_datasets
from ._types import CouchbaseConnection, LoadDataError, LoadDataResult, MongoConnection

__all__ = [
    "load_data",
    "dataset_info",
    "list_datasets",
    "CouchbaseConnection",
    "MongoConnection",
    "LoadDataError",
    "LoadDataResult",
]
