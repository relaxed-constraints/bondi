"""SQL++ text and JSON parameters for Couchbase."""

import hashlib
import json
import math
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any, ClassVar, Self


def _validate_json(value: Any, active: set[int]) -> None:
    """Accept plain JSON values without silently coercing keys or containers."""
    if value is None or type(value) in (str, bool, int):
        return
    if type(value) is float:
        if not math.isfinite(value):
            raise ValueError("JSON numbers must be finite")
        return
    if type(value) not in (dict, list):
        raise TypeError("Parameters must contain plain JSON values")
    identity = id(value)
    if identity in active:
        raise ValueError("Parameters must not contain circular references")
    active.add(identity)
    try:
        if type(value) is dict:
            if any(type(key) is not str for key in value):
                raise TypeError("JSON object keys must be strings")
            children = value.values()
        else:
            children = value
        for child in children:
            _validate_json(child, active)
    finally:
        active.remove(identity)


@dataclass
class CouchbaseQuery:
    """Describe SQL++ text and bindings without parsing or executing the statement.

    Mutable and unhashable. Parameter containers are deep-copied at construction.
    Later edits are not intercepted; validation runs explicitly, at construction,
    and before serialization or fingerprinting. Statement and context text are
    preserved exactly, including whitespace. No Couchbase SDK is required.

    Args:
        statement: Nonblank SQL++ text. Syntax, placeholder bindings and read-only
            behaviour are not checked, so invalid LLM candidates can be represented.
        named_parameters: Named JSON values, conventionally keyed without the $
            placeholder prefix. Names are preserved, not parsed or normalized.
        positional_parameters: Ordered JSON values for positional placeholders.
            Only one parameter style may be nonempty (a toolkit restriction).
        query_context: Optional nonblank native context string for name resolution.
            Its syntax is not parsed. None means no explicit context.

    Raises:
        TypeError: Fields have incorrect types or parameters contain non-JSON values.
        ValueError: Text is blank, both parameter styles are used, or parameters
            contain nonfinite floats or circular references.

    Examples:
        >>> query = CouchbaseQuery("SELECT $minimum AS stars", named_parameters={"minimum": 4})
        >>> restored = CouchbaseQuery.from_json(query.to_json())
        >>> restored.fingerprint() == query.fingerprint()
        True
    """

    backend: ClassVar[str] = "couchbase"

    statement: str
    named_parameters: dict[str, Any] = field(default_factory=dict)
    positional_parameters: list[Any] = field(default_factory=list)
    query_context: str | None = None

    def __post_init__(self) -> None:
        self.validate()
        self.named_parameters = deepcopy(self.named_parameters)
        self.positional_parameters = deepcopy(self.positional_parameters)

    def validate(self) -> None:
        """Check text and JSON bindings without modifying them or parsing SQL++.

        Plain dict/list containers, string keys, strings, booleans, integers,
        finite floats and None are accepted. Tuples, BSON-specific values and
        dates are rejected rather than converted. JSON validity does not guarantee
        server acceptance, including numeric range or precision support.

        Raises:
            TypeError: A field or nested parameter has an incorrect type.
            ValueError: Blank text, mixed parameter styles, nonfinite numbers or cycles.
        """
        for name, value in (("statement", self.statement), ("query_context", self.query_context)):
            if name == "query_context" and value is None:
                continue
            if not isinstance(value, str):
                raise TypeError(f"{name} must be a string")
            if not value.strip():
                raise ValueError(f"{name} must not be blank")
        if type(self.named_parameters) is not dict:
            raise TypeError("named_parameters must be a dictionary")
        if type(self.positional_parameters) is not list:
            raise TypeError("positional_parameters must be a list")
        if self.named_parameters and self.positional_parameters:
            raise ValueError("Only one parameter style may be nonempty")
        _validate_json(self.named_parameters, set())
        _validate_json(self.positional_parameters, set())

    def to_json(self) -> str:
        """Serialize a validated version-1 couchbase.sqlpp envelope as standard JSON.

        Includes defaults; preserves exact statement/context text, array order
        and parameter dictionary insertion order. Does not use BSON Extended JSON.
        Raises the same validation errors as validate().
        """
        self.validate()
        return json.dumps(
            {
                "format_version": 1,
                "query_kind": "couchbase.sqlpp",
                "statement": self.statement,
                "named_parameters": self.named_parameters,
                "positional_parameters": self.positional_parameters,
                "query_context": self.query_context,
            },
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        )

    @classmethod
    def from_json(cls, text: str) -> Self:
        """Load a version-1 SQL++ envelope and validate its fields.

        Rejects missing/extra fields, unknown versions or kinds, duplicate JSON
        keys, and nonfinite numeric values. Envelope order and formatting may vary;
        the exact statement string is retained.

        Raises:
            TypeError: Input or decoded fields have incorrect types.
            ValueError: Invalid JSON, envelope or query values.
        """
        if not isinstance(text, str):
            raise TypeError("text must be a string")

        def unique_object(pairs):
            result = {}
            for key, value in pairs:
                if key in result:
                    raise ValueError(f"Duplicate JSON key: {key}")
                result[key] = value
            return result

        def reject_constant(value):
            raise ValueError(f"Nonfinite JSON constant: {value}")

        data = json.loads(text, object_pairs_hook=unique_object, parse_constant=reject_constant)
        fields = {
            "format_version",
            "query_kind",
            "statement",
            "named_parameters",
            "positional_parameters",
            "query_context",
        }
        if not isinstance(data, dict) or set(data) != fields:
            raise ValueError("Query envelope must contain exactly the version-1 fields")
        if type(data["format_version"]) is not int or data["format_version"] != 1:
            raise ValueError("Unsupported format_version")
        if data["query_kind"] != "couchbase.sqlpp":
            raise ValueError("Unsupported query_kind")
        return cls(
            statement=data["statement"],
            named_parameters=data["named_parameters"],
            positional_parameters=data["positional_parameters"],
            query_context=data["query_context"],
        )

    def fingerprint(self) -> str:
        """Compute SHA-256 of the current validated serialized representation.

        Includes statement text, bindings, context, kind and version. Whitespace
        and comments inside SQL++ affect the digest, as does parameter dictionary
        order. No semantic normalization or deployment identity is implied.
        Recomputed on each call; raises the same errors as to_json().
        """
        return hashlib.sha256(self.to_json().encode("utf-8")).hexdigest()
