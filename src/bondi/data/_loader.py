"""Load documents with explicit source, identity and write rules."""

import copy
import sqlite3
import tempfile
from collections.abc import Callable, Iterable, Mapping, Sequence
from pathlib import Path
from time import perf_counter
from typing import Literal

from bondi.deployment import Deployment

from ._sources import prepare, records
from ._types import CouchbaseConnection, LoadDataError, LoadDataResult, MongoConnection
from ._values import convert, document_key, generated_id, identity
from ._writers import CouchbaseWriter, MongoWriter, connection, name


def load_data(
    source: str | Path | Iterable[dict] | Mapping | None = None,
    *,
    target: Deployment | MongoConnection | CouchbaseConnection,
    manifest: str | Path | Mapping | None = None,
    database: str | None = None,
    bucket: str | None = None,
    scope: str = "_default",
    collection: str | None = None,
    bucket_memory_mb: int | None = None,
    id_field: str | None = None,
    namespace: str | None = None,
    mode: Literal["create", "replace", "upsert"] = "create",
    split: str | Sequence[str] | None = None,
    splits: Literal["preserve", "merge"] = "preserve",
    json_mode: Literal["plain", "extended"] = "plain",
    naive_datetimes: Literal["error", "utc"] = "error",
    decimal_mode: Literal["error", "string"] = "error",
    indexes: str | None = None,
    batch_size: int = 1000,
    on_progress: Callable[[LoadDataResult], None] | None = None,
) -> LoadDataResult:
    """Read a source and write documents to MongoDB or Couchbase.

    Args:
        source: File, registered name, document iterable, HF dataset or collection mapping.
        target: Deployment, MongoConnection or CouchbaseConnection.
        manifest: Version 1 manifest path or mapping. Mutually exclusive with source.
        database: MongoDB database. Required unless supplied by the manifest.
            Manifests can override each destination.
        bucket: Default Couchbase bucket. Defaults to a managed deployment's bucket.
        scope: Default Couchbase scope.
        collection: Name for a single source. Catalogue entries provide defaults.
        bucket_memory_mb: Required quota for a missing Couchbase bucket.
        id_field: Source ID field. Otherwise preserve _id or generate stable IDs.
        namespace: Stable source identity. Required to generate IDs for anonymous inputs.
        mode: create refuses nonempty targets. replace explicitly permits clearing
            selected collections. upsert replaces by ID.
        split: Split name or list. None selects all available splits.
        splits: preserve adds split suffixes. merge concatenates into one collection.
        json_mode: plain preserves wrappers. extended uses loads_query_json.
        naive_datetimes: error rejects naive Python datetimes. utc treats them as UTC.
        decimal_mode: error rejects Couchbase decimals. string preserves their text.
        indexes: Optional named native index profile from the manifest.
        batch_size: Maximum documents buffered and progress callback interval.
        on_progress: Synchronous callback receiving a snapshot after each acknowledged batch.

    Returns:
        Source information, conversion counts and acknowledged writes by destination and split.

    Raises:
        ValueError: Invalid options, manifest or destination plan before database writes.
        LoadDataError: Failure during loading. The result attribute contains partial progress.

    This is not an atomic operation. Errors can leave created resources and partial
    data. Do not modify sources or destinations concurrently. No automatic retries,
    rollback or resume are provided. Replacement preserves existing indexes.
    """
    start = perf_counter()
    for value, allowed, label in [
        (mode, ("create", "replace", "upsert"), "mode"),
        (splits, ("preserve", "merge"), "splits"),
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
    conn = connection(target)
    backend = "couchbase" if isinstance(conn, CouchbaseConnection) else "mongodb"
    bucket = bucket or getattr(target, "bucket", None)
    plans, profiles = prepare(source, manifest, collection, namespace, split, splits)
    destinations = {}
    for plan in plans:
        spec = plan["spec"]
        root = (
            spec.get("bucket", bucket) if backend == "couchbase" else spec.get("database", database)
        )
        if backend == "mongodb" and (root is None or root == ""):
            raise ValueError(
                "MongoDB requires a destination database. Specify --database NAME in the CLI "
                'or database="NAME" in Python, or set database in the manifest collection.'
            )
        dest = (
            name(root),
            name(spec.get("scope", scope)) if backend == "couchbase" else None,
            name(plan["collection"]),
        )
        plan["destination"] = dest
        logical_key = (plan["logical"], plan["split"] if splits == "preserve" else None)
        if dest in destinations and destinations[dest]["logical_key"] != logical_key:
            raise ValueError("Two logical sources map to the same destination")
        destinations[dest] = dict(
            logical_key=logical_key,
            quota=spec.get("bucket_memory_mb", bucket_memory_mb),
        )
    bucket_quotas = {}
    if backend == "couchbase":
        for dest, options in destinations.items():
            quota = options["quota"]
            if quota is not None and (type(quota) is not int or quota < 100):
                raise ValueError("bucket_memory_mb must be an integer of at least 100")
            if dest[0] in bucket_quotas and bucket_quotas[dest[0]] != quota:
                raise ValueError("Conflicting quotas for one Couchbase bucket")
            bucket_quotas[dest[0]] = quota
    definitions = []
    if indexes is not None:
        if indexes not in profiles or backend not in profiles[indexes]:
            raise ValueError("Index profile is absent for the selected backend")
        definitions = profiles[indexes][backend]
        if not isinstance(definitions, list):
            raise ValueError("Index definitions must be a list")
        for definition in definitions:
            if not isinstance(definition, dict) or set(definition) - {
                "collection",
                "name",
                "keys",
                "options",
            }:
                raise ValueError("Invalid index definition fields")
            name(definition["name"])
            if definition["collection"] not in {p["logical"] for p in plans}:
                raise ValueError("Index profile refers to an unselected collection")
            if not definition.get("keys"):
                raise ValueError("Index requires keys")
            options = definition.get("options", {})
            if not isinstance(options, dict) or set(options) & {"name", "key", "keys"}:
                raise ValueError("Index options cannot override name or keys")
            if backend == "mongodb":
                from pymongo import IndexModel

                IndexModel(
                    [tuple(pair) for pair in definition["keys"]], name=definition["name"], **options
                )
            if backend == "couchbase":
                for key in definition["keys"]:
                    name(key)
                if definition.get("options"):
                    raise ValueError("Couchbase index options are not supported in this version")
    result = LoadDataResult(
        backend,
        sources=[p["info"] for p in plans],
        settings={
            "mode": mode,
            "splits": splits,
            "split": split,
            "json_mode": json_mode,
            "naive_datetimes": naive_datetimes,
            "decimal_mode": decimal_mode,
            "namespace": namespace,
            "id_field": id_field,
            "indexes": indexes,
        },
    )
    writer = None
    context = "destination preparation"
    try:
        writer = CouchbaseWriter(conn) if backend == "couchbase" else MongoWriter(conn)
        for dest, options in destinations.items():
            occupied = writer.preflight(dest, options["quota"])
            if occupied and mode == "create":
                raise ValueError("create requires absent or empty collections")
        for dest, options in destinations.items():
            args = {"quota": options["quota"]} if backend == "couchbase" else {}
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
                        field = plan["spec"].get("id_field", id_field)
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
        context = "index creation"
        for dest in destinations:
            logical = destinations[dest]["logical_key"][0]
            writer.indexes(dest, [d for d in definitions if d["collection"] == logical])
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
