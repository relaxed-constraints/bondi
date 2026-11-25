"""AptMQL BSON sources, with dataset names mapped to databases or scopes."""

import hashlib
from pathlib import Path
from typing import Any

from bson import decode_file_iter
from bson.codec_options import CodecOptions
from huggingface_hub import HfApi, hf_hub_download

from bondi.connection import CouchbaseConnection, MongoConnection, PostgresConnection
from bondi.couchbase.collection import CouchbaseCollectionRef
from bondi.mongodb import MongoCollectionRef
from bondi.postgresql import PostgresCollectionRef

from ._loader import _load, backend_for, load_connection
from ._sources import source_plan
from ._types import LoadDataError, LoadDataResult
from ._writers import name

REPOSITORY = "MongoDB/AptMQL-Bench"


def _catalog(revision):
    api = HfApi()
    commit = api.dataset_info(REPOSITORY, revision=revision or "main").sha
    catalog = {}
    for filename in sorted(api.list_repo_files(REPOSITORY, repo_type="dataset", revision=commit)):
        parts = filename.split("/")
        if (
            len(parts) != 5
            or parts[0] != "databases"
            or parts[1] not in ("train", "dev")
            or parts[3] != "dump"
            or not parts[4].endswith(".bson")
        ):
            continue
        split, dataset, collection = parts[1], name(parts[2]), name(parts[4][:-5])
        previous = catalog.setdefault(dataset, {"split": split, "collections": {}})
        if previous["split"] != split:
            raise ValueError(f"Ambiguous AptMQL dataset in multiple splits: {dataset}")
        previous["collections"][collection] = filename
    if not catalog:
        raise ValueError("AptMQL repository contains no BSON datasets")
    return commit, catalog


def _references(connection, datasets, database, bucket, scope, schema=None):
    conn = load_connection(connection)
    if isinstance(conn, PostgresConnection):
        if any(value is not None for value in (database, bucket, scope)):
            raise ValueError("PostgreSQL accepts schema for the destination namespace")
        return {
            dataset: {
                collection: PostgresCollectionRef(
                    name(dataset if schema is None else schema), collection
                )
                for collection in entry["collections"]
            }
            for dataset, entry in datasets.items()
        }
    if schema is not None:
        raise ValueError("schema requires PostgreSQL")
    if isinstance(conn, MongoConnection):
        if bucket is not None or scope is not None:
            raise ValueError("MongoDB does not accept bucket or scope")
        return {
            dataset: {
                collection: MongoCollectionRef(
                    name(dataset if database is None else database), collection
                )
                for collection in entry["collections"]
            }
            for dataset, entry in datasets.items()
        }
    if database is not None:
        raise ValueError("Couchbase does not accept database")
    if bucket is None:
        raise ValueError("Couchbase requires bucket='NAME'")
    return {
        dataset: {
            collection: CouchbaseCollectionRef(
                name(bucket), name(dataset if scope is None else scope), collection
            )
            for collection in entry["collections"]
        }
        for dataset, entry in datasets.items()
    }


def _load_catalog(connection, commit, catalog, refs, options):
    # BSON is already decoded. Never reinterpret literal Extended JSON-shaped documents.
    if options.get("json_mode", "plain") != "plain":
        raise ValueError("AptMQL BSON loading requires json_mode='plain'")
    prepared = []
    # Resolve/download every selected file before the first destination write.
    for dataset, entry in sorted(catalog.items()):
        for collection, filename in sorted(entry["collections"].items()):
            cached = Path(
                hf_hub_download(REPOSITORY, filename, repo_type="dataset", revision=commit)
            )
            with cached.open("rb") as stream:
                digest = hashlib.file_digest(stream, "sha256").hexdigest()
            info = dict(
                kind="aptmql",
                repo_id=REPOSITORY,
                revision=commit,
                dataset=dataset,
                path=filename,
                sha256=digest,
            )
            prepared.append((dataset, collection, entry["split"], cached, info))
    results = {dataset: {} for dataset in sorted(catalog)}
    completed = []
    for dataset, collection, split, cached, info in prepared:
        namespace = options.get("namespace") or f"hf:{REPOSITORY}:{dataset}"
        # Dataset-qualified logical names prevent source-count collisions across databases.
        plan = source_plan([], f"{dataset}.{collection}", namespace, split, info)
        try:
            with cached.open("rb") as stream:
                plan["source"] = decode_file_iter(stream, CodecOptions(tz_aware=True))
                result = _load(
                    [plan], connection=connection, collection=refs[dataset][collection], **options
                )
        except Exception as error:
            if not isinstance(error, LoadDataError):
                error = LoadDataError(
                    f"{dataset}.{collection}: {type(error).__name__}",
                    LoadDataResult(
                        backend_for(connection),
                        sources=[plan["info"]],
                    ),
                )
            for previous in completed:
                error.result.destinations.update(previous.destinations)
                error.result.source_counts.update(previous.source_counts)
                error.result.sources.extend(previous.sources)
                error.result.elapsed_seconds += previous.elapsed_seconds
                error.result.uncertain_writes |= previous.uncertain_writes
                for key, value in previous.conversions.items():
                    error.result.conversions[key] = error.result.conversions.get(key, 0) + value
            raise error from None
        results[dataset][collection] = result
        completed.append(result)
    return results


