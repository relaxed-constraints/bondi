"""Source plans and streaming readers. No database operations occur here."""

import csv
import hashlib
import json
from collections.abc import Mapping
from importlib.resources import files
from pathlib import Path

from bondi.mongodb import loads_query_json

# Resolve this revision once when preparing a load and record the exact commit.
CATALOG = {
    "demo": {"description": "Eight fictional businesses", "collection": "business"},
    **{
        name: {
            "description": f"JSynth {name} dataset",
            "repo_id": "origami-ml/jsynth-data",
            "config": name,
            "collection": name,
            "revision": "9af20c2698454dd33403c993501f5e1c0007643a",
        }
        for name in ("adult", "diabetes", "electric_vehicles")
    },
}


def list_datasets() -> dict[str, dict]:
    """Return catalogue names and descriptions without downloading data."""
    return {name: dict(info) for name, info in CATALOG.items()}


def dataset_info(name: str) -> dict:
    """Return catalogue metadata for one dataset. Unknown names raise ValueError."""
    if name not in CATALOG:
        raise ValueError(f"Unknown dataset: {name}")
    return dict(CATALOG[name])


def optional(module):
    try:
        return __import__(module)
    except ImportError:
        raise ImportError("Install bondi[data] to read this source format") from None


def checked_events(ijson, handle):
    objects = []
    for prefix, event, value in ijson.parse(handle, use_float=True):
        if event == "start_map":
            objects.append(set())
        elif event == "map_key":
            if value in objects[-1]:
                raise ValueError("duplicate JSON key")
            objects[-1].add(value)
        elif event == "end_map":
            objects.pop()
        yield prefix, event, value


def decode(text, mode):
    if mode == "extended":
        return loads_query_json(text)

    def pairs(items):
        result = {}
        for k, v in items:
            if k in result:
                raise ValueError("duplicate JSON key")
            result[k] = v
        return result

    def constant(_):
        raise ValueError("nonfinite JSON literal")

    return json.loads(text, object_pairs_hook=pairs, parse_constant=constant)


def records(source, mode):
    if not isinstance(source, (str, Path)):
        yield from source
        return
    path = Path(source)
    if path.suffix.lower() == ".jsonl":
        with path.open() as handle:
            for line in handle:
                if line.strip():
                    yield decode(line, mode)
    elif path.suffix.lower() == ".json":
        # Arrays are streamed. Single JSON objects are one document.
        ijson = optional("ijson")
        with path.open("rb") as handle:
            first = next(
                (
                    chr(c)
                    for chunk in iter(lambda: handle.read(4096), b"")
                    for c in chunk
                    if not chr(c).isspace()
                ),
                "",
            )
            handle.seek(0)
            for row in ijson.items(checked_events(ijson, handle), "item" if first == "[" else ""):
                yield decode(json.dumps(row), mode)
    elif path.suffix.lower() == ".csv":
        with path.open(newline="") as handle:
            reader = csv.DictReader(handle)
            if not reader.fieldnames or len(set(reader.fieldnames)) != len(reader.fieldnames):
                raise ValueError("CSV requires unique column names")
            for row in reader:
                if None in row or any(v is None for v in row.values()):
                    raise ValueError("CSV row does not match its header")
                yield row
    elif path.suffix.lower() == ".parquet":
        optional("pyarrow")
        import pyarrow.parquet as pq

        for batch in pq.ParquetFile(path).iter_batches(batch_size=1024):
            yield from batch.to_pylist()
    else:
        raise ValueError("Supported file formats: csv, json, jsonl, parquet")


def file_info(source):
    if not isinstance(source, (str, Path)):
        return {"kind": "iterable"}
    path = Path(source)
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return {"kind": "file", "file": path.name, "sha256": digest.hexdigest()}


