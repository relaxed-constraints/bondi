"""Version-1 statistics definitions, scope boundaries and documented examples."""

import re
from collections import Counter
from copy import deepcopy
from datetime import datetime
from pathlib import Path

import pytest
from bson import ObjectId, Regex

from bondi.mongodb import (
    MongoAggregateQuery,
    MongoCollectionRef,
    MongoFindQuery,
    MongoQueryStatistics,
    MongoStageStatistics,
    query_statistics,
)

TARGET = MongoCollectionRef("research", "items")


def aggregate(*stages):
    return MongoAggregateQuery(TARGET, list(stages))


@pytest.mark.parametrize(
    ("predicate", "count", "operators"),
    [
        ({}, 0, {}),
        ({"a": 1}, 1, {"$eq": 1}),
        ({"a": {"$eq": 1}}, 1, {"$eq": 1}),
        ({"a": {"$gte": 1, "$lt": 10}}, 2, {"$gte": 1, "$lt": 1}),
        ({"a": {"$in": [1, 2, 3]}}, 1, {"$in": 1}),
        ({"a": {"b": 1, "c": 2}}, 1, {"$eq": 1}),
        ({"a": [1, {"$eq": "data"}]}, 1, {"$eq": 1}),
        ({"$or": [{"a": 1}, {"b": 2}]}, 2, {"$or": 1, "$eq": 2}),
        ({"$nor": [{"a": 1}, {"b": 2}]}, 2, {"$nor": 1, "$eq": 2}),
        ({"$and": [{"a": 1}, {"a": 1}]}, 2, {"$and": 1, "$eq": 2}),
        ({"a": {"$not": {"$gt": 5}}}, 1, {"$not": 1, "$gt": 1}),
        ({"a": {"$elemMatch": {"b": 1, "c": 2}}}, 2, {"$elemMatch": 1, "$eq": 2}),
        ({"a": {"$elemMatch": {"$gte": 1, "$lt": 5}}}, 2, {"$elemMatch": 1, "$gte": 1, "$lt": 1}),
        ({"a": {"$elemMatch": {}}}, 0, {"$elemMatch": 1}),
        ({"a": {"$regex": "^foo", "$options": "i"}}, 1, {"$regex": 1}),
        ({"a": Regex("foo", "i")}, 1, {"$regex": 1}),
        ({"a": re.compile("foo")}, 1, {"$regex": 1}),
        ({"a": {"$not": Regex("foo")}}, 1, {"$not": 1, "$regex": 1}),
        ({"a": {"$in": [Regex("foo"), {"$literal": "data"}]}}, 1, {"$in": 1}),
        ({"a": {"$eq": {"$unknown": {"$gt": 1}}}}, 1, {"$eq": 1}),
        ({"a": {"$all": [1, 2, 3]}}, 1, {"$all": 1}),
        (
            {"a": {"$all": [{"$elemMatch": {"x": 1, "y": {"$gt": 2}}}]}},
            1,
            {"$all": 1, "$elemMatch": 1, "$eq": 1, "$gt": 1},
        ),
        (
            {"$expr": {"$and": [{"$gt": ["$a", "$b"]}, {"$lt": ["$a", 10]}]}},
            1,
            {"$expr": 1, "$and": 1, "$gt": 1, "$lt": 1},
        ),
        ({"$text": {"$search": "$eq", "$caseSensitive": True}}, 1, {"$text": 1}),
        ({"$comment": {"$eq": "annotation"}}, 0, {}),
        (
            {"a": {"$geoWithin": {"$geometry": {"type": "Polygon", "coordinates": []}}}},
            1,
            {"$geoWithin": 1},
        ),
        (
            {"a": {"$geoIntersects": {"$geometry": {"type": "Point", "coordinates": [0, 0]}}}},
            1,
            {"$geoIntersects": 1},
        ),
        ({"a": {"$exists": True, "$type": "number"}}, 2, {"$exists": 1, "$type": 1}),
        ({"a": {"$size": 3, "$mod": [2, 0]}}, 2, {"$size": 1, "$mod": 1}),
        ({"a": {"$bitsAllSet": [1, 2]}}, 1, {"$bitsAllSet": 1}),
        ({"a": ObjectId(), "b": datetime(2025, 1, 1)}, 2, {"$eq": 2}),
    ],
)
def test_predicate_definitions(predicate, count, operators):
    stats = query_statistics(aggregate({"$match": predicate}))
    assert stats.predicate_count == count
    assert stats.operator_counts == operators
    assert stats.operator_count == sum(operators.values())
    assert stats.stage_counts == {"$match": 1}


