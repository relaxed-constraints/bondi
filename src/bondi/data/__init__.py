"""Read datasets and load their documents into MongoDB or Couchbase."""

from ._aptmql import load_aptmql_dataset, load_aptmql_repository
from ._demo import load_demo_data
from ._loader import load_documents, load_file, load_hf_dataset, load_hf_repository
from ._sources import dataset_info, list_datasets
from ._types import LoadDataError, LoadDataResult

__all__ = [
    "load_aptmql_dataset",
    "load_aptmql_repository",
    "load_demo_data",
    "load_documents",
    "load_file",
    "load_hf_dataset",
    "load_hf_repository",
    "dataset_info",
    "list_datasets",
    "LoadDataError",
    "LoadDataResult",
]
