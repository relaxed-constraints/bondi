"""Aggregation contracts and shared serialization regressions."""

import json
from datetime import datetime

import pytest
from bson import Binary, Decimal128, Int64, ObjectId, Regex, Timestamp

from dbrtoolkit.mongodb import MongoAggregateQuery, MongoCollectionRef, MongoFindQuery

TARGET = MongoCollectionRef("research", "businesses")


def test_pipeline_is_required_but_can_be_empty():
    query = MongoAggregateQuery(TARGET, [])
    assert MongoAggregateQuery.from_json(query.to_json()) == query
    with pytest.raises(TypeError):
        MongoAggregateQuery(TARGET)


def test_nested_pipeline_is_independent_and_mutable():
    stages = [{"$lookup": {"from": "other", "pipeline": [{"$match": {"x": [1]}}], "as": "joined"}}]
    query = MongoAggregateQuery(TARGET, stages)
    sibling = MongoAggregateQuery(TARGET, stages)
    query.pipeline[0]["$lookup"]["pipeline"][0]["$match"]["x"].append(2)
    assert sibling.pipeline == stages
    stages.append({"$limit": 5})
    assert len(query.pipeline) == 1
    assert len(sibling.pipeline) == 1
    with pytest.raises(TypeError):
        hash(query)


@pytest.mark.parametrize(
    "pipeline",
    [[{"$limit": 5}], [{"$out": "result"}], [{"$merge": "result"}], [{"$futureStage": None}]],
)
def test_stage_values_and_write_stages_are_representable(pipeline):
    query = MongoAggregateQuery(TARGET, pipeline)
    assert MongoAggregateQuery.from_json(query.to_json()) == query


@pytest.mark.parametrize(
    "pipeline,error",
    [
        (None, TypeError),
        ((), TypeError),
        ([1], TypeError),
        ([{}], ValueError),
        ([{"$match": {}, "$limit": 1}], ValueError),
        ([{1: {}}], TypeError),
        ([{"match": {}}], ValueError),
        ([{"$": {}}], ValueError),
    ],
)
def test_rejects_invalid_stage_structure(pipeline, error):
    with pytest.raises(error):
        MongoAggregateQuery(TARGET, pipeline)


def test_target_validation():
    with pytest.raises(TypeError, match="target"):
        MongoAggregateQuery("research.businesses", [])


@pytest.mark.parametrize("method", ["validate", "to_json", "fingerprint"])
def test_invalid_mutations_rejected_at_boundaries(method):
    query = MongoAggregateQuery(TARGET, [])
    query.pipeline.append({})
    with pytest.raises(ValueError):
        getattr(query, method)()


def test_validation_does_not_copy_and_nested_semantics_are_deferred():
    query = MongoAggregateQuery(TARGET, [{"$lookup": {"pipeline": ["not validated"]}}])
    original = query.pipeline
    query.validate()
    assert query.pipeline is original


@pytest.mark.parametrize(
    "value",
    [
        ObjectId("0123456789abcdef01234567"),
        Int64(1),
        1,
        1.5,
        Decimal128("1.25"),
        Binary(b"x", 128),
        b"x",
        Regex("a", "i"),
        Timestamp(123, 4),
        datetime(2026, 1, 1),
    ],
)
def test_bson_round_trip_in_nested_pipeline(value):
    query = MongoAggregateQuery(TARGET, [{"$facet": {"part": [{"$match": {"x": value}}]}}])
    restored = MongoAggregateQuery.from_json(query.to_json())
    actual = restored.pipeline[0]["$facet"]["part"][0]["$match"]["x"]
    assert type(actual) is type(value)
    assert actual == value
    assert restored.fingerprint() == query.fingerprint()


def test_fingerprint_preserves_stage_and_sort_key_order_and_target():
    stages = [{"$sort": {"b": -1, "a": 1}}, {"$limit": 2}]
    query = MongoAggregateQuery(TARGET, stages)
    before = query.fingerprint()
    assert before != MongoAggregateQuery(TARGET, stages[::-1]).fingerprint()
    assert (
        before
        != MongoAggregateQuery(TARGET, [{"$sort": {"a": 1, "b": -1}}, {"$limit": 2}]).fingerprint()
    )
    assert (
        before
        != MongoAggregateQuery(MongoCollectionRef("other", "businesses"), stages).fingerprint()
    )
    query.pipeline[1]["$limit"] = 3
    assert before != query.fingerprint()


@pytest.mark.parametrize(
    "mutation",
    [
        lambda d: d.update(extra=True),
        lambda d: d.pop("pipeline"),
        lambda d: d.update(format_version=2),
        lambda d: d.update(format_version=True),
        lambda d: d.update(query_kind="mongodb.find"),
        lambda d: d["target"].update(host="localhost"),
        lambda d: d.update(pipeline={}),
        lambda d: d.update(pipeline=[{}]),
    ],
)
def test_rejects_bad_envelopes(mutation):
    raw = json.loads(MongoAggregateQuery(TARGET, []).to_json())
    mutation(raw)
    with pytest.raises((ValueError, TypeError)):
        MongoAggregateQuery.from_json(json.dumps(raw))


def test_rejects_duplicate_keys_inside_pipeline():
    text = MongoAggregateQuery(TARGET, [{"$match": {}}]).to_json()
    text = text.replace('"$match":{}', '"$match":{},"$match":{}')
    with pytest.raises(ValueError, match="Duplicate"):
        MongoAggregateQuery.from_json(text)


def test_rejects_ambiguous_bson_wrapper_and_relaxed_payload():
    with pytest.raises(ValueError, match="ambiguous"):
        MongoAggregateQuery(TARGET, [{"$match": {"x": {"$numberLong": "1"}}}]).to_json()
    text = MongoAggregateQuery(TARGET, [{"$limit": 2}]).to_json()
    with pytest.raises(ValueError, match="Canonical"):
        MongoAggregateQuery.from_json(text.replace('{"$numberInt":"2"}', "2"))


def test_find_serialization_is_unchanged_by_helper_extraction():
    query = MongoFindQuery(TARGET, {"b": 2, "a": 1}, sort=(("b", -1),), limit=10)
    expected = (
        '{"format_version":{"$numberInt":"1"},"query_kind":"mongodb.find",'
        '"target":{"database":"research","collection":"businesses"},'
        '"filter":{"b":{"$numberInt":"2"},"a":{"$numberInt":"1"}},'
        '"projection":null,"sort":[["b",{"$numberInt":"-1"}]],'
        '"skip":{"$numberInt":"0"},"limit":{"$numberInt":"10"}}'
    )
    assert query.to_json() == expected
    assert query.fingerprint() == "acdf5f2030daddc455641f3c0aac5c549f5b7e7f9d8eedbbf69328f289970fcd"
    assert MongoFindQuery.from_json(expected) == query


def test_query_loaders_reject_other_query_kinds():
    with pytest.raises(ValueError):
        MongoFindQuery.from_json(MongoAggregateQuery(TARGET, []).to_json())
    with pytest.raises(ValueError):
        MongoAggregateQuery.from_json(MongoFindQuery(TARGET, {}).to_json())