@pytest.mark.parametrize(
    ("stage", "operators"),
    [
        ({"$project": {"a": 1, "_id": 0, "nested": {"b": 1}}}, {}),
        ({"$sort": {"a": 1, "b": -1}}, {}),
        ({"$sort": {"score": {"$meta": "textScore"}}}, {"$meta": 1}),
        ({"$project": {"a": "$b", "v": "$$variable"}}, {}),
        ({"$project": {"a": {"$literal": {"$unknown": [{"$gt": 2}]}}}}, {"$literal": 1}),
        ({"$project": {"a": {"$const": {"$match": {"a": 1}}}}}, {"$const": 1}),
        (
            {"$group": {"_id": "$a", "total": {"$sum": {"$multiply": ["$p", "$q"]}}}},
            {"$sum": 1, "$multiply": 1},
        ),
        (
            {"$set": {"a": {"$filter": {"input": "$a", "as": "v", "cond": {"$gt": ["$$v", 1]}}}}},
            {"$filter": 1, "$gt": 1},
        ),
        (
            {"$addFields": {"a": {"$let": {"vars": {"x": {"$add": [1, 2]}}, "in": "$$x"}}}},
            {"$let": 1, "$add": 1},
        ),
        (
            {"$replaceRoot": {"newRoot": {"$mergeObjects": ["$$ROOT", {"x": {"$add": [1, 2]}}]}}},
            {"$mergeObjects": 1, "$add": 1},
        ),
        ({"$replaceWith": {"$literal": {"$fake": 1}}}, {"$literal": 1}),
        ({"$redact": {"$cond": [{"$gt": ["$a", 2]}, "$$KEEP", "$$PRUNE"]}}, {"$cond": 1, "$gt": 1}),
        ({"$sortByCount": {"$toLower": "$a"}}, {"$toLower": 1}),
        ({"$documents": [{"x": {"$literal": {"$match": {}}}}]}, {"$literal": 1}),
        (
            {
                "$bucket": {
                    "groupBy": {"$add": ["$a", 1]},
                    "boundaries": [0, 10],
                    "default": {"$eq": "data"},
                    "output": {"n": {"$sum": 1}},
                }
            },
            {"$add": 1, "$sum": 1},
        ),
        (
            {"$bucketAuto": {"groupBy": "$a", "buckets": 5, "output": {"n": {"$sum": 1}}}},
            {"$sum": 1},
        ),
        (
            {
                "$graphLookup": {
                    "from": "items",
                    "startWith": {"$add": ["$a", 1]},
                    "connectFromField": "a",
                    "connectToField": "b",
                    "as": "out",
                    "restrictSearchWithMatch": {"x": 1, "y": {"$gt": 2}},
                }
            },
            {"$add": 1, "$eq": 1, "$gt": 1},
        ),
    ],
)
def test_expression_definitions(stage, operators):
    stats = query_statistics(aggregate(stage))
    assert stats.operator_counts == operators
    assert stats.operator_count == sum(operators.values())
    assert stats.predicate_count == 0


def test_multiple_matches_and_stage_occurrences():
    query = aggregate(
        {"$match": {"a": 1}},
        {"$match": {"a": 1}},
        {"$match": {}},
        {"$sort": {"a": 1}},
        {"$skip": 2},
        {"$limit": 5},
        {"$project": {"a": 1}},
        {"$count": "n"},
        {"$out": "copy"},
    )
    stats = query_statistics(query)
    assert (stats.stage_count, stats.predicate_count, stats.operator_count) == (9, 2, 2)
    assert [stage.predicate_count for stage in stats.stages] == [1, 1, 0, 0, 0, 0, 0, 0, 0]
    assert [stage.path for stage in stats.stages] == [(i,) for i in range(9)]
    assert stats.stage_counts["$match"] == 3


def test_find_conversion_empty_and_generated_expressions():
    find = MongoFindQuery(TARGET, {"a": 1}, sort=(("b", 1),), skip=2, limit=5, projection={"a": 1})
    stats = query_statistics(find)
    assert (stats.stage_count, stats.predicate_count, stats.operator_count) == (5, 1, 1)
    assert stats == query_statistics(find.to_aggregate())
    assert query_statistics(MongoFindQuery(TARGET, {})).stage_count == 0
    assert query_statistics(aggregate({"$match": {}})).stage_count == 1
    sliced = query_statistics(MongoFindQuery(TARGET, {}, projection={"a": {"$slice": 2}}))
    assert sliced.stage_counts == {"$set": 1}
    assert sliced.operator_counts == {"$cond": 1, "$isArray": 1, "$slice": 1}
    assert sliced.predicate_count == 0
    positional = MongoFindQuery(TARGET, {"a": {"$elemMatch": {"x": 1}}}, {"a.$": 1})
    assert query_statistics(positional) == query_statistics(positional.to_aggregate())
    with pytest.raises(ValueError, match="to_aggregate"):
        query_statistics(MongoFindQuery(TARGET, {}, {"a.$": 1}))


