"""BSON fidelity, strict loading and representation identity."""

import json
from datetime import UTC, datetime, timedelta, timezone

import pytest
from bson import Binary, Decimal128, Int64, ObjectId, Regex, Timestamp, json_util
from bson.errors import BSONError

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
        lambda d: d.update(format_version=99),
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
    assert encoded["projection"] == {"x": {"$numberInt": "1"}, "_id": {"$numberInt": "0"}}
    assert encoded["sort"] == [["x", -1]]
    assert encoded["skip"] == 2
    assert encoded["limit"] == 10
    assert records[1]["query"]["pipeline"][1] == {"$limit": {"$numberInt": "10"}}
    restored = Workload.load(path)
    assert restored[0].query == query
    assert restored[1].query == aggregate
    assert restored[0].query.fingerprint() == query.fingerprint()


def test_legacy_projection_remains_plain_json():
    projection = {"literal": {"$literal": {"$numberLong": "1"}}}
    envelope = json.loads(MongoFindQuery(TARGET, {}).to_json())
    envelope.update(format_version=1, projection=projection)
    restored = MongoFindQuery.from_json(json.dumps(envelope))
    assert restored.projection == projection
    with pytest.raises(ValueError, match="ambiguous"):
        restored.to_json()


def test_extended_json_metadata_is_rejected():
    data = json.loads(MongoFindQuery(TARGET, {}).to_json())
    data["format_version"] = {"$numberInt": "1"}
    with pytest.raises(ValueError, match="format_version"):
        MongoFindQuery.from_json(json.dumps(data))


@pytest.mark.parametrize(
    "value",
    [
        ObjectId("0123456789abcdef01234567"),
        datetime(2026, 1, 1),
        Regex("a", "i"),
        Int64(3),
        Binary(b"x", 128),
        Decimal128("1.25"),
    ],
)
def test_projection_bson_roundtrip(value):
    query = MongoFindQuery(TARGET, {}, {"x": {"$literal": value}})
    restored = MongoFindQuery.from_json(query.to_json())
    assert restored.projection == query.projection
    assert restored.fingerprint() == query.fingerprint()


@pytest.mark.parametrize(
    "operator",
    [
        {"$regex": "^python$", "$options": "i"},
        {"$options": "i", "$regex": "^python$"},
        {"$regex": Regex("^python$", "i")},
    ],
)
def test_regex_operators_across_query_payloads(operator, tmp_path):
    from bondi.mongodb import MongoAggregateQuery
    from bondi.workload import Workload, WorkloadEntry

    predicate = {"tags": {"$elemMatch": operator}}
    find = MongoFindQuery(TARGET, predicate, {"tags": {"$elemMatch": operator}})
    aggregate = MongoAggregateQuery(TARGET, [{"$match": predicate}])
    path = tmp_path / "queries.jsonl"
    Workload([WorkloadEntry(find), WorkloadEntry(aggregate)]).save(path)
    restored = Workload.load(path)
    assert restored[0].query == find
    assert restored[1].query == aggregate
    assert isinstance(restored[0].query.filter["tags"]["$elemMatch"], dict)
    assert list(restored[0].query.filter["tags"]["$elemMatch"]) == list(operator)
    assert restored[0].query.fingerprint() == find.fingerprint()


def test_regex_operator_and_native_value_are_distinct():
    operator = MongoFindQuery(TARGET, {"x": {"$regex": "a", "$options": "i"}})
    native = MongoFindQuery(TARGET, {"x": Regex("a", "i")})
    assert operator.fingerprint() != native.fingerprint()
    assert "$regularExpression" in native.to_json()
    assert isinstance(MongoFindQuery.from_json(native.to_json()).filter["x"], Regex)


def test_ordinary_version1_find_loads_and_migrates():
    envelope = json.loads(MongoFindQuery(TARGET, {"x": 1}).to_json())
    envelope.update(format_version=1, projection={"x": 1})
    restored = MongoFindQuery.from_json(json.dumps(envelope))
    assert restored.projection == {"x": 1}
    assert json.loads(restored.to_json())["format_version"] == 2


@pytest.mark.parametrize(
    "wrapper",
    [
        {"$regularExpression": {"pattern": "a", "options": "i"}},
        {"$oid": "0123456789abcdef01234567"},
    ],
)
def test_literal_wrappers_in_projection_remain_rejected(wrapper):
    with pytest.raises(ValueError, match="ambiguous"):
        MongoFindQuery(TARGET, {}, {"x": {"$literal": wrapper}}).to_json()


def test_duplicate_projection_keys_rejected():
    text = (
        MongoFindQuery(TARGET, {})
        .to_json()
        .replace('"projection":null', '"projection":{"x":1,"x":0}')
    )
    with pytest.raises(ValueError, match="Duplicate"):
        MongoFindQuery.from_json(text)


@pytest.mark.parametrize(
    "wrapper",
    [
        {"$oid": "invalid"},
        {"$regularExpression": {"pattern": "a"}},
        {"$date": "invalid"},
    ],
)
def test_malformed_projection_wrappers_rejected(wrapper):
    envelope = json.loads(MongoFindQuery(TARGET, {}).to_json())
    envelope["projection"] = {"x": {"$literal": wrapper}}
    with pytest.raises((ValueError, TypeError, KeyError, BSONError)):
        MongoFindQuery.from_json(json.dumps(envelope))
