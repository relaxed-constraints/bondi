"""Observed schemas inferred from Python documents, without database access."""

from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from math import isfinite
from types import MappingProxyType
from typing import Any, Literal
from uuid import UUID

from bson import Binary, Int64, ObjectId


class _ArrayElement(Enum):
    ELEMENT = "[]"


ARRAY_ELEMENT = _ArrayElement.ELEMENT
"""Structural array-element marker for unambiguous tuple paths."""

Path = tuple[str | _ArrayElement, ...]
ValueMode = Literal["none", "distinct", "full"]
_SCALARS = {str, bool, int, float, bytes, datetime, date, Decimal, UUID, ObjectId, Int64, Binary}


def _type_name(value: Any) -> str:
    if isinstance(value, dict):
        return "object"
    if isinstance(value, list):
        return "array"
    if value is None:
        return "null"
    if type(value) not in _SCALARS:
        raise TypeError(f"Unsupported schema value type: {type(value).__name__}")
    if isinstance(value, float) and not isfinite(value):
        raise ValueError("Nonfinite numbers are not supported")
    if isinstance(value, Decimal) and not value.is_finite():
        raise ValueError("Nonfinite decimals are not supported")
    return type(value).__name__


def _validate(value: Any, active: set[int], depth: int = 0) -> None:
    if depth > 128:
        raise ValueError("Documents may nest at most 128 levels")
    kind = _type_name(value)
    if kind not in ("object", "array"):
        return
    identity = id(value)
    if identity in active:
        raise ValueError("Documents must not contain cycles")
    active.add(identity)
    try:
        if kind == "object":
            if any(not isinstance(key, str) for key in value):
                raise TypeError("Object keys must be strings")
            children = value.values()
        else:
            children = value
        for child in children:
            _validate(child, active, depth + 1)
    finally:
        active.remove(identity)


def _path(value: str | Path) -> Path:
    if isinstance(value, tuple):
        if not value or any(not isinstance(p, str) and p is not ARRAY_ELEMENT for p in value):
            raise ValueError("Paths must be nonempty tuples of strings and ARRAY_ELEMENT")
        return value
    if not isinstance(value, str):
        raise TypeError("Path must be a string or tuple")
    segments, token = [], []
    escaped = literal = False
    for char in value:
        if escaped:
            token.append(char)
            escaped = False
            literal = True
        elif char == "\\":
            escaped = True
        elif char == ".":
            text = "".join(token)
            segments.append(ARRAY_ELEMENT if text == "[]" and not literal else text)
            token, literal = [], False
        else:
            token.append(char)
    if escaped:
        raise ValueError("Path cannot end with an unpaired escape")
    text = "".join(token)
    segments.append(ARRAY_ELEMENT if text == "[]" and not literal else text)
    return tuple(segments)


def _display(path: Path) -> str:
    return ".".join(
        "[]"
        if p is ARRAY_ELEMENT
        else p.replace("\\", "\\\\").replace(".", "\\.").replace("[", "\\[")
        for p in path
    )


@dataclass
class TypeSchema:
    """Observations of one type at one field or array-element location.

    Attributes:
        name: Type label: object, array, null, or the supported scalar's Python name.
        count: Number of occurrences of this type, including repeated array values.
        elements: Array-element schema for arrays; otherwise None. Empty arrays
            still have an element schema with count zero and no observed types.

    Instances are maintained by Schema; inspect them rather than modifying counters.
    Retained values are immutable and separated by type. Container types never retain
    complete objects/arrays as values. Fields and count mappings are read-only views.
    """

    name: str
    count: int = 0
    elements: "FieldSchema | None" = None
    _mode: ValueMode = field(default="none", repr=False)
    _fields: dict[str, "FieldSchema"] = field(default_factory=dict, repr=False)
    _retained: set | Counter | None = field(default=None, repr=False)

    @property
    def fields(self) -> Mapping[str, "FieldSchema"]:
        """Object children, keyed by literal field name; empty for other types."""
        return MappingProxyType(self._fields)

    @property
    def values(self) -> frozenset | None:
        """Distinct retained primitives; None if disabled or this is a container.

        In full mode this is derived from the counter, not a second stored set.
        The returned frozenset is a snapshot; request it again after an update.
        """
        return None if self._retained is None else frozenset(self._retained)

    @property
    def value_counts(self) -> Mapping[Any, int] | None:
        """Live read-only exact frequencies in full mode; otherwise None."""
        if self._mode != "full" or self._retained is None:
            return None
        return MappingProxyType(self._retained)


