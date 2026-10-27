"""Construction and mutation contracts for MongoDB find queries."""

from datetime import datetime

import pytest

from bondi.mongodb import MongoCollectionRef, MongoFindQuery

TARGET = MongoCollectionRef("research", "businesses")


def test_explicit_unrestricted_query():
    query = MongoFindQuery(TARGET, {})
    assert query.filter == {}
    assert (query.projection, query.sort, query.skip, query.limit) == (None, (), 0, None)
    with pytest.raises(TypeError):
        MongoFindQuery(TARGET)


def test_documents_are_deep_copied_in_both_directions():
    predicate = {"$and": [{"stars": {"$gte": 4}}]}
    projection = {"items": {"$slice": [0, 5]}}
    query = MongoFindQuery(TARGET, predicate, projection)
    sibling = MongoFindQuery(TARGET, predicate, projection)
    query.filter["$and"][0]["stars"]["$gte"] = 5
    query.projection["items"]["$slice"][1] = 10
    assert predicate["$and"][0]["stars"]["$gte"] == 4
    assert projection["items"]["$slice"] == [0, 5]
    predicate["$and"].append({"active": True})
    projection["items"]["$slice"][0] = 2
    assert len(query.filter["$and"]) == 1
    assert query.projection["items"]["$slice"] == [0, 10]
    assert sibling.filter == {"$and": [{"stars": {"$gte": 4}}]}
    assert sibling.projection == {"items": {"$slice": [0, 5]}}


def test_native_values_are_not_json_coerced():
    instant = datetime(2026, 1, 1)
    query = MongoFindQuery(TARGET, {"created": instant, "payload": b"data"})
    assert query.filter == {"created": instant, "payload": b"data"}


def test_mutable_value_equality_without_hashing():
    query = MongoFindQuery(TARGET, {})
    other = MongoFindQuery(TARGET, {})
    assert query == other
    query.limit = 20
    assert query != other
    with pytest.raises(TypeError):
        hash(query)


def test_sort_order_is_preserved_and_affects_equality():
    order = (("stars", -1), ("name", 1))
    query = MongoFindQuery(TARGET, {}, sort=order, skip=2, limit=20)
    assert query.sort == order
    assert query != MongoFindQuery(TARGET, {}, sort=order[::-1], skip=2, limit=20)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("target", "research.businesses"),
        ("filter", None),
        ("filter", []),
        ("projection", ["name"]),
        ("skip", True),
        ("skip", 1.5),
        ("skip", None),
        ("limit", False),
        ("limit", "20"),
        ("sort", [("stars", -1)]),
        ("sort", (["stars", -1],)),
        ("sort", ((42, 1),)),
        ("sort", (("stars", True),)),
        ("sort", (("stars", 1.0),)),
    ],
)
def test_rejects_incorrect_types(field, value):
    kwargs = {"target": TARGET, "filter": {}, field: value}
    with pytest.raises(TypeError):
        MongoFindQuery(**kwargs)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("skip", -1),
        ("limit", 0),
        ("limit", -1),
        ("sort", (("stars",),)),
        ("sort", (("stars", 1, "extra"),)),
        ("sort", (("", 1),)),
        ("sort", (("bad\0name", 1),)),
        ("sort", (("stars", 0),)),
    ],
)
def test_rejects_invalid_values(field, value):
    kwargs = {"target": TARGET, "filter": {}, field: value}
    with pytest.raises(ValueError):
        MongoFindQuery(**kwargs)
