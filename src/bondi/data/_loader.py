"""Load documents with explicit source, identity and write rules."""

import copy
import sqlite3
import tempfile
from collections.abc import Callable, Iterable, Mapping
from pathlib import Path
from time import perf_counter
from typing import Any, Literal

from bondi.couchbase.collection import CouchbaseCollectionRef
from bondi.deployment import Deployment
from bondi.mongodb import MongoCollectionRef

from ._sources import decode_document, hf_configs, hf_plans, hf_revision, records, source_plan
from ._types import CouchbaseConnection, LoadDataError, LoadDataResult, MongoConnection
from ._values import convert, document_key, generated_id, identity
from ._writers import CouchbaseWriter, MongoWriter, connection, name


def _destination(target, collection):
    conn = connection(target)
    if isinstance(conn, MongoConnection) and isinstance(collection, MongoCollectionRef):
        dest = (name(collection.database), None, name(collection.collection))
    elif isinstance(conn, CouchbaseConnection) and isinstance(collection, CouchbaseCollectionRef):
        dest = (name(collection.bucket), name(collection.scope), name(collection.collection))
    else:
        raise TypeError("collection must be a CollectionRef for the target backend")
    return conn, dest


def load_documents(
    documents: Iterable[dict],
    *,
    target: Deployment | MongoConnection | CouchbaseConnection,
    collection: MongoCollectionRef | CouchbaseCollectionRef,
    id_field: str | None = None,
    namespace: str | None = None,
    mode: Literal["create", "replace", "upsert"] = "create",
    bucket_memory_mb: int | None = None,
    json_mode: Literal["plain", "extended"] = "plain",
    naive_datetimes: Literal["error", "utc"] = "error",
    decimal_mode: Literal["error", "string"] = "error",
    batch_size: int = 1000,
    on_progress: Callable[[LoadDataResult], None] | None = None,
) -> LoadDataResult:
    """Load dictionaries into one exact collection.

    Args:
        documents: Iterable of document dictionaries. No split or collection mappings.
        target: Managed deployment or explicit connection.
        collection: Exact destination reference matching the target backend.
        id_field: Field to use as _id. Otherwise preserve _id.
        namespace: Stable identity used to generate missing IDs.
        mode: create requires an empty destination. replace clears it, preserving
            indexes. upsert replaces matching IDs and leaves other documents.
        bucket_memory_mb: Quota required when creating a Couchbase bucket.
        json_mode: extended decodes Extended JSON wrappers before conversion.
        naive_datetimes: error rejects naive datetimes; utc assumes UTC.
        decimal_mode: error rejects Couchbase decimals; string stores their text.
        batch_size: Maximum buffered documents and progress interval.
        on_progress: Synchronous callback receiving an independent progress snapshot.

    Returns:
        Acknowledged counts, source information and conversion counts.

    Raises:
        ValueError: Invalid options or destination names.
        TypeError: Invalid source or mismatched collection reference.
        LoadDataError: Loading failed. result contains partial progress.

    Loads are non-atomic. No rollback or automatic retries occur. Duplicate IDs
    within the input fail, including in upsert mode. Do not write concurrently.
    """
    if isinstance(documents, (str, Path, Mapping)) or not isinstance(documents, Iterable):
        raise TypeError("documents must be an iterable of dictionaries, not a file or mapping")
    _destination(target, collection)
    return _load(
        [source_plan(documents, collection.collection, namespace)],
        target=target,
        collection=collection,
        id_field=id_field,
        namespace=namespace,
        mode=mode,
        bucket_memory_mb=bucket_memory_mb,
        json_mode=json_mode,
        naive_datetimes=naive_datetimes,
        decimal_mode=decimal_mode,
        batch_size=batch_size,
        on_progress=on_progress,
    )


def load_file(
    path: str | Path,
    *,
    target: Deployment | MongoConnection | CouchbaseConnection,
    collection: MongoCollectionRef | CouchbaseCollectionRef,
    **options: Any,
) -> LoadDataResult:
    """Load one CSV, JSON, JSONL or Parquet file into an exact CollectionRef.

    Args:
        path: Local file. Its extension selects the reader.
        target: Managed deployment or explicit connection.
        collection: MongoCollectionRef or CouchbaseCollectionRef.
        **options: Shared ID, write, type and progress options from load_documents.

    Returns:
        Load counts and source information, including the file SHA256.

    CSV values remain strings. JSON arrays are streamed. No manifest, package
    mapping or catalogue alias is accepted.
    """
    _destination(target, collection)
    path = Path(path)
    if path.suffix.lower() not in (".csv", ".json", ".jsonl", ".parquet"):
        raise ValueError("Supported file formats: csv, json, jsonl, parquet")
    return _load(
        [source_plan(path, collection.collection, options.get("namespace"))],
        target=target,
        collection=collection,
        **options,
    )


