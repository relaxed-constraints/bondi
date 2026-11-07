"""Offline, versioned structural statistics for MongoDB queries.

Counting rules and supported syntax are documented in the MongoDB Query statistics
user guide. These counts describe syntax, not execution cost or query equivalence.
"""

import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Any

from bson import Regex

from bondi.mongodb.aggregate import MongoAggregateQuery
from bondi.mongodb.query import MongoFindQuery

_Path = tuple[str | int, ...]


@dataclass
class MongoStageStatistics:
    """Statistics owned by one stage, excluding its nested pipeline bodies.

    Attributes:
        path: Location in the analyzed pipeline, starting with a zero-based index.
        name: Stage operator, including its dollar prefix.
        predicate_count: Atomic filter conditions in this stage's $match body.
        operator_count: Operator occurrences below stage level.
        operator_counts: Occurrence histogram, including normalized implicit operators.
        expression_depth: Maximum nested expression-operator depth in local syntax.
        filter_logical_depth: Maximum Boolean-connective depth in a $match filter.
        filter_logical_fan_out: Maximum connective arity in a $match filter.
    """

    path: tuple[str | int, ...]
    name: str
    predicate_count: int
    operator_count: int
    operator_counts: dict[str, int]
    expression_depth: int = 0
    filter_logical_depth: int = 0
    filter_logical_fan_out: int = 0


@dataclass
class MongoQueryStatistics:
    """Independent statistics snapshot for the selected pipeline scope.

    Attributes:
        definition_version: Counting-rule version, currently 1.
        stage_count: Number of selected stage occurrences.
        predicate_count: Sum of selected stages' predicate counts.
        operator_count: Sum of selected stages' operator counts.
        stage_counts: Stage-name occurrence histogram.
        operator_counts: Combined below-stage operator histogram.
        stages: Ordered stage records; recursive selection uses depth-first preorder.
        expression_depth: Maximum expression depth across selected stages, or zero.
        filter_logical_depth: Maximum filter logical depth across selected stages, or zero.
        filter_logical_fan_out: Maximum filter connective arity across selected stages, or zero.
        nested_pipeline_depth: Maximum selected child-pipeline nesting, including empty
            pipelines. Zero for outer-only analysis; the outer pipeline is level zero.

    Records and dictionaries are mutable, independent snapshots. Editing them does
    not change the input query, and totals are not recomputed after such edits.
    """

    definition_version: int
    stage_count: int
    predicate_count: int
    operator_count: int
    stage_counts: dict[str, int]
    operator_counts: dict[str, int]
    stages: tuple[MongoStageStatistics, ...]
    expression_depth: int = 0
    filter_logical_depth: int = 0
    filter_logical_fan_out: int = 0
    nested_pipeline_depth: int = 0


# Explicit registries prevent unknown syntax from silently producing partial counts.
_FIELD_LEAVES = frozenset(
    """
$eq $ne $gt $gte $lt $lte $in $nin $exists $type $mod $regex $size
$bitsAllClear $bitsAllSet $bitsAnyClear $bitsAnySet
""".split()
)
_LOGICAL = frozenset({"$and", "$or", "$nor"})
_EXPRESSIONS = frozenset(
    """
$abs $acos $acosh $add $addToSet $allElementsTrue $and $anyElementTrue
$arrayElemAt $arrayToObject $asin $asinh $atan $atan2 $atanh $avg
$binarySize $bsonSize $ceil $cmp $concat $concatArrays $cond $convert $cos $cosh
$count $dateAdd $dateDiff $dateFromParts $dateFromString $dateSubtract $dateToParts
$dateToString $dateTrunc $dayOfMonth $dayOfWeek $dayOfYear $degreesToRadians
$divide $eq $exp $filter $first $firstN $floor $getField $gt $gte $hour $ifNull
$in $indexOfArray $indexOfBytes $indexOfCP $isArray $isNumber $isoDayOfWeek
$isoWeek $isoWeekYear $last $lastN $let $ln $log $log10 $lt $lte $ltrim $map
$max $maxN $mergeObjects $meta $millisecond $min $minN $minute $mod $month
$multiply $ne $not $objectToArray $or $pow $push $radiansToDegrees $rand $range
$reduce $regexFind $regexFindAll $regexMatch $replaceAll $replaceOne $reverseArray
$round $rtrim $second $setDifference $setEquals $setField $setIntersection
$setIsSubset $setUnion $sin $sinh $size $slice $sortArray $split $sqrt
$stdDevPop $stdDevSamp $strcasecmp $strLenBytes $strLenCP $substr $substrBytes
$substrCP $subtract $sum $switch $tan $tanh $toBool $toDate $toDecimal $toDouble
$toInt $toLong $toObjectId $toString $toLower $toUpper $trim $trunc $type
$unsetField $week $year $zip
""".split()
)
_LITERAL_STAGES = frozenset({"$count", "$limit", "$skip", "$unset", "$sample", "$unwind", "$out"})
_FIELD_EXPRESSION_STAGES = frozenset({"$project", "$set", "$addFields", "$group", "$sort"})
_EXPRESSION_STAGES = frozenset({"$replaceWith", "$redact", "$sortByCount", "$documents"})


