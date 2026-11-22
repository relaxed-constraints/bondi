"""Project observed field types into JSON Schema Draft 2020-12."""

from collections.abc import Mapping
from typing import Any

from .schema import FieldSchema, Schema, _display

_JSON_TYPES = {
    "null": "null",
    "str": "string",
    "bool": "boolean",
    "int": "integer",
    "Int64": "integer",
    "float": "number",
}


def _closed_object(**properties: dict) -> dict:
    return {
        "type": "object",
        "properties": properties,
        "required": list(properties),
        "additionalProperties": False,
    }


def _canonical_branches(kind: str) -> list[dict]:
    string = {"type": "string"}
    tags = {
        "int": ("$numberInt", "$numberLong"),
        "Int64": ("$numberLong",),
        "float": ("$numberDouble",),
        "ObjectId": ("$oid",),
    }
    if kind in tags:
        return [_closed_object(**{tag: string}) for tag in tags[kind]]
    if kind == "datetime":
        return [_closed_object(**{"$date": _closed_object(**{"$numberLong": string})})]
    if kind in {"Binary", "bytes", "UUID"}:
        return [_closed_object(**{"$binary": _closed_object(base64=string, subType=string)})]
    return []


def _object(fields: Mapping[str, FieldSchema], representation: str) -> dict[str, Any]:
    result: dict[str, Any] = {"type": "object"}
    if fields:
        result["properties"] = {key: _field(field, representation) for key, field in fields.items()}
        required = [key for key, field in fields.items() if field.missing_count == 0]
        if required:
            result["required"] = required
    return result


def _field(field: FieldSchema, representation: str) -> dict:
    branches = []
    primitives = []
    for kind, observed in field.types.items():
        if kind == "object":
            branches.append(_object(observed.fields, representation))
        elif kind == "array":
            array = {"type": "array"}
            if observed.elements.types:
                array["items"] = _field(observed.elements, representation)
            branches.append(array)
        elif representation == "canonical_extended_json" and (encoded := _canonical_branches(kind)):
            for branch in encoded:
                if branch not in branches:
                    branches.append(branch)
        elif kind in _JSON_TYPES:
            primitive = _JSON_TYPES[kind]
            if primitive not in primitives:
                primitives.append(primitive)
        else:
            raise ValueError(
                f"Cannot represent {kind} at {_display(field.path)!r} in {representation}"
            )

    if "number" in primitives and "integer" in primitives:
        primitives.remove("integer")
    if primitives:
        branches.append({"type": primitives[0] if len(primitives) == 1 else primitives})
    return branches[0] if len(branches) == 1 else {"anyOf": branches}


def export(schema: Schema, representation: str) -> dict:
    if representation not in ("json", "canonical_extended_json"):
        raise ValueError(f"Unknown JSON Schema representation: {representation!r}")
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        **_object(schema.fields, representation),
    }
