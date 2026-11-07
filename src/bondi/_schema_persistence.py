"""Version-1 schema snapshots; only scalar payloads use Extended JSON."""

import json
import os
import tempfile
from collections import Counter
from datetime import UTC, date, datetime, time
from decimal import Decimal, DecimalException
from pathlib import Path
from uuid import UUID

from bson import Binary, Decimal128, Int64, json_util
from bson.binary import UuidRepresentation

from .schema import ARRAY_ELEMENT, FieldSchema, Schema, TypeSchema, _type_name

_OPTIONS = json_util.CANONICAL_JSON_OPTIONS.with_options(tz_aware=True, tzinfo=UTC)
_NAMES = {
    "object",
    "array",
    "null",
    "str",
    "bool",
    "int",
    "float",
    "bytes",
    "datetime",
    "date",
    "Decimal",
    "UUID",
    "ObjectId",
    "Int64",
    "Binary",
}


def _encode(value):
    if type(value) is datetime:
        return {"iso": value.isoformat(), "fold": value.fold}
    if type(value) is date:
        value = datetime.combine(value, time(), UTC)
    elif type(value) is Decimal:
        try:
            encoded = Decimal128(value)
            if encoded.to_decimal().as_tuple() != value.as_tuple():
                return str(value)
            value = encoded
        except (DecimalException, ValueError, OverflowError):
            return str(value)
    elif type(value) is UUID:
        value = Binary.from_uuid(value, UuidRepresentation.STANDARD)
    return json.loads(json_util.dumps(value, json_options=_OPTIONS))


def _canonical(value):
    return json.dumps(value, sort_keys=True, allow_nan=False, ensure_ascii=True)


def _decode(name, payload):
    if name == "datetime":
        _keys(payload, {"iso", "fold"})
        if type(payload["iso"]) is not str or type(payload["fold"]) is not int:
            raise ValueError("Invalid datetime payload")
        value = datetime.fromisoformat(payload["iso"]).replace(fold=payload["fold"])
    elif name == "Decimal" and type(payload) is str:
        value = Decimal(payload)
    else:
        value = json_util.loads(json.dumps(payload), json_options=_OPTIONS)
        if name == "date" and type(value) is datetime:
            if value.timetz().replace(tzinfo=None) != time():
                raise ValueError("Date must represent midnight UTC")
            value = value.date()
        elif name == "Decimal" and type(value) is Decimal128:
            value = value.to_decimal()
        elif name == "UUID" and type(value) is Binary:
            value = value.as_uuid(UuidRepresentation.STANDARD)
        elif name == "Binary" and type(value) is bytes:
            value = Binary(value, 0)
        elif name == "int" and type(value) is Int64:
            value = int(value)
    if _type_name(value) != name or _canonical(_encode(value)) != _canonical(payload):
        raise ValueError(f"Invalid or noncanonical {name} payload")
    return value


def _keys(record, expected):
    if type(record) is not dict or set(record) != expected:
        raise ValueError(f"Expected members: {sorted(expected)}")


def _count(value, minimum=0):
    if type(value) is not int or value < minimum:
        raise ValueError(f"Expected integer count >= {minimum}")
    return value


def _list(value):
    if type(value) is not list:
        raise ValueError("Expected a list")
    return value


def _field_record(node, mode, name=None):
    record = {"count": node.count, "types": []}
    if name is not None:
        record["name"] = name
    for variant in node.types.values():
        item = {"name": variant.name, "count": variant.count}
        if variant.name == "object":
            item["fields"] = [
                _field_record(child, mode, key) for key, child in variant.fields.items()
            ]
        elif variant.name == "array":
            item["elements"] = _field_record(variant.elements, mode)
        elif mode != "none":
            values = [
                {"value": _encode(value), **({"count": count} if mode == "full" else {})}
                for value, count in (
                    variant.value_counts.items()
                    if mode == "full"
                    else ((value, None) for value in variant.values)
                )
            ]
            if mode == "distinct":
                values.sort(key=_canonical)
            item["values"] = values
        record["types"].append(item)
    return record


