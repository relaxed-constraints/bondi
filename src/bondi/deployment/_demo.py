"""Load the packaged teaching dataset into a running deployment."""

import json
import re
import time
from dataclasses import dataclass
from importlib.resources import files
from urllib.parse import quote

from pymongo import MongoClient, ReplaceOne
from pymongo.errors import PyMongoError

from . import _couchbase


@dataclass(frozen=True)
class DemoDataResult:
    """Destination and count of successfully upserted demo documents.

    Attributes:
        backend: mongodb or couchbase.
        database: MongoDB database or Couchbase bucket.
        scope: Couchbase scope, or None for MongoDB.
        collection: Destination collection.
        document_count: Documents loaded, including replacements on repeated calls.
    """

    backend: str
    database: str
    scope: str | None
    collection: str
    document_count: int


def _name(value, label):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_-]{0,62}", value):
        raise ValueError(f"{label} must use 1–63 letters, digits, underscores or hyphens")


def load_demo_data(
    db, *, database=None, scope=None, collection="business", create_primary_index=False
):
    if type(create_primary_index) is not bool:
        raise ValueError("create_primary_index must be a boolean")
    _name(collection, "collection")
    if db.backend == "mongodb":
        if scope is not None or create_primary_index:
            raise ValueError("scope and create_primary_index are only supported for Couchbase")
        database = "demo" if database is None else database
        _name(database, "database")
    elif db.backend == "couchbase":
        if database is not None:
            raise ValueError(
                "database is only supported for MongoDB; Couchbase uses its saved bucket"
            )
        scope = "_default" if scope is None else scope
        _name(scope, "scope")
        database = db.bucket
    else:
        raise ValueError(f"Unsupported deployment backend: {db.backend}")
    if db.status() != "running":
        raise RuntimeError(
            f"Deployment {db.name!r} must be running; start it before loading demo data"
        )
    documents = json.loads(files("bondi.deployment").joinpath("business.json").read_text())
    if db.backend == "mongodb":
        try:
            with MongoClient(db.uri, timeoutMS=30000) as client:
                result = client[database][collection].bulk_write(
                    [
                        ReplaceOne(
                            {"_id": doc["business_id"]},
                            {**doc, "_id": doc["business_id"]},
                            upsert=True,
                        )
                        for doc in documents
                    ]
                )
                if not result.acknowledged or (
                    result.matched_count + result.upserted_count != len(documents)
                ):
                    raise RuntimeError("MongoDB did not acknowledge all demo documents")
        except PyMongoError:
            raise RuntimeError(
                "MongoDB demo-data load failed; some writes may have succeeded"
            ) from None
    else:
        _load_couchbase(db, scope, collection, documents, create_primary_index)
    return DemoDataResult(db.backend, database, scope, collection, len(documents))


def _load_couchbase(db, scope, collection, documents, create_primary_index):
    path = f"/pools/default/buckets/{quote(db.bucket, safe='')}/scopes"
    existing = _couchbase.request(db, path)["scopes"]
    current = next((item for item in existing if item["name"] == scope), None)
    if current is None:
        _couchbase.request(db, path, {"name": scope})
    created = current is None or not any(c["name"] == collection for c in current["collections"])
    if created:
        _couchbase.request(db, f"{path}/{quote(scope, safe='')}/collections", {"name": collection})
    keyspace = ".".join(f"`{part.replace('`', '``')}`" for part in (db.bucket, scope, collection))

    def query(statement, **parameters):
        result = _couchbase.request(
            db, "/query/service", {"statement": statement, **parameters}, query=True, timeout=30
        )
        if result.get("status") != "success":
            raise RuntimeError("Couchbase demo-data query failed; some writes may have succeeded")
        return result

    # Management can acknowledge a collection before Query sees its manifest.
    # Only retry transient keyspace availability after creating the destination.
    deadline = time.monotonic() + 30
    while True:
        try:
            result = query(
                f"UPSERT INTO {keyspace} (KEY doc.business_id, VALUE doc) "
                "SELECT doc FROM $documents AS doc RETURNING RAW META().id",
                **{"$documents": json.dumps(documents)},
            )
            break
        except _couchbase.CouchbaseHTTPError as exc:
            if not created or exc.code != 424 or time.monotonic() >= deadline:
                raise
            time.sleep(0.5)
    if sorted(result.get("results", [])) != sorted(doc["business_id"] for doc in documents):
        raise RuntimeError("Couchbase did not acknowledge all demo documents")
    if create_primary_index:
        query(f"CREATE PRIMARY INDEX IF NOT EXISTS ON {keyspace}")