def test_nested_scope_paths_and_no_double_counting():
    query = aggregate(
        {
            "$lookup": {
                "from": "other",
                "as": "out",
                "let": {"x": {"$add": ["$x", 1]}},
                "pipeline": [
                    {"$match": {"$expr": {"$eq": ["$x", "$$x"]}}},
                    {"$facet": {"first": [{"$match": {"a": 1}}], "second": [{"$limit": 5}]}},
                ],
            }
        },
        {"$unionWith": {"coll": "other", "pipeline": [{"$match": {"a": 1}}]}},
        {
            "$merge": {
                "into": "other",
                "let": {"v": {"$multiply": ["$x", 2]}},
                "whenMatched": [{"$set": {"x": {"$add": ["$x", "$$v"]}}}],
            }
        },
    )
    local = query_statistics(query)
    assert (local.stage_count, local.predicate_count, local.operator_count) == (3, 0, 2)
    recursive = query_statistics(query, include_nested_pipelines=True)
    assert (recursive.stage_count, recursive.predicate_count, recursive.operator_count) == (9, 3, 7)
    assert [s.path for s in recursive.stages] == [
        (0,),
        (0, "$lookup", "pipeline", 0),
        (0, "$lookup", "pipeline", 1),
        (0, "$lookup", "pipeline", 1, "$facet", "first", 0),
        (0, "$lookup", "pipeline", 1, "$facet", "second", 0),
        (1,),
        (1, "$unionWith", "pipeline", 0),
        (2,),
        (2, "$merge", "whenMatched", 0),
    ]
    assert recursive.stages[0].operator_counts == {"$add": 1}
    assert recursive.stage_count == sum(recursive.stage_counts.values())
    assert recursive.operator_count == sum(s.operator_count for s in recursive.stages)
    assert recursive.predicate_count == sum(s.predicate_count for s in recursive.stages)
    combined = Counter()
    for stage in recursive.stages:
        combined.update(stage.operator_counts)
    assert recursive.operator_counts == combined


def test_skipped_nested_content_is_not_inspected():
    query = aggregate({"$facet": {"branch": [{"$futureStage": {"$futureOperator": 1}}]}})
    assert query_statistics(query).stage_count == 1
    with pytest.raises(ValueError, match="futureStage") as error:
        query_statistics(query, include_nested_pipelines=True)
    assert "(0, '$facet', 'branch', 0, '$futureStage')" in str(error.value)
    with pytest.raises(ValueError, match="pipeline must be a list"):
        query_statistics(aggregate({"$lookup": {"pipeline": {}}}))


@pytest.mark.parametrize(
    "stage",
    [
        {"$future": {}},
        {"$project": {"a": {"$future": 1}}},
        {"$match": {"$jsonSchema": {}}},
        {"$match": {"a": {"$future": 1}}},
        {"$match": {"a": {"$options": "i"}}},
        {"$match": {"$and": []}},
        {"$match": {"a": {"$not": 1}}},
        {"$match": {"a": {"$all": 1}}},
        {"$match": {"a": {"$elemMatch": []}}},
        {"$match": []},
        {"$lookup": {"let": {}, "future": {"$add": [1, 2]}}},
        {"$replaceRoot": {}},
        {"$project": {"a": {"$add": [1], "$sum": [2]}}},
        {"$match": {"$text": {"$unknown": 1}}},
    ],
)
def test_unsupported_and_malformed_syntax_reports_path(stage):
    with pytest.raises(ValueError, match=r"query_statistics\(\) at \(0,"):
        query_statistics(aggregate(stage))


