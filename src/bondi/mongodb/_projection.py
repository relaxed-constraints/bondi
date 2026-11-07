"""Bounded translations of find array projections, with explicit rejection paths.

Query predicates and aggregation expressions have different array and type rules.
Keep this compiler deliberately small rather than silently approximating matching.
"""

import math
from typing import Any


def _unsupported(detail: str) -> ValueError:
    return ValueError(f"to_aggregate() unsupported projection: {detail}")


def _path(field: str, *, top_level: bool = False) -> None:
    if (
        not isinstance(field, str)
        or not field
        or any(
            not part or part.startswith("$") or part.isdigit() or "\0" in part
            for part in field.split(".")
        )
        or (top_level and "." in field)
    ):
        raise _unsupported(f"field path {field!r}")


def _scalar_comparison(reference: Any, operator: str, operand: Any) -> Any:
    """Type-bracket comparisons; missing equals null in query predicates."""
    if operand is None:
        if operator != "$eq":
            raise _unsupported("only equality/membership support null operands")
        return {"$in": [{"$type": reference}, ["missing", "null"]]}
    if type(operand) not in (bool, int, float, str) or (
        type(operand) is float and not math.isfinite(operand)
    ):
        raise _unsupported(
            "element conditions require finite numeric, string, bool or null literals"
        )
    kinds = (
        ["bool"]
        if type(operand) is bool
        else ["string"]
        if isinstance(operand, str)
        else ["int", "long", "double", "decimal"]
    )
    return {
        "$and": [
            {"$in": [{"$type": reference}, kinds]},
            {operator: [reference, {"$literal": operand}]},
        ]
    }


def _condition(reference: Any, condition: Any, *, traverse: bool) -> Any:
    if not isinstance(condition, dict):
        condition = {"$eq": condition}
    if not condition:
        raise _unsupported("empty/literal-document element conditions")
    terms = []
    for operator, operand in condition.items():
        if operator == "$not":
            terms.append({"$not": [_condition(reference, operand, traverse=traverse)]})
            continue
        if operator not in {"$eq", "$ne", "$gt", "$gte", "$lt", "$lte", "$in", "$nin"}:
            raise _unsupported(f"element condition operator {operator!r}")
        negate = operator in {"$ne", "$nin"}
        comparison = "$eq" if operator in {"$ne", "$in", "$nin"} else operator
        operands = operand if operator in {"$in", "$nin"} else [operand]
        if not isinstance(operands, list):
            raise _unsupported(f"{operator} requires an array")

        def compare(ref: Any) -> Any:
            return {"$or": [_scalar_comparison(ref, comparison, item) for item in operands]}

        term = compare(reference)
        if traverse:
            # Field predicates also match individual immediate array elements.
            term = {
                "$or": [
                    term,
                    {
                        "$anyElementTrue": [
                            {
                                "$map": {
                                    "input": {"$cond": [{"$isArray": reference}, reference, []]},
                                    "as": "candidate",
                                    "in": compare("$$candidate"),
                                }
                            }
                        ]
                    },
                ]
            }
        terms.append({"$not": [term]} if negate else term)
    return {"$and": terms}


def _element_condition(document: Any) -> Any:
    if not isinstance(document, dict) or not document:
        raise _unsupported("$elemMatch requires a nonempty condition document")
    # Scalar $elemMatch applies comparisons to each element itself, without the
    # implicit array traversal used when testing an object's field.
    if all(key.startswith("$") for key in document) and not any(
        key in {"$and", "$or", "$nor"} for key in document
    ):
        return _condition("$$element", document, traverse=False)
    terms = []
    for field, condition in document.items():
        if field in {"$and", "$or", "$nor"}:
            if not isinstance(condition, list) or not condition:
                raise _unsupported(f"{field} requires nonempty condition documents")
            parts = [_element_condition(child) for child in condition]
            term = {"$or" if field == "$nor" else field: parts}
            terms.append({"$not": [term]} if field == "$nor" else term)
        else:
            _path(field, top_level=True)
            # Object-style $elemMatch also examines array elements as objects
            # with numeric keys. Non-numeric fields on those arrays are missing.
            reference = {
                "$getField": {
                    "field": {"$literal": field},
                    "input": {
                        "$cond": [
                            {"$eq": [{"$type": "$$element"}, "object"]},
                            "$$element",
                            {},
                        ]
                    },
                }
            }
            terms.append(_condition(reference, condition, traverse=True))
    return {"$and": [{"$in": [{"$type": "$$element"}, ["object", "array"]]}, *terms]}


