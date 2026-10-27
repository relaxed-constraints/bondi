"""Immutable shapes for the flat-find subset produced by workload generation."""

import math
from dataclasses import dataclass
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