def load_hf_dataset(
    repo_id: str,
    *,
    target: Deployment | MongoConnection | CouchbaseConnection,
    collection: MongoCollectionRef | CouchbaseCollectionRef,
    dataset: str | None = None,
    split: str | list[str] | None = None,
    revision: str | None = None,
    **options: Any,
) -> LoadDataResult:
    """Load one Hugging Face configuration into one exact collection.

    Args:
        repo_id: Hub dataset repository ID.
        target: Managed deployment or explicit connection.
        collection: Exact destination reference. No suffix is added.
        dataset: Configuration name. May be omitted only for a single-config repo.
        split: Split name or list. None combines all splits in sorted name order.
        revision: Branch, tag or commit. Resolved to a commit before loading.
        **options: Shared options from load_documents. Namespace defaults to the
            repository and configuration identity.

    Returns:
        Load counts, original split counts and the resolved source commit.

    Uses Hugging Face streaming readers, which can normalize rows to a shared
    schema. Generated IDs include the original split; explicit duplicate IDs fail.
    """
    _destination(target, collection)
    commit = hf_revision(repo_id, revision)
    configs = hf_configs(repo_id, commit)
    if dataset is None:
        if len(configs) != 1:
            raise ValueError(f"Specify dataset. Available datasets: {configs}")
        dataset = configs[0]
    if dataset not in configs:
        raise ValueError(f"Unknown dataset {dataset!r}. Available datasets: {configs}")
    plans = hf_plans(repo_id, dataset, commit, split, options.get("namespace"))
    return _load(plans, target=target, collection=collection, **options)


def load_hf_repository(
    repo_id: str,
    *,
    target: Deployment | MongoConnection | CouchbaseConnection,
    database: str | None = None,
    bucket: str | None = None,
    scope: str = "_default",
    split: str | list[str] | None = None,
    revision: str | None = None,
    **options: Any,
) -> dict[str, LoadDataResult]:
    """Load every HF configuration into a collection with the same name.

    Args:
        repo_id: Hub dataset repository ID.
        target: Managed deployment or explicit connection.
        database: Required for MongoDB. Do not pass bucket or scope.
        bucket: Required for Couchbase. Do not pass database.
        scope: Couchbase scope, default _default.
        split: Selection applied to every configuration. None combines all splits.
        revision: Resolve once so all configurations use the same commit.
        **options: Shared options from load_documents, applied to each collection.

    Returns:
        Results keyed by configuration name.

    Names and split selections are checked before any writes. Collections load
    sequentially in sorted name order. On failure, earlier writes remain.
    LoadDataError.result includes completed collections and the failed collection.
    Progress callbacks report the current collection only.
    """
    conn = connection(target)
    if isinstance(conn, MongoConnection):
        if database is None:
            raise ValueError("MongoDB requires --database NAME or database='NAME'")
        if bucket is not None or scope != "_default":
            raise ValueError("MongoDB does not accept bucket or scope")
        name(database)

        def make_ref(value):
            return MongoCollectionRef(database, value)
    else:
        if database is not None:
            raise ValueError("Couchbase does not accept database")
        if bucket is None:
            raise ValueError("Couchbase requires --bucket NAME or bucket='NAME'")
        name(bucket)
        name(scope)

        def make_ref(value):
            return CouchbaseCollectionRef(bucket, scope, value)

    commit = hf_revision(repo_id, revision)
    configs = hf_configs(repo_id, commit)
    if not configs:
        raise ValueError("Repository contains no datasets")
    prepared = []
    for config in configs:
        ref = make_ref(name(config))
        prepared.append(
            (config, ref, hf_plans(repo_id, config, commit, split, options.get("namespace")))
        )
    results = {}
    for config, ref, plans in prepared:
        try:
            results[config] = _load(plans, target=target, collection=ref, **options)
        except LoadDataError as error:
            for previous in results.values():
                error.result.destinations.update(previous.destinations)
                error.result.source_counts.update(previous.source_counts)
                error.result.sources.extend(previous.sources)
                error.result.elapsed_seconds += previous.elapsed_seconds
                for key, value in previous.conversions.items():
                    error.result.conversions[key] = error.result.conversions.get(key, 0) + value
            raise
    return results


