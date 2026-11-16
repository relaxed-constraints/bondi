"""Offline index definitions and versioned persistence."""

import hashlib
import json
import re
from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import ClassVar

from bson import json_util


def _name(value):
    if not isinstance(value, str) or not value or "\0" in value:
        raise ValueError("Names must be nonempty strings without null characters")


class _Definition:
    def validate(self):
        """Validate structure, not server acceptance or data semantics."""
        if self.name is not None:
            _name(self.name)
        if not isinstance(self.keys, tuple) or not self.keys:
            raise ValueError("keys must be a nonempty tuple of (key, direction) tuples")
        seen = set()
        for pair in self.keys:
            if not isinstance(pair, tuple) or len(pair) != 2:
                raise ValueError("Each key must be a (key, direction) tuple")
            key, direction = pair
            _name(key)
            if self.kind == "field" and not re.fullmatch(
                r"[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)*", key
            ):
                raise ValueError("Shared keys must be simple dotted field paths")
            if type(direction) is not int or direction not in (1, -1):
                raise ValueError("Directions must be integer 1 or -1")
            if key in seen:
                raise ValueError("Duplicate index key")
            seen.add(key)

    def to_dict(self):
        """Return an independent JSON-compatible definition, with BSON predicates encoded."""
        self.validate()
        data = {"kind": self.kind, "name": self.name, "keys": [list(k) for k in self.keys]}
        for option in self._options:
            value = getattr(self, option)
            if option == "partial_filter" and value is not None:
                value = json.loads(
                    json_util.dumps(value, json_options=json_util.CANONICAL_JSON_OPTIONS)
                )
            data[option] = deepcopy(value)
        return data

    @classmethod
    def from_dict(cls, data):
        """Restore a definition; reject a different kind or unknown options."""
        result = _from_dict(data)
        if type(result) is not cls:
            raise ValueError(f"Expected {cls.kind} index")
        return result

    def save(self, path):
        """Save a version-1 JSON file. No database operations are performed."""
        _write(path, {"format_version": 1, **self.to_dict()})

    @classmethod
    def load(cls, path):
        """Load a versioned file of this definition kind."""
        result = load_index(path)
        if type(result) is not cls:
            raise ValueError(f"Expected {cls.kind} index")
        return result

    @property
    def resolved_name(self):
        """Explicit name or deterministic name derived from the serialized definition."""
        data = self.to_dict()
        if self.name is not None:
            return self.name
        # Preserve nested predicate order: BSON document order can be meaningful.
        digest = hashlib.sha256(json.dumps(data, separators=(",", ":")).encode()).hexdigest()
        return "bondi_" + digest[:24]


@dataclass
class FieldIndex(_Definition):
    """Ordered field paths, interpreted using each backend's native semantics.

    Args:
        keys: Nonempty tuple of (simple dotted path, 1 or -1) tuples.
        name: Optional server index name; otherwise generated deterministically.

    Definitions are mutable and validated at construction, serialization and creation.
    Array traversal and missing-value behavior are not normalized across databases.
    """

    keys: tuple[tuple[str, int], ...]
    name: str | None = None
    kind: ClassVar[str] = "field"
    _options: ClassVar[tuple] = ()

    def __post_init__(self):
        self.validate()


def _from_dict(data):
    from bondi.couchbase.indexes import CouchbaseIndex
    from bondi.mongodb.indexes import MongoIndex

    if not isinstance(data, dict):
        raise TypeError("Index definition must be a dictionary")
    data = deepcopy(data)
    kind = data.pop("kind", "field")
    classes = {"field": FieldIndex, "mongodb": MongoIndex, "couchbase": CouchbaseIndex}
    if not isinstance(kind, str) or kind not in classes:
        raise ValueError(f"Unknown index kind: {kind!r}")
    cls = classes[kind]
    if "fields" in data:
        fields = data.pop("fields")
        if kind != "field" or "keys" in data or not isinstance(fields, list):
            raise ValueError("fields is a list shorthand for shared keys only")
        data["keys"] = [(field, 1) for field in fields]
    if set(data) - {"keys", "name", *cls._options}:
        raise ValueError("Unknown index options")
    keys = data.get("keys")
    if not isinstance(keys, (list, tuple)) or any(
        not isinstance(pair, (list, tuple)) for pair in keys
    ):
        raise ValueError("keys must be a sequence of pairs")
    data["keys"] = tuple(tuple(pair) for pair in keys)
    if kind == "mongodb" and data.get("partial_filter") is not None:
        data["partial_filter"] = json_util.loads(json.dumps(data["partial_filter"]))
    return cls(**data)


