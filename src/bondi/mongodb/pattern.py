"""Immutable shapes for the flat-find subset produced by workload generation."""

import json
import math
from dataclasses import asdict, dataclass
from typing import Self

from bondi.mongodb.collection import MongoCollectionRef
from bondi.mongodb.query import MongoFindQuery

_TYPES = {"str", "int", "Int64", "float", "bool", "datetime", "ObjectId", "null"}
_BSON_TYPES = {
    "string",
    "int",
    "long",
    "double",
    "bool",
    "date",
    "objectId",
    "array",
    "object",
    "null",
    "number",
}


def _value_type(value):
    name = "null" if value is None else type(value).__name__
    if name == "int" and not -(2**31) <= value < 2**31:
        if not -(2**63) <= value < 2**63:
            raise ValueError("Integer operand exceeds BSON int64 range")
        name = "Int64"
    if name not in _TYPES or (name == "float" and not math.isfinite(value)):
        raise ValueError(f"Unsupported generation operand type: {name}")
    return name


def _field_path(path):
    if (
        not isinstance(path, str)
        or not path
        or "\0" in path
        or any(not p or p.startswith("$") or p == "[]" or p.isdecimal() for p in path.split("."))
    ):
        raise ValueError(f"Unsupported Mongo generation field path: {path!r}")


@dataclass(frozen=True)
class MongoPredicateTemplate:
    """One field/operator slot exposed through MongoQueryPattern.predicates.

    Attributes:
        field: Normalized MongoDB dot path.
        operator: Operator name without '$'.
        value_type: BSON-compatible Python type label, or None for fixed literals.
        arity: Number of operands; in uses 2–10, nin uses 1–10, others use one.
        fixed_value: Boolean for exists or BSON type name for type; otherwise None.
    """

    field: str
    operator: str
    value_type: str | None = None
    arity: int = 1
    fixed_value: bool | str | None = None

    def __post_init__(self):
        _field_path(self.field)
        if self.operator not in {
            "eq",
            "ne",
            "lt",
            "lte",
            "gt",
            "gte",
            "in",
            "nin",
            "exists",
            "type",
            "size",
        }:
            raise ValueError("Unsupported pattern operator")
        if type(self.arity) is not int or self.arity < 1:
            raise ValueError("arity must be a positive integer")
        if self.operator in {"in", "nin"}:
            if not (2 if self.operator == "in" else 1) <= self.arity <= 10:
                raise ValueError("Unsupported membership arity")
        elif self.arity != 1:
            raise ValueError("Scalar operators have arity=1")
        if self.operator in {"exists", "type"}:
            if self.value_type is not None:
                raise ValueError("Fixed predicates have no sampled type")
            if self.operator == "exists" and type(self.fixed_value) is not bool:
                raise ValueError("exists requires a fixed bool")
            if self.operator == "type" and self.fixed_value not in _BSON_TYPES:
                raise ValueError("type requires a supported BSON type name")
        elif self.value_type not in _TYPES or self.fixed_value is not None:
            raise ValueError("Sampled predicates require a supported type and no fixed value")
        if self.operator == "size" and self.value_type != "int":
            raise ValueError("size requires int operands")