def test_snapshots_revalidation_and_types():
    query = aggregate({"$match": {"a": 1}})
    original = deepcopy(query)
    stats = query_statistics(query)
    assert isinstance(stats, MongoQueryStatistics)
    assert isinstance(stats.stages[0], MongoStageStatistics)
    assert stats.definition_version == 1
    assert query == original
    stats.operator_counts["$eq"] = 100
    assert stats.stages[0].operator_counts == {"$eq": 1}
    query.pipeline[0]["$match"]["b"] = 2
    assert stats.predicate_count == 1
    assert query_statistics(query).predicate_count == 2
    query.pipeline.append({})
    with pytest.raises(ValueError):
        query_statistics(query)
    with pytest.raises(TypeError, match="query must"):
        query_statistics([])
    with pytest.raises(TypeError, match="boolean"):
        query_statistics(original, include_nested_pipelines=1)


def test_documentation_examples_execute():
    root = Path(__file__).resolve().parents[1]
    for filename in ("docs/mongodb-query-statistics.md", "docs/reference/mongodb/statistics.md"):
        namespace = {}
        for block in re.findall(r"```python\n(.*?)```", (root / filename).read_text(), re.DOTALL):
            exec(compile(block, filename, "exec"), namespace)


@pytest.mark.parametrize(
    ("expression", "depth"),
    [
        ("$price", 0),
        ("$$ROOT", 0),
        (5, 0),
        ({"$add": ["$price", 1]}, 1),
        ({"$multiply": [{"$add": ["$price", 1]}, "$quantity"]}, 2),
        ({"$literal": {"$add": [{"$multiply": [1, 2]}, 3]}}, 1),
        ({"$add": [{"$const": {"$unknown": 1}}, 2]}, 2),
        ({"nested": [{"value": {"$add": [1, 2]}}]}, 1),
        ({"$let": {"vars": {"x": {"$add": [1, 2]}}, "in": {"$multiply": ["$$x", 3]}}}, 2),
        (
            {
                "$filter": {
                    "input": "$items",
                    "as": "item",
                    "cond": {"$and": [{"$gt": ["$$item", 1]}, {"$lt": ["$$item", 5]}]},
                }
            },
            3,
        ),
    ],
)
def test_expression_depth(expression, depth):
    stats = query_statistics(aggregate({"$project": {"value": expression}}))
    assert stats.expression_depth == stats.stages[0].expression_depth == depth
    assert stats.filter_logical_depth == stats.filter_logical_fan_out == 0


@pytest.mark.parametrize(
    ("predicate", "depth", "fan_out"),
    [
        ({}, 0, 0),
        ({"a": 1}, 0, 0),
        ({"a": {"x": 1, "y": 2}}, 0, 0),
        ({"a": {1: "literal data"}}, 0, 0),
        ({"a": {"$in": [1, 2, 3]}}, 0, 0),
        ({"a": 1, "b": 2, "c": 3}, 1, 3),
        ({"$and": [{"a": 1}, {"b": 2}, {"c": 3}]}, 1, 3),
        ({"a": {"$gte": 1, "$lt": 5}}, 1, 2),
        ({"a": {"$gte": 1, "$lt": 5}, "b": 2}, 1, 3),
        ({"$or": [{"a": 1}, {"$and": [{"b": 2}, {"c": 3}]}, {"d": 4}]}, 2, 3),
        ({"$or": [{"a": 1, "b": 2}, {"c": 3}]}, 2, 2),
        ({"$or": [{"a": 1}, {"b": 2}], "c": 3}, 2, 2),
        ({"$and": [{"$and": [{"a": 1}]}]}, 2, 1),
        ({"$nor": [{"a": 1}, {"b": 2}]}, 1, 2),
        ({"a": {"$not": {"$gt": 5}}}, 1, 1),
        ({"a": {"$not": {"$gt": 5, "$lt": 10}}}, 2, 2),
        ({"a": {"$not": Regex("foo")}}, 1, 1),
        ({"a": {"$regex": "foo", "$options": "i"}, "$comment": "annotation"}, 0, 0),
        ({"$comment": "annotation"}, 0, 0),
        ({"a": {"$elemMatch": {"x": 1, "y": 2}}}, 1, 2),
        ({"a": {"$elemMatch": {"x": 1, "y": 2}}, "b": 1}, 2, 2),
        ({"a": {"$elemMatch": {"$gt": 1, "$lt": 5}}}, 1, 2),
        ({"a": {"$elemMatch": {}}}, 0, 0),
        ({"a": {"$all": [{"$elemMatch": {"x": 1, "y": 2}}]}}, 0, 0),
        ({"$expr": {"$and": [{"$gt": ["$a", 1]}, {"$lt": ["$a", 5]}]}}, 0, 0),
    ],
)
def test_filter_logical_structure(predicate, depth, fan_out):
    stats = query_statistics(aggregate({"$match": predicate}))
    assert stats.filter_logical_depth == stats.stages[0].filter_logical_depth == depth
    assert stats.filter_logical_fan_out == stats.stages[0].filter_logical_fan_out == fan_out