@dataclass
class FieldSchema:
    """Observations at an object key or array-element location.

    Attributes:
        path: Unambiguous structural path: field-name strings and ARRAY_ELEMENT.
        count: Number of times this field or array element was observed.

    parent_count/missing_count refer to immediate parent objects, not root-document
    coverage. They are None for array elements. Schema owns these instances;
    references remain live across update() calls.
    """

    path: Path
    count: int = 0
    _parent: "Schema | TypeSchema | None" = field(default=None, repr=False, compare=False)
    _types: dict[str, TypeSchema] = field(default_factory=dict, repr=False)

    @property
    def types(self) -> Mapping[str, TypeSchema]:
        """Observed types in first-encounter order, exposed as a read-only mapping."""
        return MappingProxyType(self._types)

    @property
    def is_multi_type(self) -> bool:
        """Whether more than one type has been observed at this location."""
        return len(self._types) > 1

    @property
    def parent_count(self) -> int | None:
        """Number of parent objects; unavailable for array-element locations."""
        if self._parent is None:
            return None
        if isinstance(self._parent, Schema):
            return self._parent.document_count
        return self._parent.count

    @property
    def missing_count(self) -> int | None:
        """Parent objects lacking this key; null values count as present."""
        parent = self.parent_count
        return None if parent is None else parent - self.count

    @property
    def has_missing(self) -> bool | None:
        """Whether any parent objects lack this key; None for array elements."""
        missing = self.missing_count
        return None if missing is None else missing > 0


@dataclass(init=False)
class Schema:
    """Infer an observed schema from dictionaries without retaining source documents.

    Args:
        values: Primitive retention: none (default), distinct values, or full exact
            frequencies. The policy remains fixed across updates. Both enabled modes
            use memory proportional to distinct values and impose no memory limit.

    Objects use dict (including subclasses), arrays use list. Scalar support includes
    JSON primitives, bytes, datetime/date, finite Decimal, UUID and BSON ObjectId,
    Int64 and Binary. Other scalar types and nonfinite numbers raise explicitly.
    Nesting beyond 128 levels is rejected before accumulation. No JSON text decoding,
    database sampling or backend query semantics are included.
    """

    _mode: ValueMode
    _count: int
    _fields: dict[str, FieldSchema] = field(repr=False)
    _flat: dict[Path, FieldSchema] = field(repr=False)

    def __init__(self, *, values: ValueMode = "none") -> None:
        if values not in ("none", "distinct", "full"):
            raise ValueError("values must be 'none', 'distinct' or 'full'")
        self._mode = values
        self._count = 0
        self._fields = {}
        self._flat = {}

    def __repr__(self) -> str:
        return (
            f"Schema(document_count={self.document_count}, paths={len(self._flat)}, "
            f"values={self.value_mode!r})"
        )

    @classmethod
    def from_documents(cls, documents: Iterable[dict], *, values: ValueMode = "none") -> "Schema":
        """Construct a schema from one pass over an iterable of documents.

        Accepts generators and empty iterables. Each document is validated before
        accumulation; input dictionaries and lists are not modified or retained.
        """
        schema = cls(values=values)
        schema.update(documents)
        return schema

    @property
    def document_count(self) -> int:
        """Number of successfully ingested root documents, including empty objects."""
        return self._count

    @property
    def value_mode(self) -> ValueMode:
        """Fixed primitive-value retention policy."""
        return self._mode

    @property
    def fields(self) -> Mapping[str, FieldSchema]:
        """Live top-level fields keyed by literal field names."""
        return MappingProxyType(self._fields)

    @property
    def flat_fields(self) -> Mapping[str, FieldSchema]:
        """All locations keyed by escaped display paths, including array elements.

        Keys are a snapshot; values reference live field objects. Backslash escapes
        literal dots, opening brackets and backslashes. Tuple lookup avoids escaping.
        """
        return MappingProxyType({_display(path): value for path, value in self._flat.items()})

    @property
    def primitive_fields(self) -> Mapping[str, FieldSchema]:
        """Locations with any primitive type, even if objects/arrays also occur."""
        return MappingProxyType(
            {
                _display(path): value
                for path, value in self._flat.items()
                if any(name not in ("object", "array") for name in value.types)
            }
        )

    def __getitem__(self, path: str | Path) -> FieldSchema:
        """Look up an exact path; raise KeyError if absent. Arrays require explicit []."""
        return self._flat[_path(path)]

    def update(self, documents: Iterable[dict]) -> None:
        """Add a batch, keeping earlier documents if a later one fails validation.

        TypeError reports unsupported values or keys; ValueError reports cycles or
        nonfinite values. A failing document contributes nothing. Iterator failures
        also preserve earlier documents. Calls are synchronous and not thread-safe.
        """
        for document in documents:
            if not isinstance(document, dict):
                raise TypeError("Each root document must be a dictionary")
            _validate(document, set())
            self._count += 1
            self._object(document, self, ())

    def _object(self, document, parent, prefix):
        for name, value in document.items():
            path = prefix + (name,)
            if name not in parent._fields:
                parent._fields[name] = FieldSchema(path, _parent=parent)
                self._flat[path] = parent._fields[name]
            self._observe(parent._fields[name], value)

    def _observe(self, node, value):
        name = _type_name(value)
        node.count += 1
        if name not in node._types:
            variant = TypeSchema(name, _mode=self._mode)
            node._types[name] = variant
            if name == "array":
                path = node.path + (ARRAY_ELEMENT,)
                variant.elements = FieldSchema(path)
                self._flat[path] = variant.elements
            elif name != "object" and self._mode != "none":
                variant._retained = Counter() if self._mode == "full" else set()
        variant = node._types[name]
        variant.count += 1
        if name == "object":
            self._object(value, variant, node.path)
        elif name == "array":
            for item in value:
                self._observe(variant.elements, item)
        elif self._mode == "full":
            variant._retained[value] += 1
        elif self._mode == "distinct":
            variant._retained.add(value)