def prepare(source, manifest, collection, namespace, split, splits):
    """Return logical source specifications and optional index profiles."""
    profiles = {}
    base = Path.cwd()
    if manifest is not None:
        if source is not None:
            raise ValueError("Use source or manifest, not both")
        if isinstance(manifest, Mapping):
            spec = dict(manifest)
        else:
            path = Path(manifest)
            base = path.resolve().parent
            spec = decode(path.read_text(), "plain")
        if set(spec) - {"version", "namespace", "collections", "index_profiles"}:
            raise ValueError("Unknown manifest fields")
        if (
            type(spec.get("version")) is not int
            or spec["version"] != 1
            or not isinstance(spec.get("collections"), dict)
        ):
            raise ValueError("Manifest requires version=1 and collections mapping")
        namespace = namespace or spec.get("namespace")
        if not namespace:
            raise ValueError("Manifest requires a namespace")
        profiles = spec.get("index_profiles", {})
        entries = spec["collections"]
    elif isinstance(source, str) and source in CATALOG:
        info = dataset_info(source)
        namespace = namespace or f"bondi:{source}"
        collection = collection or info["collection"]
        if source == "demo":
            entries = {
                collection: {
                    "source": json.loads(
                        files("bondi.deployment").joinpath("business.json").read_text()
                    ),
                    "id_field": "business_id",
                }
            }
        else:
            entries = {collection: {"hf": info}}
    elif isinstance(source, Mapping):
        # HF DatasetDict is a split mapping, not a collection mapping.
        if type(source).__name__ in ("DatasetDict", "IterableDatasetDict"):
            if not collection:
                raise ValueError("collection is required for a split dataset")
            entries = {collection: {"splits": source}}
        else:
            entries = {name: {"source": rows} for name, rows in source.items()}
    else:
        if not collection or source is None:
            raise ValueError("source and collection are required")
        declared_split = getattr(source, "split", None)
        if declared_split is not None and type(source).__module__.startswith("datasets."):
            entries = {collection: {"splits": {str(declared_split): source}}}
        else:
            entries = {collection: {"source": source}}
    selected = [split] if isinstance(split, str) else split
    if selected is not None and (not selected or len(set(selected)) != len(selected)):
        raise ValueError("split selection must be nonempty and distinct")
    plans = []
    for logical, spec in entries.items():
        if not isinstance(spec, dict):
            raise ValueError("Each manifest collection requires an object")
        allowed = {
            "source",
            "splits",
            "hf",
            "id_field",
            "database",
            "bucket",
            "scope",
            "bucket_memory_mb",
            "collection",
        }
        if set(spec) - allowed:
            raise ValueError("Unknown collection manifest fields")
        if sum(key in spec for key in ("source", "splits", "hf")) != 1:
            raise ValueError("Each collection needs exactly one source, splits or hf field")
        revision = None
        if "hf" in spec:
            hf = spec["hf"]
            hub = optional("huggingface_hub")
            revision = (
                hub.HfApi().dataset_info(hf["repo_id"], revision=hf.get("revision", "main")).sha
            )
            if hf["repo_id"] == "origami-ml/jsynth-data":
                sources = {
                    part: hub.hf_hub_download(
                        hf["repo_id"],
                        f"{hf['config']}/{part}.jsonl",
                        repo_type="dataset",
                        revision=revision,
                    )
                    for part in ("train", "test")
                    if selected is None or part in selected
                }
            else:
                datasets = optional("datasets")
                sources = datasets.load_dataset(
                    hf["repo_id"], name=hf.get("config"), revision=revision, streaming=True
                )
            namespace = namespace or f"hf:{hf['repo_id']}:{hf.get('config', 'default')}"
        elif "splits" in spec:
            sources = spec["splits"]
        else:
            sources = {None: spec["source"]}
        if selected is not None and any(part not in sources for part in selected):
            raise ValueError(f"{logical}: requested split is absent")
        # Manifest insertion order is explicit. Other inputs use sorted split names.
        order = list(sources) if manifest is not None else sorted(sources, key=lambda x: x or "")
        for part in order:
            if selected is not None and part not in selected:
                continue
            raw = sources[part]
            shards = (
                [raw]
                if not isinstance(raw, (list, tuple))
                or not raw
                or not all(isinstance(x, (str, Path)) for x in raw)
                else raw
            )
            for shard_index, shard in enumerate(shards):
                if isinstance(shard, (str, Path)):
                    shard = base / shard
                base_collection = spec.get("collection", logical)
                target = (
                    base_collection
                    if part is None or splits == "merge"
                    else f"{base_collection}_{part}"
                )
                info = file_info(shard)
                info.update(collection=logical, split=part, shard=shard_index, namespace=namespace)
                if revision:
                    info.update(revision=revision, repo_id=spec["hf"]["repo_id"])
                plans.append(
                    dict(
                        logical=logical,
                        collection=target,
                        split=part,
                        shard=shard_index,
                        source=shard,
                        namespace=namespace,
                        spec=spec,
                        info=info,
                    )
                )
    if not plans:
        raise ValueError("No collections selected")
    return plans, profiles