@dataclass(frozen=True)
class MongoQueryPattern:
    """Complete immutable flat-find shape, independent of operand values.

    Field/operator/type/membership length and all query options identify a pattern.
    Filter and projection order are canonicalized; sort order is significant.
    Use print(pattern) for a readable target, typed predicates and query options.
    Patterns may be inspected or extracted from saved queries with from_query().
    Logical expressions, object/array equality and multiple operators on one field
    are outside this initial subset. They remain representable as MongoFindQuery.
    """

    target: MongoCollectionRef
    predicates: tuple[MongoPredicateTemplate, ...]
    sort: tuple[tuple[str, int], ...] = ()
    projection: tuple[tuple[str, int], ...] | None = None
    skip: int = 0
    limit: int | None = None

    def __post_init__(self):
        if (
            not isinstance(self.predicates, tuple)
            or not self.predicates
            or not all(isinstance(p, MongoPredicateTemplate) for p in self.predicates)
        ):
            raise ValueError("Patterns require a nonempty tuple of MongoPredicateTemplate")
        fields = [p.field for p in self.predicates]
        if len(fields) != len(set(fields)):
            raise ValueError("One predicate per field is supported")
        object.__setattr__(
            self, "predicates", tuple(sorted(self.predicates, key=lambda p: p.field))
        )
        MongoFindQuery(self.target, {}, sort=self.sort, skip=self.skip, limit=self.limit)
        if len({p[0] for p in self.sort}) != len(self.sort):
            raise ValueError("Duplicate sort field")
        for name, _ in self.sort:
            _field_path(name)
        if self.projection is not None:
            if not isinstance(self.projection, tuple) or any(
                not isinstance(p, tuple)
                or len(p) != 2
                or type(p[1]) is not int
                or p[1] not in (0, 1)
                for p in self.projection
            ):
                raise ValueError("Projection patterns require tuple pairs with 0/1 values")
            names = [p[0] for p in self.projection]
            for name in names:
                _field_path(name)
            if len(names) != len(set(names)):
                raise ValueError("Duplicate projection field")
            non_id = {v for k, v in self.projection if k != "_id"}
            if len(non_id) > 1:
                raise ValueError("Cannot mix inclusion and exclusion projection")
            object.__setattr__(self, "projection", tuple(sorted(self.projection)))

    def to_dict(self) -> dict:
        """Return an independent, JSON-compatible version-1 pattern envelope.

        Sort/projection pairs become lists; target and predicate templates become
        dictionaries. Patterns contain type labels and fixed bool/string operands,
        not sampled BSON values, so ordinary JSON is sufficient.
        """
        return {
            "format_version": 1,
            "pattern_kind": "mongodb.find",
            "target": asdict(self.target),
            "predicates": [asdict(predicate) for predicate in self.predicates],
            "sort": [list(pair) for pair in self.sort],
            "projection": None if self.projection is None else [list(p) for p in self.projection],
            "skip": self.skip,
            "limit": self.limit,
        }

    @classmethod
    def from_dict(cls, value: dict) -> Self:
        """Restore an envelope produced by to_dict, validating its shape and values.

        All fields are required; unknown fields, kinds and versions are rejected.
        Raises TypeError for incorrect container types and ValueError for invalid
        contents. Nested objects and immutable tuples are reconstructed.
        """

        def fields(obj, expected, name):
            if not isinstance(obj, dict):
                raise TypeError(f"{name} must be a dictionary")
            if set(obj) != set(expected):
                raise ValueError(f"Unexpected or missing fields in {name}")

        def pairs(items, name):
            if not isinstance(items, list):
                raise TypeError(f"{name} must be a list")
            if any(not isinstance(p, list) or len(p) != 2 for p in items):
                raise ValueError(f"{name} must contain two-element lists")
            return tuple(tuple(p) for p in items)

        fields(
            value,
            (
                "format_version",
                "pattern_kind",
                "target",
                "predicates",
                "sort",
                "projection",
                "skip",
                "limit",
            ),
            "pattern",
        )
        if type(value["format_version"]) is not int or value["format_version"] != 1:
            raise ValueError("Unsupported pattern format_version")
        if value["pattern_kind"] != "mongodb.find":
            raise ValueError("Unsupported pattern_kind")
        fields(value["target"], ("database", "collection"), "target")
        if not isinstance(value["predicates"], list):
            raise TypeError("predicates must be a list")
        predicates = []
        for predicate in value["predicates"]:
            fields(
                predicate, ("field", "operator", "value_type", "arity", "fixed_value"), "predicate"
            )
            predicates.append(MongoPredicateTemplate(**predicate))
        return cls(
            target=MongoCollectionRef(**value["target"]),
            predicates=tuple(predicates),
            sort=pairs(value["sort"], "sort"),
            projection=None
            if value["projection"] is None
            else pairs(value["projection"], "projection"),
            skip=value["skip"],
            limit=value["limit"],
        )

    def to_json(self) -> str:
        """Serialize the versioned envelope as compact JSON."""
        return json.dumps(
            self.to_dict(), ensure_ascii=False, allow_nan=False, separators=(",", ":")
        )

    @classmethod
    def from_json(cls, text: str) -> Self:
        """Restore JSON, rejecting duplicate keys, nonfinite numbers and invalid envelopes."""
        if not isinstance(text, str):
            raise TypeError("text must be a string")

        def object_pairs(pairs):
            result = {}
            for key, value in pairs:
                if key in result:
                    raise ValueError(f"Duplicate JSON key: {key}")
                result[key] = value
            return result

        def reject_constant(value):
            raise ValueError(f"Nonfinite JSON constant: {value}")

        return cls.from_dict(
            json.loads(text, object_pairs_hook=object_pairs, parse_constant=reject_constant)
        )

    def __str__(self) -> str:
        """Format the target, typed predicates and configured query options for display.

        Sampled operands appear as <type>, or <arity × type> for membership.
        Fixed exists/type operands retain their Python literal representation.
        Predicates follow canonical field order; sort precedence is preserved.
        Unset options and skip=0 are omitted. This is a human-readable summary,
        not an executable query or persistence format; repr retains the dataclass view.
        """
        predicates = []
        for predicate in self.predicates:
            if predicate.fixed_value is not None:
                operand = repr(predicate.fixed_value)
            elif predicate.operator in {"in", "nin"}:
                operand = f"<{predicate.arity} × {predicate.value_type}>"
            else:
                operand = f"<{predicate.value_type}>"
            predicates.append(f"{predicate.field} ${predicate.operator} {operand}")
        parts = [f"{self.target.database}.{self.target.collection}: " + " AND ".join(predicates)]
        if self.sort:
            parts.append(f"sort={dict(self.sort)!r}")
        if self.projection is not None:
            parts.append(f"projection={dict(self.projection)!r}")
        if self.skip:
            parts.append(f"skip={self.skip}")
        if self.limit is not None:
            parts.append(f"limit={self.limit}")
        return " | ".join(parts)

    @classmethod
    def from_query(cls, query: MongoFindQuery) -> Self:
        """Extract a shape from a supported native find query, including after JSONL loading."""
        if not isinstance(query, MongoFindQuery):
            raise TypeError("Expected MongoFindQuery")
        query.validate()
        predicates = []
        for name, expression in query.filter.items():
            op, operand = "eq", expression
            if isinstance(expression, dict):
                if len(expression) != 1:
                    raise ValueError("Only one operator per field is supported")
                key, operand = next(iter(expression.items()))
                if not isinstance(key, str) or not key.startswith("$"):
                    raise ValueError("Literal object equality is not a pattern operand")
                op = key[1:]
            if op in ("exists", "type"):
                predicate = MongoPredicateTemplate(name, op, fixed_value=operand)
            else:
                values = operand if op in ("in", "nin") else [operand]
                if not isinstance(values, list) or not values:
                    raise ValueError("Membership operands require a nonempty list")
                kind = _value_type(values[0])
                if any(_value_type(v) != kind for v in values) or len(set(values)) != len(values):
                    raise ValueError("Membership operands must be distinct and of one type")
                if op == "size" and (type(operand) is not int or operand < 0):
                    raise ValueError("size requires a nonnegative integer")
                predicate = MongoPredicateTemplate(name, op, kind, len(values))
            predicates.append(predicate)
        return cls(
            query.target,
            tuple(predicates),
            query.sort,
            None if query.projection is None else tuple(query.projection.items()),
            query.skip,
            query.limit,
        )

    def matches(self, query: MongoFindQuery) -> bool:
        """Whether the query has this shape; unsupported shapes return False."""
        try:
            return self == self.from_query(query)
        except (ValueError, TypeError):
            return False
