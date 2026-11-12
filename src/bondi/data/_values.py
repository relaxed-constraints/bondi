"""Explicit document conversion and stable IDs."""

import hashlib
import json
import math
from datetime import UTC, date, datetime
from decimal import Decimal

from bson import BSON, Decimal128, ObjectId, json_util

SAFE_INTEGER = 2**53 - 1


def convert(value, backend, settings, counts, path="$", *, decoded=False):
    def record(kind):
        counts[kind] = counts.get(kind, 0) + 1

    if isinstance(value, dict):
        if any(not isinstance(k, str) or "\0" in k for k in value):
            raise ValueError(f"{path}: document keys must be strings without null characters")
        return {
            k: convert(v, backend, settings, counts, f"{path}.{k}", decoded=decoded)
            for k, v in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [
            convert(v, backend, settings, counts, f"{path}[{i}]", decoded=decoded)
            for i, v in enumerate(value)
        ]
    if isinstance(value, datetime):
        if value.tzinfo is None:
            if not decoded and settings["naive_datetimes"] != "utc":
                raise ValueError(f'{path}: naive datetime requires naive_datetimes="utc"')
            value = value.replace(tzinfo=UTC)
        value = value.astimezone(UTC)
        value = value.replace(microsecond=(value.microsecond // 1000) * 1000)
        record("datetime")
        return (
            value
            if backend == "mongodb"
            else value.isoformat(timespec="milliseconds").replace("+00:00", "Z")
        )
    if isinstance(value, date):
        record("date")
        return value.isoformat()
    if isinstance(value, ObjectId):
        if backend == "couchbase":
            record("objectid")
            return str(value)
        return value
    if isinstance(value, (Decimal, Decimal128)):
        decimal = value.to_decimal() if isinstance(value, Decimal128) else value
        if not decimal.is_finite():
            raise ValueError(f"{path}: nonfinite decimal is unsupported")
        if backend == "mongodb":
            try:
                return Decimal128(decimal)
            except Exception:
                raise ValueError(f"{path}: decimal cannot be represented as Decimal128") from None
        if settings["decimal_mode"] == "string":
            record("decimal_string")
            return str(decimal)
        raise ValueError(f'{path}: decimal requires decimal_mode="string" for Couchbase')
    if value is None or type(value) in (str, bool):
        return value
    if isinstance(value, int):
        limit = SAFE_INTEGER if backend == "couchbase" else 2**63 - 1
        lower = -limit if backend == "couchbase" else -(2**63)
        if not lower <= value <= limit:
            raise ValueError(f"{path}: integer exceeds the destination exact range")
        return value
    if type(value) is float:
        if not math.isfinite(value):
            raise ValueError(f"{path}: nonfinite float is unsupported")
        return value
    if backend == "mongodb":
        try:
            BSON.encode({"v": value})
            return value
        except Exception:
            pass
    raise ValueError(f"{path}: unsupported type {type(value).__name__}")


def identity(value):
    # Keep source types distinct in Couchbase keys and duplicate detection.
    if isinstance(value, bool) or not isinstance(value, (str, int, ObjectId)):
        raise ValueError("document IDs must be strings, integers or ObjectIds")
    if isinstance(value, int) and not -(2**63) <= value < 2**63:
        raise ValueError("integer document ID exceeds BSON range")
    if isinstance(value, int):
        value = int(value)  # BSON Int64 and Python int identify the same numeric document ID.
    return json_util.dumps(value, json_options=json_util.CANONICAL_JSON_OPTIONS)


def document_key(value):
    return "bondi:" + hashlib.sha256(identity(value).encode()).hexdigest()


def generated_id(namespace, collection, split, shard, row):
    if not namespace:
        raise ValueError("namespace is required when a source document has no ID")
    parts = [namespace, collection, split, shard, row]
    return "gen:" + hashlib.sha256(json.dumps(parts).encode()).hexdigest()[:24]