def _first_match(field: str, condition: Any) -> Any:
    matches = {
        "$filter": {
            "input": {"$cond": [{"$isArray": f"${field}"}, f"${field}", []]},
            "as": "element",
            "cond": _element_condition(condition),
        }
    }
    return {
        "$let": {
            "vars": {"matches": matches},
            "in": {
                "$cond": [
                    {"$gt": [{"$size": "$$matches"}, 0]},
                    {"$slice": ["$$matches", 1]},
                    "$$REMOVE",
                ]
            },
        }
    }


def _slice(field: str, specification: Any) -> Any:
    reference = f"${field}"
    if type(specification) is int:
        result = [] if specification == 0 else {"$slice": [reference, specification]}
    elif (
        isinstance(specification, list)
        and len(specification) == 2
        and all(type(value) is int for value in specification)
        and specification[1] > 0
    ):
        skip, limit = specification
        # Find clamps a negative offset before the beginning of the array to 0.
        start = skip if skip >= 0 else {"$max": [0, {"$add": [{"$size": reference}, skip]}]}
        result = {"$slice": [reference, start, limit]}
    else:
        raise _unsupported("$slice requires an integer or [integer skip, positive integer limit]")
    return {"$cond": [{"$isArray": reference}, result, reference]}


def projection_stages(
    projection: dict[str, Any] | None, predicate: dict[str, Any]
) -> list[dict[str, Any]]:
    """Translate flags and supported top-level array projections."""
    if not projection:
        return []
    flags: dict[str, int] = {}
    expressions: dict[str, Any] = {}
    slices: set[str] = set()
    positional = False
    for field, value in projection.items():
        if isinstance(field, str) and field.endswith(".$"):
            base = field[:-2]
            _path(base, top_level=True)
            if base in projection:
                raise _unsupported("overlapping projection paths")
            if type(value) not in (int, bool) or not value:
                raise _unsupported("positional $ requires inclusion")
            # Explicit $elemMatch is the unambiguous binding: all conditions
            # apply to one element. Multi-array/implicit positional bindings are
            # deliberately rejected, rather than guessing which element Mongo chose.
            if (
                set(predicate) != {base}
                or not isinstance(predicate[base], dict)
                or set(predicate[base]) != {"$elemMatch"}
            ):
                raise _unsupported("positional $ requires a sole filter {array: {$elemMatch: ...}}")
            expressions[base] = _first_match(base, predicate[base]["$elemMatch"])
            positional = True
            continue
        _path(field)
        if type(value) in (int, bool):
            flags[field] = int(bool(value))
        elif isinstance(value, dict) and len(value) == 1:
            _path(field, top_level=True)
            if "$slice" in value:
                expressions[field] = _slice(field, value["$slice"])
                slices.add(field)
            elif "$elemMatch" in value:
                expressions[field] = _first_match(field, value["$elemMatch"])
            else:
                raise _unsupported(f"expression on {field!r}; only $slice/$elemMatch are supported")
        else:
            raise _unsupported(f"value on {field!r}")

    paths = list(flags) + list(expressions)
    if len(paths) != len(set(paths)) or any(
        right.startswith(left + ".") for left in paths for right in paths if left != right
    ):
        raise _unsupported("overlapping projection paths")
    exclusions = {key for key, value in flags.items() if not value and key != "_id"}
    explicit_inclusion = any(value for key, value in flags.items() if key != "_id")
    if exclusions and (explicit_inclusion or positional):
        raise _unsupported("cannot mix inclusion and exclusion projections")

    # Find's special projections do not all select inclusion mode. $elemMatch
    # can accompany exclusions; $slice defaults to exclusion even beside it.
    inclusion = (
        explicit_inclusion
        or positional
        or (not exclusions and (bool(flags.get("_id")) or (bool(expressions) and not slices)))
    )
    if inclusion:
        return [{"$project": {**flags, **expressions}}]
    stages = [{"$set": expressions}] if expressions else []
    if flags:
        stages.append({"$project": flags})
    return stages
