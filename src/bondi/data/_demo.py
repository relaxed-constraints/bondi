"""Load the small business dataset shipped with BONDI."""

import json
from importlib.resources import files
from typing import Any

from bondi.couchbase.collection import CouchbaseCollectionRef
from bondi.deployment import Deployment
from bondi.mongodb import MongoCollectionRef

from ._loader import load_documents
from ._types import CouchbaseConnection, LoadDataResult, MongoConnection


def load_demo_data(
    *,
    target: Deployment | MongoConnection | CouchbaseConnection,
    collection: MongoCollectionRef | CouchbaseCollectionRef,
    id_field: str | None = "business_id",
    **options: Any,
) -> LoadDataResult:
    """Load eight packaged fictional businesses into one collection.

    No download or source checkout is needed. Uses the general dataset loader.
    Couchbase requires the optional SDK, as with other dataset sources.

    Args:
        target: Managed deployment or explicit connection.
        collection: Exact destination reference matching the target backend.
        id_field: Field used for document IDs. Defaults to business_id.
        **options: Options accepted by load_documents, including mode and on_progress.
            The default mode, create, requires an empty destination.
            Use upsert to replace matching IDs and keep other documents.

    Returns:
        Acknowledged counts, source information and conversion counts.

    Raises:
        ValueError: Invalid loading options.
        TypeError: Invalid target or collection reference.
        LoadDataError: Loading failed. result contains partial progress.

    This function creates no indexes. Create query indexes separately.
    """
    documents = json.loads(files("bondi.data").joinpath("business.json").read_text())
    return load_documents(
        documents, target=target, collection=collection, id_field=id_field, **options
    )
