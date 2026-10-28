"""Versioned pattern persistence and independent nested representations."""

import json
from copy import deepcopy

import pytest

from bondi.mongodb import MongoCollectionRef, MongoFindQuery, MongoQueryPattern


def pattern(projection=None):
    return MongoQueryPattern.from_query(
        MongoFindQuery(
            MongoCollectionRef("demo", "business"),
            {
                "city": {"$in": ["Sydney", "Melbourne"]},
                "x": {"$exists": False},
                "y": {"$type": "string"},
                "tags": {"$size": 2},
                "n": None,
            },
            sort=(("y", -1), ("city", 1)),
            projection=projection,
            skip=2,
            limit=10,
        )
    )


@pytest.mark.parametrize("projection", [None, {}, {"city": 1, "_id": 0}])
def test_round_trip(projection):
    original = pattern(projection)
    data = original.to_dict()
    assert json.loads(original.to_json()) == data
    for restored in (
        MongoQueryPattern.from_dict(data),
        MongoQueryPattern.from_json(original.to_json()),
    ):
        assert restored == original
        assert hash(restored) == hash(original)
        assert str(restored) == str(original)
        assert restored.sort == (("y", -1), ("city", 1))
    restored = MongoQueryPattern.from_dict(data)
    data["target"]["database"] = "changed"
    data["predicates"][0]["field"] = "changed"
    data["sort"][0][0] = "changed"
    assert restored == original
    assert original.to_dict()["target"]["database"] == "demo"


@pytest.mark.parametrize(
    "field,value",
    [
        ("format_version", True),
        ("format_version", 2),
        ("pattern_kind", "other"),
        ("target", {}),
        ("predicates", []),
        ("predicates", {}),
        ("sort", [["x", True]]),
        ("sort", [["x"]]),
        ("sort", {}),
        ("projection", [["x", 2]]),
        ("skip", -1),
        ("limit", 0),
    ],
)
def test_invalid_envelopes(field, value):
    data = pattern().to_dict()
    data[field] = value
    with pytest.raises((ValueError, TypeError)):
        MongoQueryPattern.from_dict(data)


def test_missing_unknown_and_invalid_predicate_fields():
    data = pattern().to_dict()
    for key in data:
        invalid = deepcopy(data)
        del invalid[key]
        with pytest.raises(ValueError):
            MongoQueryPattern.from_dict(invalid)
    data["extra"] = 1
    with pytest.raises(ValueError):
        MongoQueryPattern.from_dict(data)
    data = pattern().to_dict()
    data["predicates"][0]["operator"] = "unsupported"
    with pytest.raises(ValueError):
        MongoQueryPattern.from_dict(data)


@pytest.mark.parametrize("text", ["null", "[]", "{", '{"x":1,"x":2}', '{"x":NaN}'])
def test_invalid_json(text):
    with pytest.raises((ValueError, TypeError)):
        MongoQueryPattern.from_json(text)


def test_initial_query_still_matches_restored_pattern():
    query = MongoFindQuery(MongoCollectionRef("a", "b"), {"stars": {"$gte": 4.5}})
    restored = MongoQueryPattern.from_json(MongoQueryPattern.from_query(query).to_json())
    assert restored.matches(query)