def load_aptmql_dataset(
    dataset: str,
    *,
    connection: MongoConnection | CouchbaseConnection | PostgresConnection,
    database: str | None = None,
    bucket: str | None = None,
    scope: str | None = None,
    schema: str | None = None,
    revision: str | None = None,
    **options: Any,
) -> dict[str, LoadDataResult]:
    """Load all collections of one AptMQL dataset from Hugging Face BSON dumps.

    Args:
        dataset: Source database name, such as beer_factory. Its split is discovered.
        connection: Connection settings for the destination instance.
        database: MongoDB destination name. Defaults to the source dataset name.
        bucket: Required Couchbase bucket. Do not supply for MongoDB.
        schema: PostgreSQL destination schema. Defaults to the source dataset name.
        scope: Couchbase destination scope. Defaults to the source dataset name.
        revision: Hub branch, tag or commit. Resolved once before downloading.
        **options: Write, identity, conversion and progress options from load_documents.
            json_mode must be plain. BSON dates decode as timezone-aware UTC values.

    Returns:
        Load results keyed by collection name, including source commit and file SHA256.

    Raises:
        ValueError: Dataset selection or destination options are invalid or ambiguous.
        LoadDataError: A collection failed. The result includes earlier acknowledged writes.

    Downloads only the selected BSON files into the Hugging Face cache. Collections
    load sequentially in sorted order. Indexes and collection metadata are ignored.
    No mongorestore executable is required. Writes are non-atomic, with no rollback.
    Progress callbacks describe only the current collection. Hub errors propagate
    before writes. Unsupported destination values follow load_documents policies.
    """
    name(dataset)
    load_connection(connection)
    commit, catalog = _catalog(revision)
    if dataset not in catalog:
        raise ValueError(
            f"Unknown AptMQL dataset {dataset!r}. Available datasets: {sorted(catalog)}"
        )
    selected = {dataset: catalog[dataset]}
    refs = _references(connection, selected, database, bucket, scope, schema)
    return _load_catalog(connection, commit, selected, refs, options)[dataset]


def load_aptmql_repository(
    *,
    connection: MongoConnection | CouchbaseConnection | PostgresConnection,
    bucket: str | None = None,
    revision: str | None = None,
    **options: Any,
) -> dict[str, dict[str, LoadDataResult]]:
    """Load every AptMQL dataset into its own MongoDB database or Couchbase scope.

    Args:
        connection: Connection settings for the destination instance.
        bucket: Required Couchbase destination bucket. Do not supply for MongoDB.
        revision: Hub branch, tag or commit, resolved once for the entire repository.
        **options: Shared load_documents options applied to every collection.
            Destination database and scope names cannot be overridden.

    Returns:
        Dataset names mapped to collection names mapped to load results.

    Raises:
        ValueError: Source names are ambiguous or destination options are invalid.
        LoadDataError: A collection failed. Its result includes all earlier acknowledged writes.

    Downloads all BSON files before writing. Dataset names become MongoDB databases
    or Couchbase scopes within the supplied bucket. Collections and datasets load
    in sorted order. Indexes and collection metadata are ignored. Conversion, cache,
    progress and non-atomic failure behavior match load_aptmql_dataset.
    """
    if any(key in options for key in ("database", "scope", "schema")):
        raise ValueError("Repository loading uses source dataset names as databases or scopes")
    load_connection(connection)
    commit, catalog = _catalog(revision)
    refs = _references(connection, catalog, None, bucket, None)
    return _load_catalog(connection, commit, catalog, refs, options)