def _write(path, data):
    text = json.dumps(data, indent=2, ensure_ascii=False, allow_nan=False) + "\n"
    Path(path).write_text(text, encoding="utf-8")


def _read(path):
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("Expected a versioned index envelope")
    version = data.pop("format_version", None)
    if type(version) is not int or version != 1:
        raise ValueError("Unsupported index format version")
    return data


def load_index(path):
    """Load a FieldIndex, MongoIndex or CouchbaseIndex from a versioned JSON file."""
    data = _read(path)
    if "kind" not in data:
        raise ValueError("Index file must include a kind discriminator")
    return _from_dict(data)


class IndexSet(Mapping):
    """Ordered collection names mapped to lists of independent index definitions.

    Args:
        indexes (Mapping): Mapping of collection names to lists of definitions.

    Constructor inputs are deep-copied. Lists and definitions returned by lookup
    remain mutable. Duplicate explicit names within one collection are rejected.
    Iteration yields collection names; len() counts collections, not definitions.
    """

    def __init__(self, indexes):
        if not isinstance(indexes, Mapping):
            raise TypeError("indexes must be a mapping")
        self._indexes = deepcopy(dict(indexes))
        self.validate()

    def __getitem__(self, key):
        return self._indexes[key]

    def __iter__(self):
        return iter(self._indexes)

    def __len__(self):
        return len(self._indexes)

    def validate(self):
        """Validate every definition and per-collection explicit name uniqueness."""
        for target, definitions in self.items():
            _name(target)
            if not isinstance(definitions, list):
                raise TypeError("Each collection must map to a list of definitions")
            names = set()
            for index in definitions:
                if not isinstance(index, _Definition):
                    raise TypeError("Expected an index definition")
                index.validate()
                if index.name is not None:
                    if index.name in names:
                        raise ValueError(f"Duplicate index name for {target}: {index.name}")
                    names.add(index.name)

    def to_dict(self):
        """Return a canonical config mapping, without a file envelope."""
        self.validate()
        return {target: [index.to_dict() for index in indexes] for target, indexes in self.items()}

    @classmethod
    def from_dict(cls, data):
        """Parse a config mapping, including fields: [path, ...] shorthand."""
        if not isinstance(data, dict):
            raise TypeError("IndexSet configuration must be a dictionary")
        result = {}
        for target, definitions in data.items():
            if not isinstance(definitions, list):
                raise TypeError("Each collection must map to a list")
            result[target] = [_from_dict(index) for index in definitions]
        return cls(result)

    def save(self, path):
        """Save a versioned JSON index-set artifact."""
        _write(path, {"format_version": 1, "kind": "index_set", "indexes": self.to_dict()})

    @classmethod
    def load(cls, path):
        """Restore a versioned index set, offline."""
        data = _read(path)
        if set(data) != {"kind", "indexes"} or data["kind"] != "index_set":
            raise ValueError("Expected an index_set envelope")
        return cls.from_dict(data["indexes"])


class IndexCreationError(RuntimeError):
    """Batch creation failed after zero or more successful operations.

    Attributes:
        completed: Collection names mapped to confirmed index names.
        target: Collection name of the failed operation.
        position: Zero-based position in that collection's definition list.

    The failed operation may have created an index or left a build running.
    The original exception is available as __cause__. No rollback is attempted.
    """

    def __init__(self, completed, target, position):
        super().__init__(f"Index creation failed at {target}[{position}]")
        self.completed = deepcopy(completed)
        self.target = target
        self.position = position