def _error(path: _Path, message: str) -> ValueError:
    return ValueError(f"query_statistics() at {path!r}: {message}")


def _document(value: Any, path: _Path) -> dict[str, Any]:
    if not isinstance(value, dict) or any(not isinstance(key, str) for key in value):
        raise _error(path, "expected a document with string keys")
    return value


def _keys(document: dict[str, Any], allowed: set[str], path: _Path) -> None:
    for key in document:
        if key not in allowed:
            raise _error((*path, key), "unsupported argument")


@dataclass
class _Counts:
    predicates: int = 0
    expression_depth: int = 0
    operators: Counter[str] = field(default_factory=Counter)

    def add(self, name: str, *, predicate: bool = False) -> None:
        self.operators[name] += 1
        self.predicates += int(predicate)

    def expression_fields(self, value: Any, path: _Path, depth: int = 0) -> None:
        for key, child in _document(value, path).items():
            if key.startswith("$"):
                raise _error((*path, key), "expected a field/variable name, not an operator")
            self.expression(child, (*path, key), depth)

    def expression(self, value: Any, path: _Path, depth: int = 0) -> None:
        if isinstance(value, list):
            for index, child in enumerate(value):
                self.expression(child, (*path, index), depth)
        elif isinstance(value, dict):
            document = _document(value, path)
            operators = [key for key in document if key.startswith("$")]
            if not operators:
                self.expression_fields(document, path, depth)
                return
            if len(document) != 1:
                raise _error(path, "expression operator must occupy a single-key document")
            name = operators[0]
            operand = document[name]
            location = (*path, name)
            self.expression_depth = max(self.expression_depth, depth + 1)
            if name in {"$literal", "$const"}:
                self.add(name)
                return
            if name not in _EXPRESSIONS:
                raise _error(location, "unsupported expression operator")
            self.add(name)
            self.expression(operand, location, depth + 1)
        # Strings (including references), BSON values and other scalars are leaves.

    def filter(self, value: Any, path: _Path, *, predicates: bool = True) -> None:
        for name, operand in _document(value, path).items():
            location = (*path, name)
            if name in _LOGICAL:
                if not isinstance(operand, list) or not operand:
                    raise _error(location, "logical operator requires a nonempty array")
                self.add(name)
                for index, child in enumerate(operand):
                    self.filter(child, (*location, index), predicates=predicates)
            elif name == "$expr":
                self.add(name, predicate=predicates)
                self.expression(operand, location)
            elif name == "$text":
                _keys(
                    _document(operand, location),
                    {"$search", "$language", "$caseSensitive", "$diacriticSensitive"},
                    location,
                )
                self.add(name, predicate=predicates)
            elif name == "$comment":
                pass  # Query annotation, not an operator or predicate.
            elif name.startswith("$"):
                raise _error(location, "unsupported document filter operator")
            elif isinstance(operand, (Regex, re.Pattern)):
                self.add("$regex", predicate=predicates)
            elif isinstance(operand, dict) and any(
                isinstance(key, str) and key.startswith("$") for key in operand
            ):
                self.field_filter(operand, location, predicates=predicates)
            else:
                # Equality against a literal object/array remains one condition.
                self.add("$eq", predicate=predicates)

    def element_filter(self, value: Any, path: _Path, *, predicates: bool) -> None:
        document = _document(value, path)
        if any(key.startswith("$") and key not in _LOGICAL for key in document):
            self.field_filter(document, path, predicates=predicates)
        else:
            self.filter(document, path, predicates=predicates)

    def field_filter(self, value: Any, path: _Path, *, predicates: bool) -> None:
        document = _document(value, path)
        for name, operand in document.items():
            location = (*path, name)
            if name == "$options":
                if "$regex" not in document:
                    raise _error(location, "$options requires $regex")
            elif name in _FIELD_LEAVES:
                self.add(name, predicate=predicates)
            elif name == "$not":
                self.add(name)
                if isinstance(operand, (Regex, re.Pattern)):
                    self.add("$regex", predicate=predicates)
                else:
                    self.field_filter(operand, location, predicates=predicates)
            elif name == "$elemMatch":
                self.add(name)
                self.element_filter(operand, location, predicates=predicates)
            elif name == "$all":
                if not isinstance(operand, list):
                    raise _error(location, "$all requires an array")
                self.add(name, predicate=predicates)
                for index, child in enumerate(operand):
                    if isinstance(child, dict) and "$elemMatch" in child:
                        _keys(child, {"$elemMatch"}, (*location, index))
                        self.add("$elemMatch")
                        self.element_filter(
                            child["$elemMatch"], (*location, index, "$elemMatch"), predicates=False
                        )
            elif name in {"$geoWithin", "$geoIntersects"}:
                _keys(
                    _document(operand, location),
                    {"$geometry", "$box", "$center", "$centerSphere", "$polygon"},
                    location,
                )
                self.add(name, predicate=predicates)
            else:
                raise _error(location, "unsupported field filter operator")


