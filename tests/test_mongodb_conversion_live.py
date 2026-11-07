"""Opt-in differential probes; only a uniquely named temporary database is modified.

BONDI_LIVE=1 uv run pytest tests/test_mongodb_conversion_live.py
"""

from uuid import uuid4

import pytest
from pymongo import MongoClient

from bondi.mongodb import MongoCollectionRef, MongoFindQuery

pytestmark = pytest.mark.live


@pytest.fixture(scope="module")
def collection(live_mongodb):
    with MongoClient(live_mongodb.uri, serverSelectionTimeoutMS=5000) as client:
        database = client[f"bondi_conversion_test_{uuid4().hex}"]
        collection = database.items
        values = [
            None,
            False,
            True,
            -2,
            0,
            1,
            2,
            3.5,
            "",
            "a",
            "$value",
            [],
            [1, 3],
            {"x": 1},
            {"x": [1, 3]},
            {"x": None},
            {},
            {"x": "a"},
            {"x": False},
        ]
        documents = [
            {"_id": 0, "other": "missing"},
            *(
                {"_id": i + 1, "a": value, "other": i, "hide": True}
                for i, value in enumerate(values)
            ),
            {"_id": 100, "a": values, "other": 100},
            {"_id": 101, "a": list(reversed(values)), "other": 101},
            {"_id": 102, "a": [{"x": 3, "y": "a"}, {"x": 1}, {"x": [1, 3]}]},
        ]
        # Singleton arrays prevent an earlier matching element from masking errors.
        extra = values + [
            [{"x": 1}],
            [[1]],
            {"x": []},
            {"x": [None]},
            {"x": [[1], None]},
            {"x": {"y": 1}},
            {"x": [False, 0]},
        ]
        documents.extend(
            {"_id": 200 + i, "a": [value], "other": i} for i, value in enumerate(extra)
        )
        collection.insert_many(documents)
        try:
            yield collection
        finally:
            client.drop_database(database.name)


def compare(collection, predicate, projection, skip=0, limit=None):
    query = MongoFindQuery(
        MongoCollectionRef(collection.database.name, collection.name),
        predicate,
        projection,
        (("_id", 1),),
        skip,
        limit,
    )
    cursor = collection.find(query.filter, query.projection).sort(list(query.sort)).skip(skip)
    if limit is not None:
        cursor = cursor.limit(limit)
    expected = list(cursor)
    actual = list(collection.aggregate(query.to_aggregate().pipeline))
    assert actual == expected, (predicate, projection, expected, actual)


@pytest.mark.parametrize(
    "projection", [None, {}, {"a": 1, "_id": 0}, {"other": 0}, {"_id": 1, "other": 0}, {"a.x": 1}]
)
def test_basic_live(collection, projection):
    compare(collection, {"_id": {"$gte": 2}}, projection, skip=2, limit=10)


@pytest.mark.parametrize(
    "specification", [0, 1, 2, -1, -3, [0, 2], [2, 3], [-2, 3], [-100, 2], [100, 2]]
)
@pytest.mark.parametrize(
    "flags", [{}, {"_id": 0}, {"_id": 1}, {"other": 1}, {"hide": 0}, {"_id": 1, "hide": 0}]
)
def test_slice_live(collection, specification, flags):
    compare(collection, {}, {"a": {"$slice": specification}, **flags})


CONDITIONS = [
    {"$eq": 1},
    {"$eq": None},
    {"$eq": False},
    {"$eq": "$value"},
    {"$ne": 1},
    {"$ne": None},
    {"$gt": 1},
    {"$gte": 1, "$lt": 4},
    {"$in": [None, 1, "a"]},
    {"$nin": [None, 1]},
    {"$in": []},
    {"$nin": []},
    {"$not": {"$gte": 1}},
    {"x": 1},
    {"x": None},
    {"x": {"$ne": None}},
    {"x": {"$gt": 1}},
    {"x": {"$gte": 1, "$lt": 4}},
    {"x": {"$in": [1, None, False]}},
    {"x": {"$nin": [1, None]}},
    {"$and": [{"x": {"$gte": 1}}, {"y": "a"}]},
    {"$or": [{"x": 1}, {"y": "a"}]},
    {"$nor": [{"x": 1}, {"y": "a"}]},
]


@pytest.mark.parametrize("condition", CONDITIONS)
@pytest.mark.parametrize("flags", [{}, {"_id": 0}, {"other": 1}])
def test_elem_match_live(collection, condition, flags):
    compare(collection, {}, {"a": {"$elemMatch": condition}, **flags})


@pytest.mark.parametrize("condition", CONDITIONS)
def test_positional_live(collection, condition):
    compare(collection, {"a": {"$elemMatch": condition}}, {"a.$": 1, "_id": 0})


@pytest.mark.parametrize(
    "projection",
    [
        {"a": {"$slice": -2}, "other": {"$slice": 0}},
        {"a": {"$elemMatch": {"x": 1}}, "other": {"$slice": 1}},
        {"a": {"$elemMatch": {"x": 1}}, "other": {"$slice": 1}, "_id": 1},
        {"a": {"$elemMatch": {"x": 1}}, "hide": 0},
        {"a": {"$slice": 2}, "other": 0, "_id": 0},
    ],
)
def test_combined_projections_live(collection, projection):
    compare(collection, {}, projection, skip=1, limit=40)
