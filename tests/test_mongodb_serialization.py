"""BSON fidelity, strict loading and representation identity."""

import json
from datetime import UTC, datetime, timedelta, timezone

import pytest
from bson import Binary, Decimal128, Int64, ObjectId, Regex, Timestamp, json_util

from bondi.mongodb import MongoCollectionRef, MongoFindQuery

TARGET = MongoCollectionRef("research", "businesses")


@pytest.mark.parametrize(
    "value",
    [
        ObjectId("0123456789abcdef01234567"),
        Int64(1),
        1,
        1.5,
        Decimal128("1.25"),
        Binary(b"data", subtype=128),
        b"data",
        Regex("^hello", "i"),
        Timestamp(123, 4),
        None,
        True,
    ],
)
def test_bson_types_and_fingerprints_round_trip(value):
    query = MongoFindQuery(TARGET, {"nested": [{"value": value}]})
    restored = MongoFindQuery.from_json(query.to_json())
    actual = restored.filter["nested"][0]["value"]
    assert type(actual) is type(value)
    assert actual == value
    assert restored.fingerprint() == query.fingerprint()


def test_complete_envelope_and_sort_order():
    query = MongoFindQuery(
        TARGET, {"b": 2, "a": 1}, {"items": {"$slice": 2}}, (("b", -1), ("a", 1)), 2**35, 2**36
    )
    restored = MongoFindQuery.from_json(query.to_json())
    assert restored == query
    assert list(restored.filter) == ["b", "a"]
    assert type(restored.skip) is int
    assert type(restored.limit) is int
    assert restored.fingerprint() == query.fingerprint()
    envelope = json_util.loads(query.to_json())
    assert set(envelope) == {
        "format_version",
        "query_kind",
        "target",
        "filter",
        "projection",
        "sort",
        "skip",
        "limit",
    }


@pytest.mark.parametrize(
    "instant",
    [
        datetime(2026, 1, 1, microsecond=123456),
        datetime(2026, 1, 1, microsecond=123456, tzinfo=timezone(timedelta(hours=11))),
    ],
)
def test_datetime_normalization(instant):
    query = MongoFindQuery(TARGET, {"date": instant})
    restored = MongoFindQuery.from_json(query.to_json())
    expected = instant.replace(tzinfo=UTC) if instant.tzinfo is None else instant
    expected = expected.astimezone(UTC).replace(tzinfo=None, microsecond=123000)
    assert restored.filter["date"] == expected
    assert query.filter["date"] == instant
    assert restored.fingerprint() == query.fingerprint()


def test_binary_zero_and_large_integer_normalization():
    query = MongoFindQuery(TARGET, {"data": Binary(b"x", 0), "large": 2**40})
    restored = MongoFindQuery.from_json(query.to_json())
    assert type(restored.filter["data"]) is bytes
    assert type(restored.filter["large"]) is Int64
    assert restored.fingerprint() == query.fingerprint()


@pytest.mark.parametrize("method", ["validate", "to_json", "fingerprint"])
def test_mutated_invalid_state_is_rejected(method):
    query = MongoFindQuery(TARGET, {})
    query.limit = -1
    with pytest.raises(ValueError, match="limit"):
        getattr(query, method)()


def test_validate_does_not_copy_or_change_state():
    query = MongoFindQuery(TARGET, {"x": [1]})
    document = query.filter
    query.validate()
    assert query.filter is document


def test_fingerprint_is_recomputed_and_order_sensitive():
    query = MongoFindQuery(TARGET, {"a": 1, "b": 2})
    before = query.fingerprint()
    assert len(before) == 64
    assert before != MongoFindQuery(TARGET, {"b": 2, "a": 1}).fingerprint()
    assert before != MongoFindQuery(TARGET, {"a": Int64(1), "b": 2}).fingerprint()
    query.filter["a"] = 3
    assert query.fingerprint() != before
    assert query.fingerprint() == MongoFindQuery.from_json(query.to_json()).fingerprint()


@pytest.mark.parametrize(
    "field,value",
    [
        ("target", MongoCollectionRef("other", "businesses")),
        ("projection", {"a": 1}),
        ("sort", (("a", 1),)),
        ("skip", 1),
        ("limit", 5),
    ],
)
def test_fingerprint_includes_options(field, value):
    query = MongoFindQuery(TARGET, {})
    before = query.fingerprint()
    setattr(query, field, value)
    assert query.fingerprint() != before


