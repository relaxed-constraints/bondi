# MongoDB Query statistics

BONDI's `query_statistics()` measures the **structure of a query**, without a
MongoDB connection. Research projects can use the same definitions for predicate,
operator and stage counts, rather than implementing subtly different counters.
It returns totals, occurrence histograms and an ordered breakdown by stage.

These are syntax measurements, not estimates of execution cost, selectivity or
index use. Semantically equivalent queries can have different counts. See
[query summaries](summaries.md) for measurements derived from execution diagnostics.

## Quick example

```python
from bondi.mongodb import MongoCollectionRef, MongoFindQuery, query_statistics

query = MongoFindQuery(
    MongoCollectionRef("research", "items"),
    {"foo": "bar"},
    sort=(("baz", 1),),
    limit=5,
)
stats = query_statistics(query)

assert stats.definition_version == 1
assert stats.stage_count == 3
assert stats.predicate_count == 1
assert stats.operator_count == 1
assert stats.stage_counts == {"$match": 1, "$sort": 1, "$limit": 1}
assert stats.operator_counts == {"$eq": 1}
```

For find queries, the function first calls
[`MongoFindQuery.to_aggregate()`](find-query.md#convert-a-find-query-to-aggregation).
The example becomes `$match`, `$sort`, then `$limit`. Aggregation queries are
analyzed as written. Neither kind of query is modified, and conversion errors
propagate rather than falling back to another counting scheme.

## API and result structure

```python
from bondi.mongodb import MongoQueryStatistics, MongoStageStatistics

assert isinstance(stats, MongoQueryStatistics)
first = stats.stages[0]
assert isinstance(first, MongoStageStatistics)
assert first.path == (0,)
assert first.name == "$match"
assert first.predicate_count == 1
assert first.operator_count == 1
assert first.operator_counts == {"$eq": 1}
```

`query_statistics(query, *, include_nested_pipelines=False)` accepts either
`MongoFindQuery` or `MongoAggregateQuery`. The keyword flag must be a boolean.

| Result field | Definition |
| --- | --- |
| `definition_version` | Version of the counting rules; currently `1` |
| `stage_count` | Number of stage occurrences in the selected scope |
| `predicate_count` | Sum of atomic conditions in selected `$match` stages |
| `operator_count` | Sum of below-stage operator occurrences in the selected scope |
| `stage_counts` | Histogram keyed by stage name, including the `$` prefix |
| `operator_counts` | Histogram keyed by operator name, including implicit operators normalized as described below |
| `stages` | Tuple of `MongoStageStatistics` records in pipeline order, or depth-first preorder when recursive |

Each stage record contains `path`, `name`, `predicate_count`, `operator_count`
and `operator_counts`. A stage owns its local syntax, never the contents of a
nested pipeline. Thus the following identities hold for the returned snapshot:

```python
assert stats.stage_count == len(stats.stages) == sum(stats.stage_counts.values())
assert stats.predicate_count == sum(stage.predicate_count for stage in stats.stages)
assert stats.operator_count == sum(stage.operator_count for stage in stats.stages)
assert stats.operator_count == sum(stats.operator_counts.values())
```

The records and dictionaries are independent, mutable snapshots. Changes to the
query do not update an existing result. Editing a result does not affect the query
or recompute its totals. Call `query_statistics()` again to analyze a changed query.
Histogram keys appear in first-encounter order; missing operators are absent, not
stored with zero counts. All totals are zero for an empty pipeline.

## Predicate count

A predicate is an **atomic query-filter condition**. Count occurrences, not unique
conditions, and count them only in `$match` stage filters.

### Atomic conditions

Each supported ordinary field condition contributes one predicate. This includes
implicit equality, explicit comparisons, membership, existence, type, regex,
array size, modulo, bit tests and geospatial conditions.

| Filter fragment | Predicate count | Explanation |
| --- | ---: | --- |
| `{}` | 0 | No conditions |
| `{"a": 1}` | 1 | Implicit equality |
| `{"a": {"$eq": 1}}` | 1 | Explicit equality |
| `{"a": {"$gte": 1, "$lt": 10}}` | 2 | Two conditions on one field |
| `{"a": {"$in": [1, 2, 3]}}` | 1 | One membership condition, regardless of list length |
| `{"a": {"$nin": []}}` | 1 | Still one written condition |
| `{"a": {"b": 1, "c": 2}}` | 1 | Equality against an embedded-document value |
| `{"a": [1, 2]}` | 1 | Equality against an array value |
| `{"a": {"$exists": True, "$type": "number"}}` | 2 | Existence and type are separate conditions |
| `{"a": {"$regex": "^foo", "$options": "i"}}` | 1 | Options modify the regex condition |
| `{"a": {"$all": [1, 2, 3]}}` | 1 | One containment condition |

### Logical and element scopes

`$and`, `$or`, `$nor`, `$not` and `$elemMatch` contribute **zero predicates
themselves**. Count the conditions inside them. They do contribute operators.

| Filter fragment | Predicate count |
| --- | ---: |
| `{"$or": [{"a": 1}, {"b": 2}]}` | 2 |
| `{"$and": [{"a": 1}, {"a": 1}]}` | 2 |
| `{"a": {"$not": {"$gt": 5}}}` | 1 |
| `{"a": {"$elemMatch": {"b": 1, "c": 2}}}` | 2 |
| `{"a": {"$elemMatch": {"$gte": 1, "$lt": 5}}}` | 2 |
| `{"a": {"$elemMatch": {}}}` | 0 |

`$all` is deliberately an atomic boundary, including when its operands contain
`$elemMatch`. For example, `{"a": {"$all": [{"$elemMatch": {"x": 1, "y": 2}}]}}`
has **one predicate**, not three. Its operator histogram is
`{"$all": 1, "$elemMatch": 1, "$eq": 2}`: internal syntax still contributes
operators, but not additional predicates. The same boundary applies recursively
inside that operand.

### Expression-based and document-level conditions

- `$expr` contributes **one opaque filter predicate**. Its internal Boolean or
  arithmetic structure contributes operators, not additional predicates.
- `$text` contributes one predicate; `$search`, `$language`, `$caseSensitive` and
  `$diacriticSensitive` are options and do not contribute predicates or operators.
- `$comment` is an annotation and contributes neither.
- Other document-level operators, including `$jsonSchema` and `$where`, are
  unsupported in version 1 and raise `ValueError`.

For example, `{"$expr": {"$and": [{"$gt": ["$a", "$b"]}, {"$lt": ["$a", 10]}]}}`
has one predicate and four operators: `$expr`, `$and`, `$gt`, `$lt`.

Only `$match` contributes predicates. A Boolean expression in `$project`, `$cond`,
`$filter` or `$redact` does not. The query-filter syntax in
`$graphLookup.restrictSearchWithMatch` contributes operators, but **zero predicates**,
because it is not a `$match` stage. This keeps the predicate metric narrowly defined.

### Multiple match stages

Count **all occurrences in every selected `$match` stage** and preserve the
per-stage counts. Do not consider only the first stage and do not deduplicate.
Identical conditions before and after transformations may describe different data.
Even adjacent identical stages remain separate occurrences.

## Operator count

An operator is a recognized **MongoDB operator occurrence below stage level**,
plus the implicit operators described below. It is not simply a dictionary key
beginning with `$`.

1. Count each explicit operator occurrence once, including logical operators,
   `$elemMatch`, `$expr`, expression operators and accumulators.
2. Normalize implicit equality in filter syntax to `$eq`. Explicit and implicit
   equality therefore share one histogram key.
3. Normalize a native `bson.Regex` or Python compiled regex used directly as a
   field condition to `$regex`. The same applies directly beneath `$not`.
4. Do not invent an implicit `$and` for multiple fields or conditions. An explicit
   `$and` contributes one operator, even when it is logically redundant.
5. Exclude stage names. `$match`, `$group` and other stages belong to `stage_counts`.
   A `$count` accumulator, however, is a below-stage operator and is counted.
6. Exclude argument/option names, including `$options`, the `$text` options,
   `$filter`'s `input`/`as`/`cond`, and `$lookup`'s collection and field names.
7. Treat geospatial shape specifiers (`$geometry`, `$box`, `$center`,
   `$centerSphere`, `$polygon`) and their coordinates as arguments. Count the
   enclosing `$geoWithin` or `$geoIntersects` once, without counting those specifiers.
8. Treat ordinary predicate operands as literal data. Do not recursively inspect
   embedded-document equality values, arrays supplied to `$in`/`$nin`, or scalar
   BSON values. Regex values inside membership lists do not add operators.
   The `$all`/`$elemMatch` exception is specified above.
9. Count `$literal` or `$const` once, then stop traversing its contents. Preserve
   their separate names in the histogram; do not rewrite one as the other.
10. Field references (`"$price"`), variable references (`"$$item"`), projection
    flags and sort directions contribute no operators and no implicit equality.
11. Follow expression syntax through nested lists, expression documents and named
    arguments. An object constructed by an expression is not an equality predicate.
12. Do not deduplicate, simplify, optimize or infer unexpressed operations.

| Fragment and context | Operator histogram |
| --- | --- |
| `{"a": 1, "b": 2}` in `$match` | `{"$eq": 2}` |
| `{"$and": [{"a": 1}, {"b": 2}]}` in `$match` | `{"$and": 1, "$eq": 2}` |
| `{"a": {"$not": {"$gt": 5}}}` in `$match` | `{"$not": 1, "$gt": 1}` |
| `{"a": {"$elemMatch": {"b": 1}}}` in `$match` | `{"$elemMatch": 1, "$eq": 1}` |
| `{"$expr": {"$gt": ["$a", "$b"]}}` in `$match` | `{"$expr": 1, "$gt": 1}` |
| `{"x": {"$literal": {"$gt": 5}}}` in `$project` | `{"$literal": 1}` |
| `{"total": {"$sum": {"$multiply": ["$price", "$qty"]}}}` in `$group` | `{"$sum": 1, "$multiply": 1}` |
| `{"a": 1, "_id": 0}` in `$project` | `{}` |

MongoDB's [expression reference](https://www.mongodb.com/docs/manual/reference/mql/expressions/)
describes the distinction between operators, literals and field references.
The counts themselves are BONDI's versioned research definitions.

## Stage count and nested pipelines

By default, `stage_count` is the length of the outer aggregation pipeline. Count
every occurrence, including explicit no-ops such as `{"$match": {}}`. No pipeline
optimization or implicit-stage insertion occurs during analysis.

| Setting | Scope of all three counts |
| --- | --- |
| `include_nested_pipelines=False` | Outer stages and their local contents; exclude child pipeline bodies |
| `include_nested_pipelines=True` | Outer stages plus all selected child stages recursively |

Version 1 recognizes nested pipelines at:

- `$lookup.pipeline`
- Each named branch of `$facet`
- `$unionWith.pipeline`
- `$merge.whenMatched`, when its value is a pipeline rather than a string action

Each child pipeline must be a list, even when recursive analysis is disabled.
With the default setting its contents are not inspected: unsupported syntax in an
excluded child is not an error. With recursion enabled, unsupported child syntax
raises an error just as unsupported outer syntax does.

An enclosing stage owns only its **local** expressions. For example,
`$lookup.let` belongs to the `$lookup` record, while expressions inside the child
pipeline belong to child records. Nothing is counted twice.

### Paths and traversal order

Stage paths are tuples indexing the analyzed pipeline:

- `(0,)`: the first outer stage.
- `(2, "$lookup", "pipeline", 0)`: the first child stage of the third outer stage.
- `(1, "$facet", "recent", 0)`: the first stage in the `recent` branch.

Recursive records use depth-first preorder: parent, its children, then the next
sibling stage. Named facet branches follow their document insertion order.
Paths are retained even when the corresponding parent contains no operators.

```python
from bondi.mongodb import MongoAggregateQuery

nested = MongoAggregateQuery(
    query.target,
    [
        {
            "$lookup": {
                "from": "other",
                "as": "matches",
                "let": {"threshold": {"$add": ["$price", 1]}},
                "pipeline": [
                    {"$match": {"$expr": {"$gt": ["$price", "$$threshold"]}}},
                    {"$limit": 5},
                ],
            }
        },
        {"$match": {"active": True}},
    ],
)
outer = query_statistics(nested)
recursive = query_statistics(nested, include_nested_pipelines=True)

assert (outer.stage_count, outer.predicate_count, outer.operator_count) == (2, 1, 2)
assert (recursive.stage_count, recursive.predicate_count, recursive.operator_count) == (4, 2, 4)
assert recursive.stages[0].operator_counts == {"$add": 1}
assert recursive.stages[1].path == (0, "$lookup", "pipeline", 0)
assert recursive.stages[1].operator_counts == {"$expr": 1, "$gt": 1}
```

## Find normalization and generated projections

Find normalization emits filtering, sorting, skipping, limiting and projection in
that order. Empty filters/sorts/projections, zero skip and absent limits do not
produce stages. An unrestricted find therefore has zero stages, while an explicit
aggregation `[{"$match": {}}]` has one stage and zero predicates/operators.

Special find projections may expand into multiple stages or generated expressions.
**Those stages and expressions count.** This makes find statistics identical to
statistics from its converted aggregation, but not necessarily to a count of the
operators originally written in the find query.

```python
sliced = MongoFindQuery(query.target, {}, projection={"values": {"$slice": 2}})
converted = sliced.to_aggregate()
assert query_statistics(sliced) == query_statistics(converted)
assert query_statistics(sliced).stage_counts == {"$set": 1}
assert query_statistics(sliced).operator_counts == {"$cond": 1, "$isArray": 1, "$slice": 1}
assert query_statistics(sliced).predicate_count == 0
```

For example, the type checks generated for a special projection are expression
operators, not extra filter predicates. Conversion limitations remain those of
[`to_aggregate()`](find-query.md#array-projections), including bounded positional
bindings and special-projection paths. The statistics parser does not bypass them.

## Worked example with several matches

```python
workload_query = MongoAggregateQuery(
    query.target,
    [
        {"$match": {"status": "active", "age": {"$gte": 18, "$lt": 65}}},
        {"$match": {"$or": [{"country": "AU"}, {"country": "NZ"}]}},
        {"$sort": {"age": 1}},
        {"$limit": 5},
    ],
)
result = query_statistics(workload_query)
assert (result.stage_count, result.predicate_count, result.operator_count) == (4, 5, 6)
assert result.stage_counts == {"$match": 2, "$sort": 1, "$limit": 1}
assert result.operator_counts == {"$eq": 3, "$gte": 1, "$lt": 1, "$or": 1}
assert [stage.predicate_count for stage in result.stages] == [3, 2, 0, 0]
```

## Supported syntax and errors

The parser has explicit supported-syntax registries. An unknown stage, operator,
or argument in a parsed stage configuration raises `ValueError` with its path;
no partial result is returned. The parser validates the structures it traverses,
not every MongoDB arity, type, stage-order or server-version constraint. A successful
analysis is not a promise that the server will accept or execute the query.

Native BSON scalar values remain atomic. Decode external Extended JSON with
[`loads_query_json()`](reference/mongodb/queries.md) before constructing queries;
raw Extended JSON wrapper dictionaries are not a substitute for native values.

### Stages

| Supported stages | Contents inspected |
| --- | --- |
| `$match` | Query filter: predicates and operators |
| `$project`, `$set`, `$addFields`, `$group`, `$sort` | Field values as expressions; flags/directions contribute zero |
| `$replaceWith`, `$redact`, `$sortByCount`, `$documents` | Expression body |
| `$replaceRoot` | `newRoot` expression |
| `$lookup` | `let` expressions; optional child `pipeline` |
| `$facet` | Named child pipelines |
| `$unionWith` | Optional child `pipeline`; collection name is data |
| `$merge` | `let` expressions; optional child `whenMatched` pipeline; targets/actions are data |
| `$graphLookup` | `startWith` expression and operators in `restrictSearchWithMatch`; other configuration is data |
| `$bucket`, `$bucketAuto` | `groupBy` and `output` expressions; boundaries/default/bucket settings are data |
| `$count`, `$limit`, `$skip`, `$unset`, `$sample`, `$unwind`, `$out` | No expression/filter contents; count the stage only |

`$lookup` accepts `from`, `localField`, `foreignField`, `as`, `let`, `pipeline`.
`$unionWith` accepts a collection string or a document with `coll`, `pipeline`.
`$merge` accepts a collection string or `into`, `on`, `let`, `whenMatched`,
`whenNotMatched`. `$graphLookup` accepts `from`, `startWith`, `connectFromField`,
`connectToField`, `as`, `maxDepth`, `depthField`, `restrictSearchWithMatch`.
`$bucket` accepts `groupBy`, `output`, `boundaries`, `default`; `$bucketAuto`
accepts `groupBy`, `output`, `buckets`, `granularity`. Unknown configuration keys
in these parsed documents are rejected.

Other stages, such as `$search`, `$geoNear` and `$setWindowFields`, are not yet
supported. `$out` and `$merge` are analyzed without executing any writes.

### Query-filter operators

The supported field operators are:

- `$eq`, `$ne`, `$gt`, `$gte`, `$lt`, `$lte`, `$in`, `$nin`.
- `$exists`, `$type`, `$mod`, `$regex` (with optional `$options`), `$size`.
- `$bitsAllClear`, `$bitsAllSet`, `$bitsAnyClear`, `$bitsAnySet`.
- `$not`, `$elemMatch`, `$all`, `$geoWithin`, `$geoIntersects`.

Document-level syntax supports ordinary field predicates, `$and`, `$or`, `$nor`,
`$expr`, `$text`, and the ignored `$comment` annotation. `$options` without a
sibling `$regex` is an error. Literal operands of ordinary field operators are
not traversed or validated as expressions.

### Expression and accumulator operators

The following expression/accumulator names are recognized in version 1. Operand
structure is traversed as expression syntax, except for the literal barriers
`$literal` and `$const`. Argument arity and server-specific placement are not fully
validated. Unlisted names fail explicitly, allowing support to be extended with
regression tests rather than producing guessed counts.

`$abs`, `$acos`, `$acosh`, `$add`, `$addToSet`, `$allElementsTrue`, `$and`, `$anyElementTrue`,
`$arrayElemAt`, `$arrayToObject`, `$asin`, `$asinh`, `$atan`, `$atan2`, `$atanh`, `$avg`,
`$binarySize`, `$bsonSize`, `$ceil`, `$cmp`, `$concat`, `$concatArrays`, `$cond`, `$const`,
`$convert`, `$cos`, `$cosh`, `$count`, `$dateAdd`, `$dateDiff`, `$dateFromParts`, `$dateFromString`,
`$dateSubtract`, `$dateToParts`, `$dateToString`, `$dateTrunc`, `$dayOfMonth`, `$dayOfWeek`, `$dayOfYear`, `$degreesToRadians`,
`$divide`, `$eq`, `$exp`, `$filter`, `$first`, `$firstN`, `$floor`, `$getField`,
`$gt`, `$gte`, `$hour`, `$ifNull`, `$in`, `$indexOfArray`, `$indexOfBytes`, `$indexOfCP`,
`$isArray`, `$isNumber`, `$isoDayOfWeek`, `$isoWeek`, `$isoWeekYear`, `$last`, `$lastN`, `$let`,
`$literal`, `$ln`, `$log`, `$log10`, `$lt`, `$lte`, `$ltrim`, `$map`,
`$max`, `$maxN`, `$mergeObjects`, `$meta`, `$millisecond`, `$min`, `$minN`, `$minute`,
`$mod`, `$month`, `$multiply`, `$ne`, `$not`, `$objectToArray`, `$or`, `$pow`,
`$push`, `$radiansToDegrees`, `$rand`, `$range`, `$reduce`, `$regexFind`, `$regexFindAll`, `$regexMatch`,
`$replaceAll`, `$replaceOne`, `$reverseArray`, `$round`, `$rtrim`, `$second`, `$setDifference`, `$setEquals`,
`$setField`, `$setIntersection`, `$setIsSubset`, `$setUnion`, `$sin`, `$sinh`, `$size`, `$slice`,
`$sortArray`, `$split`, `$sqrt`, `$stdDevPop`, `$stdDevSamp`, `$strLenBytes`, `$strLenCP`, `$strcasecmp`,
`$substr`, `$substrBytes`, `$substrCP`, `$subtract`, `$sum`, `$switch`, `$tan`, `$tanh`,
`$toBool`, `$toDate`, `$toDecimal`, `$toDouble`, `$toInt`, `$toLong`, `$toLower`, `$toObjectId`,
`$toString`, `$toUpper`, `$trim`, `$trunc`, `$type`, `$unsetField`, `$week`, `$year`,
`$zip`.

### Error example and versioning

```python
unsupported = MongoAggregateQuery(query.target, [{"$project": {"x": {"$futureOp": 1}}}])
try:
    query_statistics(unsupported)
except ValueError as error:
    assert "(0, '$project', 'x', '$futureOp')" in str(error)
else:
    raise AssertionError("Unknown expression operator should be rejected")
```

Malformed input or unsupported conversion can also fail before parser traversal;
those errors come from the existing query validation/conversion contract. A wrong
query type or non-boolean recursion flag raises `TypeError`.

`definition_version=1` identifies these counting meanings. A change that alters
counts for previously supported syntax requires a new definition version. Adding
support for syntax that previously raised an error need not change the definition
version if existing meanings are preserved. Record the definition version, BONDI
package version and `include_nested_pipelines` setting with research results.
Use consistent settings when comparing projects.

See the [API reference](reference/mongodb/statistics.md) for signatures and result
fields, and [MongoDB queries](find-query.md) for native query representations.