def _load(
    plans,
    *,
    target,
    collection,
    bucket_memory_mb=None,
    id_field=None,
    namespace=None,
    mode="create",
    json_mode="plain",
    naive_datetimes="error",
    decimal_mode="error",
    batch_size=1000,
    on_progress=None,
):
    start = perf_counter()
    for value, allowed, label in [
        (mode, ("create", "replace", "upsert"), "mode"),
        (json_mode, ("plain", "extended"), "json_mode"),
        (naive_datetimes, ("error", "utc"), "naive_datetimes"),
        (decimal_mode, ("error", "string"), "decimal_mode"),
    ]:
        if value not in allowed:
            raise ValueError(f"Invalid {label}")
    if type(batch_size) is not int or batch_size <= 0:
        raise ValueError("batch_size must be a positive integer")
    if namespace is not None and (not isinstance(namespace, str) or not namespace):
        raise ValueError("namespace must be a nonempty string")
    if on_progress is not None and not callable(on_progress):
        raise TypeError("on_progress must be callable")
    if id_field is not None and (not isinstance(id_field, str) or not id_field):
        raise ValueError("id_field must be a nonempty field name")
    if bucket_memory_mb is not None and (
        type(bucket_memory_mb) is not int or bucket_memory_mb < 100
    ):
        raise ValueError("bucket_memory_mb must be an integer of at least 100")
    conn, dest = _destination(target, collection)
    backend = "couchbase" if isinstance(conn, CouchbaseConnection) else "mongodb"
    for plan in plans:
        plan["destination"] = dest
    result = LoadDataResult(
        backend,
        sources=[p["info"] for p in plans],
        settings={
            "mode": mode,
            "json_mode": json_mode,
            "naive_datetimes": naive_datetimes,
            "decimal_mode": decimal_mode,
            "namespace": namespace,
            "id_field": id_field,
        },
    )
    writer = None
    context = "destination preparation"
    try:
        writer = CouchbaseWriter(conn) if backend == "couchbase" else MongoWriter(conn)
        occupied = writer.preflight(dest, bucket_memory_mb)
        if occupied and mode == "create":
            raise ValueError("create requires absent or empty collections")
        args = {"quota": bucket_memory_mb} if backend == "couchbase" else {}
        writer.prepare(dest, mode, **args)
        result.destinations["/".join(x for x in dest if x)] = 0
        with tempfile.TemporaryDirectory(prefix="bondi-load-") as temporary:
            seen = sqlite3.connect(Path(temporary) / "ids.sqlite")
            try:
                seen.execute(
                    "CREATE TABLE ids (destination TEXT, id TEXT, PRIMARY KEY(destination,id))"
                )
                for plan in plans:
                    dest = plan["destination"]
                    destination = "/".join(x for x in dest if x)
                    origin = f"{plan['logical']}:{plan['split'] or 'unsplit'}"
                    batch = []

                    def flush():
                        for key, document in batch:
                            result.uncertain_writes = True
                            writer.write_one(dest, key, document, mode)
                            result.uncertain_writes = False
                            result.destinations[destination] += 1
                            result.source_counts[origin] = result.source_counts.get(origin, 0) + 1
                        batch.clear()
                        seen.commit()
                        result.elapsed_seconds = perf_counter() - start
                        if on_progress:
                            returned = on_progress(copy.deepcopy(result))
                            if returned is not None:
                                if hasattr(returned, "close"):
                                    returned.close()
                                raise TypeError("on_progress must return None")

                    for row, document in enumerate(records(plan["source"], json_mode)):
                        context = f"{origin}, shard {plan['shard']}, row {row}"
                        if not isinstance(document, dict):
                            raise ValueError("Each source row must be a document object")
                        if json_mode == "extended" and not isinstance(plan["source"], (str, Path)):
                            document = decode_document(document)
                        field = id_field
                        if field is not None:
                            if field not in document or document[field] is None:
                                raise ValueError("The ID field is absent or null")
                            source_id = document[field]
                            if "_id" in document and document["_id"] != source_id:
                                raise ValueError("id_field conflicts with the existing _id")
                        elif "_id" in document:
                            source_id = document["_id"]
                        else:
                            source_id = generated_id(
                                plan["namespace"],
                                plan["logical"],
                                plan["split"],
                                plan["shard"],
                                row,
                            )
                        token = identity(source_id)
                        try:
                            seen.execute("INSERT INTO ids VALUES (?, ?)", (destination, token))
                        except sqlite3.IntegrityError:
                            raise ValueError("Duplicate incoming document ID") from None
                        document = {**document, "_id": source_id}
                        converted = convert(
                            document,
                            backend,
                            result.settings,
                            result.conversions,
                            decoded=json_mode == "extended"
                            and isinstance(plan["source"], (str, Path))
                            and Path(plan["source"]).suffix.lower() in (".json", ".jsonl"),
                        )
                        batch.append((document_key(source_id), converted))
                        if len(batch) >= batch_size:
                            flush()
                    if batch:
                        flush()
            finally:
                seen.close()
        result.elapsed_seconds = perf_counter() - start
        return result
    except Exception as error:
        result.elapsed_seconds = perf_counter() - start
        # Driver errors can contain URIs or credentials. Do not include their text.
        detail = (
            str(error)
            if type(error) in (ValueError, TypeError, ImportError)
            else type(error).__name__
        )
        raise LoadDataError(f"{context}: {detail}", result) from None
    finally:
        if writer is not None:
            writer.close()
