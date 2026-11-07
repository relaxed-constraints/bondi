"""Contracts for independent, conservative find-to-aggregation conversion."""

import pytest

from bondi.mongodb import MongoAggregateQuery, MongoCollectionRef, MongoFindQuery

TARGET = MongoCollectionRef("conversion", "items")


def test_conversion_order_and_independence():
    query = MongoFindQuery(
        TARGET, {"x": {"$in": [1, 2]}}, {"x": True, "_id": 0}, (("x", -1), ("_id", 1)), 2, 5
    )
    converted = query.to_aggregate()
    assert isinstance(converted, MongoAggregateQuery)
    assert converted.target == TARGET
    assert converted.pipeline == [
        {"$match": {"x": {"$in": [1, 2]}}},
        {"$sort": {"x": -1, "_id": 1}},
        {"$skip": 2},
        {"$limit": 5},
        {"$project": {"x": 1, "_id": 0}},
    ]
    converted.pipeline[0]["$match"]["x"]["$in"].append(3)
    converted.pipeline[-1]["$project"]["x"] = 0
    assert query.filter == {"x": {"$in": [1, 2]}}
    assert query.projection == {"x": True, "_id": 0}
    assert MongoAggregateQuery.from_json(converted.to_json()) == converted


def test_empty_and_revalidation():
    query = MongoFindQuery(TARGET, {}, {})
    assert query.to_aggregate().pipeline == []
    query.limit = 0
    with pytest.raises(ValueError, match="limit"):
        query.to_aggregate()


@pytest.mark.parametrize(
    "predicate",
    [
        {"$where": "true"},
        {"p": {"$near": [0, 0]}},
        {"$or": [{"p": {"$nearSphere": [0, 0]}}]},
        {"a": {"$elemMatch": {"$where": "true"}}},
    ],
)
def test_unsupported_filters(predicate):
    with pytest.raises(ValueError, match="filter operator"):
        MongoFindQuery(TARGET, predicate).to_aggregate()


def test_literal_operator_names_are_not_reinterpreted():
    predicate = {
        "x": {"$eq": {"$near": "data"}},
        "$expr": {"$eq": [{"$literal": {"$where": "data"}}, 1]},
    }
    assert MongoFindQuery(TARGET, predicate).to_aggregate().pipeline == [{"$match": predicate}]


@pytest.mark.parametrize(
    "projection",
    [
        {"a.$": 1},
        {"a.0": 1},
        {"a": {"$slice": 2}},
        {"a": {"$elemMatch": {"x": 1}}},
        {"a": {"$add": [1, 2]}},
        {"a": 1, "b": 0},
    ],
)
def test_unsupported_projections(projection):
    with pytest.raises(ValueError, match="projection"):
        MongoFindQuery(TARGET, {}, projection).to_aggregate()


@pytest.mark.parametrize("sort", [(("$natural", 1),), (("a", 1), ("a", -1))])
def test_unsupported_sorts(sort):
    with pytest.raises(ValueError, match="sort"):
        MongoFindQuery(TARGET, {}, sort=sort).to_aggregate()