def _restore(record, cls):
    _keys(record, {"format", "format_version", "document_count", "value_mode", "fields"})
    if record["format"] != "bondi.schema" or type(record["format_version"]) is not int:
        raise ValueError("Invalid schema format")
    if record["format_version"] != 1:
        raise ValueError("Unsupported schema format_version")
    schema = cls(values=record["value_mode"])
    schema._count = _count(record["document_count"])

    def fields(records, parent, prefix, depth):
        for entry in _list(records):
            node = field(entry, parent, prefix, depth)
            name = entry["name"]
            if name in parent._fields:
                raise ValueError("Duplicate field name")
            parent._fields[name] = node

    def field(entry, parent, prefix, depth):
        if depth > 128 and not (
            depth == 129 and parent is None and entry == {"count": 0, "types": []}
        ):
            raise ValueError("Schema may nest at most 128 levels")
        _keys(entry, {"count", "types"} | ({"name"} if parent is not None else set()))
        if parent is not None:
            if type(entry["name"]) is not str:
                raise ValueError("Field names must be strings")
            path = prefix + (entry["name"],)
        else:
            path = prefix + (ARRAY_ELEMENT,)
        node = FieldSchema(path, _count(entry["count"], int(parent is not None)), parent)
        if parent is not None and node.count > node.parent_count:
            raise ValueError("Field count exceeds parent count")
        schema._flat[path] = node
        for item in _list(entry["types"]):
            if type(item) is not dict or type(item.get("name")) is not str:
                raise ValueError("Invalid type record")
            name = item["name"]
            if name not in _NAMES or name in node._types:
                raise ValueError("Unknown or duplicate type")
            extra = (
                {"fields"}
                if name == "object"
                else {"elements"}
                if name == "array"
                else ({"values"} if schema.value_mode != "none" else set())
            )
            _keys(item, {"name", "count"} | extra)
            variant = TypeSchema(name, _count(item["count"], 1), _mode=schema.value_mode)
            node._types[name] = variant
            if name == "object":
                fields(item["fields"], variant, path, depth + 1)
            elif name == "array":
                variant.elements = field(item["elements"], None, path, depth + 1)
            elif schema.value_mode != "none":
                retained = Counter() if schema.value_mode == "full" else set()
                for value_record in _list(item["values"]):
                    _keys(
                        value_record,
                        {"value", "count"} if schema.value_mode == "full" else {"value"},
                    )
                    value = _decode(name, value_record["value"])
                    if value in retained:
                        raise ValueError("Duplicate retained value")
                    if schema.value_mode == "full":
                        retained[value] = _count(value_record["count"], 1)
                    else:
                        retained.add(value)
                if not retained or len(retained) > variant.count:
                    raise ValueError("Invalid retained value count")
                if schema.value_mode == "full" and sum(retained.values()) != variant.count:
                    raise ValueError("Value frequencies do not sum to type count")
                variant._retained = retained
        if sum(t.count for t in node.types.values()) != node.count:
            raise ValueError("Type counts do not sum to field count")
        return node

    fields(record["fields"], schema, (), 1)
    return schema


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate JSON key: {key}")
        result[key] = value
    return result


def _constant(value):
    raise ValueError(f"Invalid JSON constant: {value}")


def load(path, cls=Schema):
    try:
        with Path(path).open("r", encoding="utf-8") as source:
            record = json.load(source, object_pairs_hook=_pairs, parse_constant=_constant)
        return _restore(record, cls)
    except (
        ValueError,
        TypeError,
        KeyError,
        OverflowError,
        RecursionError,
        DecimalException,
    ) as error:
        raise ValueError(f"Invalid schema snapshot: {error}") from error


def save(schema, path):
    destination = Path(path)
    temporary = None
    try:
        record = {
            "format": "bondi.schema",
            "format_version": 1,
            "document_count": schema.document_count,
            "value_mode": schema.value_mode,
            "fields": [
                _field_record(node, schema.value_mode, name) for name, node in schema.fields.items()
            ],
        }
        # Validate before replacing any artifact, including externally modified observations.
        _restore(record, Schema)
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=destination.parent,
            prefix=f".{destination.name}.",
            suffix=".tmp",
            delete=False,
        ) as output:
            temporary = Path(output.name)
            json.dump(record, output, ensure_ascii=True, allow_nan=False, indent=2)
            output.write("\n")
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, destination)
    except (ValueError, TypeError, OverflowError, RecursionError, DecimalException) as error:
        raise ValueError(f"Cannot save schema snapshot: {error}") from error
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
