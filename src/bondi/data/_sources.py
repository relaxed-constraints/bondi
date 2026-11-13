"""Source plans and streaming readers. No database operations occur here."""

import csv
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

from bondi.mongodb import loads_query_json

# Resolve this revision once when preparing a load and record the exact commit.
CATALOG = {
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


def hf_revision(repo_id, revision):
    """Resolve a repository revision once before loading its configurations."""
    return (
        optional("huggingface_hub").HfApi().dataset_info(repo_id, revision=revision or "main").sha
    )


def hf_configs(repo_id, revision):
    return sorted(optional("datasets").get_dataset_config_names(repo_id, revision=revision))


def hf_plans(repo_id, dataset, revision, split, namespace):
    library = optional("datasets")
    available = library.get_dataset_split_names(repo_id, dataset, revision=revision)
    selected = available if split is None else ([split] if isinstance(split, str) else list(split))
    if not selected or len(set(selected)) != len(selected):
        raise ValueError("Select at least one distinct split")
    if any(part not in available for part in selected):
        raise ValueError(f"{dataset}: requested split is absent. Available splits: {available}")
    namespace = namespace or f"hf:{repo_id}:{dataset}"
    plans = []
    for part in sorted(selected):
        source = library.load_dataset(
            repo_id, name=dataset, revision=revision, split=part, streaming=True
        )
        plans.append(
            source_plan(
                source,
                dataset,
                namespace,
                part,
                {
                    "kind": "huggingface",
                    "repo_id": repo_id,
                    "dataset": dataset,
                    "revision": revision,
                },
            )
        )
    return plans


def source_plan(source, logical, namespace, split=None, info=None):
    info = dict(info if info is not None else file_info(source))
    info.update(collection=logical, split=split, shard=0, namespace=namespace)
    return dict(
        source=source, logical=logical, split=split, shard=0, namespace=namespace, info=info
    )


def decode_document(value):
    """Decode JSON wrappers while leaving existing Python/BSON values unchanged."""
    if isinstance(value, dict):
        if any(not isinstance(key, str) for key in value):
            raise ValueError("document keys must be strings")
        try:
            text = json.dumps(value)
        except TypeError:
            return {key: decode_document(item) for key, item in value.items()}
        return _json_dates_utc(loads_query_json(text))
    if isinstance(value, (list, tuple)):
        return [decode_document(item) for item in value]
    return value


def _json_dates_utc(value):
    # Only values decoded from JSON reach here. Existing Python datetimes do not.
    if isinstance(value, datetime) and value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    if isinstance(value, dict):
        return {key: _json_dates_utc(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_dates_utc(item) for item in value]
    return value
