"""Private shared encoding for versioned MongoDB query envelopes."""

import json
from typing import Any

from bson import json_util


def _same_document_structure(original: Any, decoded: Any) -> bool:
    """Detect literal documents consumed as Extended JSON scalar wrappers."""
    if isinstance(original, dict):
        return (
            isinstance(decoded, dict)
            and list(original) == list(decoded)
            and all(_same_document_structure(v, decoded[k]) for k, v in original.items())
        )
    if isinstance(original, (list, tuple)):
        return (
            isinstance(decoded, list)
            and len(original) == len(decoded)
            and all(_same_document_structure(a, b) for a, b in zip(original, decoded))
        )
    return True


def _dump_bson(value: Any) -> str:
    """Encode without silently consuming literal documents as BSON wrappers."""
    text = json_util.dumps(
        value,
        json_options=json_util.CANONICAL_JSON_OPTIONS,
        separators=(",", ":"),
        ensure_ascii=True,
    )
    # Extended JSON reserves document shapes for type wrappers. Never silently
    # turn a native predicate/literal document into a different representation.
    decoded = json_util.loads(text, json_options=json_util.CANONICAL_JSON_OPTIONS)
    reencoded = json_util.dumps(
        decoded,
        json_options=json_util.CANONICAL_JSON_OPTIONS,
        separators=(",", ":"),
        ensure_ascii=True,
    )
    if text != reencoded or not _same_document_structure(value, decoded):
        raise ValueError("Query contains a document ambiguous with an Extended JSON type wrapper")
    return text


def _dump_envelope(envelope: dict[str, Any], bson_fields: tuple[str, ...]) -> str:
    """Encode native BSON payloads separately from ordinary JSON metadata/options."""
    encoded = dict(envelope)
    for field in bson_fields:
        encoded[field] = json.loads(_dump_bson(envelope[field]))
    return json.dumps(encoded, ensure_ascii=True, allow_nan=False, separators=(",", ":"))


def _load_envelope(
    text: str, kind: str, payload_fields: set[str], bson_fields: tuple[str, ...]
) -> tuple[dict, dict]:
    """Decode and check envelope metadata; query classes validate their payloads."""
    fields = {"format_version", "query_kind", "target"} | payload_fields
    if not isinstance(text, str):
        raise TypeError("text must be a string")

    def unique_object(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"Duplicate JSON key: {key}")
            result[key] = value
        return result

    raw = json.loads(text, object_pairs_hook=unique_object)
    if not isinstance(raw, dict) or set(raw) != fields:
        raise ValueError("Query envelope must contain exactly the version-1 fields")
    data = dict(raw)
    for field in bson_fields:
        data[field] = json_util.loads(
            json.dumps(raw[field]), json_options=json_util.CANONICAL_JSON_OPTIONS
        )
    version = data["format_version"]
    if isinstance(version, bool) or not isinstance(version, int) or version != 1:
        raise ValueError("Unsupported format_version")
    if data["query_kind"] != kind:
        raise ValueError("Unsupported query_kind")
    target = data["target"]
    if not isinstance(target, dict) or set(target) != {"database", "collection"}:
        raise ValueError("target must contain exactly database and collection")
    return raw, data


def _check_canonical_payload(raw: dict, encoded_text: str, fields: tuple[str, ...]) -> None:
    """Require the same canonical BSON payload representation after reconstruction."""
    encoded = json.loads(encoded_text)
    for field in fields:
        if json.dumps(raw[field], separators=(",", ":")) != json.dumps(
            encoded[field], separators=(",", ":")
        ):
            raise ValueError(f"{field} must use unambiguous Canonical Extended JSON")