@pytest.mark.parametrize(
    "mutation",
    [
        lambda d: d.update(extra=True),
        lambda d: d.pop("limit"),
        lambda d: d.update(format_version=2),
        lambda d: d.update(format_version=True),
        lambda d: d.update(query_kind="mongodb.aggregate"),
        lambda d: d["target"].update(host="localhost"),
        lambda d: d.update(sort="a"),
        lambda d: d.update(skip=True),
    ],
)
def test_rejects_invalid_envelopes(mutation):
    data = json.loads(MongoFindQuery(TARGET, {}).to_json())
    mutation(data)
    with pytest.raises((ValueError, TypeError)):
        MongoFindQuery.from_json(json.dumps(data))


def test_whitespace_and_envelope_order_do_not_affect_fingerprint():
    query = MongoFindQuery(TARGET, {"x": 1})
    data = dict(reversed(list(json.loads(query.to_json()).items())))
    assert MongoFindQuery.from_json(json.dumps(data, indent=4)).fingerprint() == query.fingerprint()


@pytest.mark.parametrize("text", ["{", "[]", "{}", '{"a":1,"a":2}'])
def test_rejects_malformed_or_duplicate_json(text):
    with pytest.raises(ValueError):
        MongoFindQuery.from_json(text)


@pytest.mark.parametrize(
    "document",
    [
        {"x": {"$regex": "a", "$options": "i"}},
        {"x": {"$date": "2026-01-01T00:00:00Z"}},
        {"x": {"$numberLong": "1"}},
    ],
)
def test_rejects_ambiguous_literal_documents(document):
    # Canonical-looking literal wrappers can have identical text after decoding.
    # They must not silently change a document into a BSON scalar either.
    with pytest.raises(ValueError):
        MongoFindQuery(TARGET, document).to_json()


def test_rejects_unknown_python_values():
    with pytest.raises(TypeError):
        MongoFindQuery(TARGET, {"value": object()}).to_json()


def test_only_native_payload_uses_extended_json(tmp_path):
    from bondi.mongodb import MongoAggregateQuery
    from bondi.workload import Workload, WorkloadEntry

    query = MongoFindQuery(TARGET, {"x": Int64(1)}, {"x": 1, "_id": 0}, (("x", -1),), 2, 10)
    aggregate = MongoAggregateQuery(TARGET, [{"$match": {"x": Int64(1)}}, {"$limit": 10}])
    path = tmp_path / "workload.jsonl"
    Workload([WorkloadEntry(query, 0), WorkloadEntry(aggregate, 1)]).save(path)
    records = [json.loads(line) for line in path.read_text().splitlines()]
    for record in records:
        assert type(record["format_version"]) is int
        assert type(record["query"]["format_version"]) is int
    encoded = records[0]["query"]
    assert encoded["filter"] == {"x": {"$numberLong": "1"}}
    assert encoded["projection"] == {"x": 1, "_id": 0}
    assert encoded["sort"] == [["x", -1]]
    assert encoded["skip"] == 2
    assert encoded["limit"] == 10
    assert records[1]["query"]["pipeline"][1] == {"$limit": {"$numberInt": "10"}}
    restored = Workload.load(path)
    assert restored[0].query == query
    assert restored[1].query == aggregate
    assert restored[0].query.fingerprint() == query.fingerprint()


def test_projection_is_plain_json_and_not_bson_decoded():
    projection = {"literal": {"$literal": {"$numberLong": "1"}}}
    query = MongoFindQuery(TARGET, {}, projection)
    assert MongoFindQuery.from_json(query.to_json()).projection == projection
    with pytest.raises(TypeError):
        MongoFindQuery(TARGET, {}, {"literal": {"$literal": ObjectId()}}).to_json()


def test_extended_json_metadata_is_rejected():
    data = json.loads(MongoFindQuery(TARGET, {}).to_json())
    data["format_version"] = {"$numberInt": "1"}
    with pytest.raises(ValueError, match="format_version"):
        MongoFindQuery.from_json(json.dumps(data))