def _stage(name: str, body: Any, path: _Path, counts: _Counts) -> list[tuple[_Path, Any]]:
    """Count local syntax and return explicit child pipeline locations."""
    location = (*path, name)
    if name == "$match":
        counts.filter(body, location)
    elif name in _FIELD_EXPRESSION_STAGES:
        counts.expression_fields(body, location)
    elif name in _EXPRESSION_STAGES:
        counts.expression(body, location)
    elif name in _LITERAL_STAGES:
        pass
    elif name == "$replaceRoot":
        document = _document(body, location)
        _keys(document, {"newRoot"}, location)
        if "newRoot" not in document:
            raise _error(location, "missing newRoot")
        counts.expression(document["newRoot"], (*location, "newRoot"))
    elif name == "$facet":
        return [
            ((*location, branch), pipeline)
            for branch, pipeline in _document(body, location).items()
        ]
    elif name in {"$lookup", "$unionWith", "$merge"}:
        if isinstance(body, str) and name in {"$unionWith", "$merge"}:
            return []
        document = _document(body, location)
        allowed = {
            "$lookup": {"from", "localField", "foreignField", "as", "let", "pipeline"},
            "$unionWith": {"coll", "pipeline"},
            "$merge": {"into", "on", "let", "whenMatched", "whenNotMatched"},
        }[name]
        _keys(document, allowed, location)
        if "let" in document:
            counts.expression_fields(document["let"], (*location, "let"))
        child_key = "whenMatched" if name == "$merge" else "pipeline"
        if child_key in document:
            child = document[child_key]
            if not (name == "$merge" and isinstance(child, str)):
                return [((*location, child_key), child)]
    elif name == "$graphLookup":
        document = _document(body, location)
        _keys(
            document,
            {
                "from",
                "startWith",
                "connectFromField",
                "connectToField",
                "as",
                "maxDepth",
                "depthField",
                "restrictSearchWithMatch",
            },
            location,
        )
        if "startWith" in document:
            counts.expression(document["startWith"], (*location, "startWith"))
        if "restrictSearchWithMatch" in document:
            counts.filter(
                document["restrictSearchWithMatch"],
                (*location, "restrictSearchWithMatch"),
                predicates=False,
            )
    elif name in {"$bucket", "$bucketAuto"}:
        document = _document(body, location)
        allowed = {"groupBy", "output"} | (
            {"boundaries", "default"} if name == "$bucket" else {"buckets", "granularity"}
        )
        _keys(document, allowed, location)
        if "groupBy" in document:
            counts.expression(document["groupBy"], (*location, "groupBy"))
        if "output" in document:
            counts.expression_fields(document["output"], (*location, "output"))
    else:
        raise _error(location, "unsupported pipeline stage")
    return []


def _connective(children: list[tuple[int, int]], *, explicit: bool = False) -> tuple[int, int]:
    """Combine logical subtrees as (maximum depth, maximum fan-out)."""
    depth = max((child[0] for child in children), default=0)
    fan_out = max((child[1] for child in children), default=0)
    if explicit or len(children) > 1:
        return depth + 1, max(fan_out, len(children))
    return depth, fan_out


def _filter_shape(document: dict[str, Any]) -> tuple[int, int]:
    """Measure validated $match syntax, flattening implicit same-scope conjunctions.

    Expressions and atomic operands are boundaries. Element matching changes the
    element scope without itself introducing a Boolean connective.
    """
    terms = []
    for name, operand in document.items():
        if name in _LOGICAL:
            terms.append(_connective([_filter_shape(child) for child in operand], explicit=True))
        elif name == "$comment":
            continue
        elif (
            not name.startswith("$")
            and isinstance(operand, dict)
            and any(isinstance(key, str) and key.startswith("$") for key in operand)
        ):
            terms.extend(_field_shapes(operand))
        else:
            terms.append((0, 0))
    return _connective(terms)