def test_expression_and_filter_depth_boundaries():
    stats = query_statistics(
        aggregate(
            {
                "$match": {
                    "$and": [{"a": {"$gt": 1}}, {"$expr": {"$gt": [{"$add": ["$x", 1]}, "$y"]}}]
                }
            },
            {"$group": {"_id": None, "total": {"$sum": {"$multiply": ["$x", "$y"]}}}},
            {
                "$graphLookup": {
                    "from": "other",
                    "as": "out",
                    "startWith": "$x",
                    "connectFromField": "a",
                    "connectToField": "b",
                    "restrictSearchWithMatch": {"a": 1, "b": 2, "c": 3},
                }
            },
        )
    )
    assert stats.expression_depth == 2
    assert stats.filter_logical_depth == 1
    assert stats.filter_logical_fan_out == 2
    assert stats.stages[0].expression_depth == 2  # $expr and $and add no expression levels.
    assert stats.stages[1].expression_depth == 2  # Accumulator contributes one level.
    assert stats.stages[2].filter_logical_depth == stats.stages[2].filter_logical_fan_out == 0
    assert stats.stages[2].operator_counts == {"$eq": 3}


def test_recursive_structural_maxima_and_empty_pipelines():
    query = aggregate(
        {
            "$lookup": {
                "from": "other",
                "as": "out",
                "let": {"v": {"$add": [1, 2]}},
                "pipeline": [
                    {"$match": {"$or": [{"a": 1, "b": 2}, {"c": 3}, {"d": 4}]}},
                    {"$project": {"x": {"$sum": {"$multiply": ["$x", "$y"]}}}},
                    {
                        "$facet": {
                            "deep": [{"$unionWith": {"coll": "other", "pipeline": []}}],
                            "wide": [],
                            "another": [],
                        }
                    },
                ],
            }
        },
        {"$merge": {"into": "other", "whenMatched": []}},
    )
    outer = query_statistics(query)
    assert (
        outer.expression_depth,
        outer.filter_logical_depth,
        outer.filter_logical_fan_out,
        outer.nested_pipeline_depth,
    ) == (1, 0, 0, 0)
    recursive = query_statistics(query, include_nested_pipelines=True)
    assert (
        recursive.expression_depth,
        recursive.filter_logical_depth,
        recursive.filter_logical_fan_out,
        recursive.nested_pipeline_depth,
    ) == (2, 2, 3, 3)
    assert recursive.stage_count == 6  # Empty pipelines have depth but no stage records.
    assert recursive.stages[0].expression_depth == 1  # Parent excludes child expressions.
    assert recursive.stages[0].filter_logical_depth == 0
    assert recursive.stages[-1].name == "$merge"


@pytest.mark.parametrize(
    "stage",
    [
        {"$lookup": {"from": "other", "as": "out", "pipeline": []}},
        {"$facet": {"a": [], "b": []}},
        {"$unionWith": {"coll": "other", "pipeline": []}},
        {"$merge": {"into": "other", "whenMatched": []}},
    ],
)
def test_empty_child_pipeline_depth(stage):
    query = aggregate(stage)
    assert query_statistics(query).nested_pipeline_depth == 0
    stats = query_statistics(query, include_nested_pipelines=True)
    assert stats.nested_pipeline_depth == 1
    assert stats.stage_count == 1


def test_empty_and_flat_structure_and_find_generated_depth():
    for query in (
        aggregate(),
        aggregate({"$facet": {}}),
        aggregate({"$unionWith": "other"}, {"$merge": "other"}),
        MongoFindQuery(TARGET, {}),
    ):
        stats = query_statistics(query, include_nested_pipelines=True)
        assert (
            stats.expression_depth
            == stats.filter_logical_depth
            == stats.filter_logical_fan_out
            == 0
        )
        assert stats.nested_pipeline_depth == 0
    query = MongoFindQuery(TARGET, {"a": 1, "b": 2}, projection={"items": {"$slice": 2}})
    stats = query_statistics(query)
    assert stats == query_statistics(query.to_aggregate())
    assert stats.expression_depth == 2  # $cond contains $isArray and $slice.
    assert (stats.filter_logical_depth, stats.filter_logical_fan_out) == (1, 2)
    assert stats.operator_counts["$eq"] == 2
    assert "$and" not in stats.operator_counts
    assert stats.definition_version == 1