def _field_shapes(document: dict[str, Any]) -> list[tuple[int, int]]:
    terms = []
    for name, operand in document.items():
        if name == "$options":
            continue
        if name == "$not":
            child = _connective(_field_shapes(operand)) if isinstance(operand, dict) else (0, 0)
            terms.append(_connective([child], explicit=True))
        elif name == "$elemMatch":
            if any(key.startswith("$") and key not in _LOGICAL for key in operand):
                terms.append(_connective(_field_shapes(operand)))
            else:
                terms.append(_filter_shape(operand))
        else:
            # $all remains atomic even when it contains $elemMatch operands.
            terms.append((0, 0))
    return terms


def _pipeline(
    pipeline: Any,
    path: _Path,
    recursive: bool,
    depth: int = 0,
) -> tuple[list[MongoStageStatistics], int]:
    if not isinstance(pipeline, list):
        raise _error(path, "pipeline must be a list")
    records = []
    deepest = depth
    for index, stage in enumerate(pipeline):
        location = (*path, index)
        document = _document(stage, location)
        if len(document) != 1:
            raise _error(location, "stage must contain exactly one operator")
        name, body = next(iter(document.items()))
        counts = _Counts()
        children = _stage(name, body, location, counts)
        logical_depth, fan_out = _filter_shape(body) if name == "$match" else (0, 0)
        records.append(
            MongoStageStatistics(
                location,
                name,
                counts.predicates,
                sum(counts.operators.values()),
                dict(counts.operators),
                expression_depth=counts.expression_depth,
                filter_logical_depth=logical_depth,
                filter_logical_fan_out=fan_out,
            )
        )
        for child_path, child in children:
            if not isinstance(child, list):
                raise _error(child_path, "pipeline must be a list")
            if recursive:
                child_records, child_depth = _pipeline(child, child_path, recursive, depth + 1)
                records.extend(child_records)
                deepest = max(deepest, child_depth)
    return records, deepest


def query_statistics(
    query: MongoFindQuery | MongoAggregateQuery,
    *,
    include_nested_pipelines: bool = False,
) -> MongoQueryStatistics:
    """Measure counts, depth and logical fan-out without database access.

    Find queries are analyzed through ``to_aggregate()``. Counts describe the
    resulting syntax, including generated projection expressions. See the MongoDB
    Query statistics user guide for complete versioned definitions and coverage.

    Args:
        query: A MongoDB find or aggregation query; never modified.
        include_nested_pipelines: Include child pipelines recursively. Otherwise
            exclude their bodies from all counts. Defaults to False.

    Returns:
        An independent version-1 snapshot with counts, structural maxima and stage records.

    Raises:
        TypeError: Input or the recursion flag has the wrong type, or query
            structural validation fails.
        ValueError: Conversion fails, query validation fails, or selected syntax
            is unsupported/malformed. Parser errors include the offending path;
            partial results are never returned. This is not a full MongoDB validator.

    Examples:
        >>> from bondi.mongodb import MongoCollectionRef
        >>> query = MongoFindQuery(MongoCollectionRef("demo", "items"), {"a": 1}, limit=5)
        >>> stats = query_statistics(query)
        >>> (stats.stage_count, stats.predicate_count, stats.operator_count)
        (2, 1, 1)
        >>> stats.operator_counts
        {'$eq': 1}
    """
    if not isinstance(query, (MongoFindQuery, MongoAggregateQuery)):
        raise TypeError("query must be a MongoFindQuery or MongoAggregateQuery")
    if type(include_nested_pipelines) is not bool:
        raise TypeError("include_nested_pipelines must be a boolean")
    if isinstance(query, MongoFindQuery):
        query = query.to_aggregate()
    else:
        query.validate()
    records, nested_depth = _pipeline(query.pipeline, (), include_nested_pipelines)
    stages = tuple(records)
    operators: Counter[str] = Counter()
    for stage in stages:
        operators.update(stage.operator_counts)
    return MongoQueryStatistics(
        definition_version=1,
        stage_count=len(stages),
        predicate_count=sum(stage.predicate_count for stage in stages),
        operator_count=sum(operators.values()),
        stage_counts=dict(Counter(stage.name for stage in stages)),
        operator_counts=dict(operators),
        stages=stages,
        expression_depth=max((stage.expression_depth for stage in stages), default=0),
        filter_logical_depth=max((stage.filter_logical_depth for stage in stages), default=0),
        filter_logical_fan_out=max((stage.filter_logical_fan_out for stage in stages), default=0),
        nested_pipeline_depth=nested_depth,
    )
