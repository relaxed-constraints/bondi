"""Native round trips, strict line diagnostics and atomic replacement."""

import json
from unittest.mock import patch

import pytest
from bson import Int64, ObjectId

from dbrtoolkit.couchbase import CouchbaseQuery
from dbrtoolkit.mongodb import MongoAggregateQuery, MongoCollectionRef, MongoFindQuery
from dbrtoolkit.workload import Workload, WorkloadEntry

TARGET = MongoCollectionRef("yelp", "business")


def sample():
    return Workload([WorkloadEntry(MongoFindQuery(TARGET, {"x": 1}), 0)])


def test_mongo_round_trip_preserves_types_order_duplicates_and_ids(tmp_path):
    query = MongoFindQuery(TARGET, {"b": Int64(1), "a": ObjectId()}, sort=(("b", -1), ("a", 1)))
    entry = WorkloadEntry(query, 42)
    work = Workload([entry, WorkloadEntry(MongoAggregateQuery(TARGET, [{"$limit": 5}])), entry])
    path = tmp_path / "queries.jsonl"
    work.save(path)
    restored = Workload.load(path)
    assert [e.pattern_id for e in restored] == [42, None, 42]
    assert [e.query.fingerprint() for e in restored] == [e.query.fingerprint() for e in work]
    assert type(restored[0].query.filter["b"]) is Int64
    assert type(restored[0].query.filter["a"]) is ObjectId
    assert list(restored[0].query.filter) == ["b", "a"]
    assert restored[0] is not restored[2]
    assert restored[0].query is not restored[2].query
    restored[0].query.limit = 2
    assert restored[2].query.limit is None
    assert len(path.read_text().splitlines()) == 3
    assert isinstance(json.loads(path.read_text().splitlines()[0])["query"], dict)


def test_couchbase_literal_wrappers_stay_json(tmp_path):
    query = CouchbaseQuery(
        " SELECT $x -- café\n", {"x": {"$numberLong": "1"}}, query_context="default:research.data"
    )
    path = tmp_path / "cb.jsonl"
    Workload([WorkloadEntry(query)]).save(path)
    restored = Workload.load(path)[0].query
    assert restored == query
    assert restored.fingerprint() == query.fingerprint()
    assert isinstance(restored.named_parameters["x"], dict)


def test_empty_overwrites_and_final_newline_optional(tmp_path):
    path = tmp_path / "queries.jsonl"
    sample().save(path)
    path.write_bytes(path.read_bytes().rstrip(b"\n"))
    assert len(Workload.load(path)) == 1
    Workload().save(path)
    assert path.read_bytes() == b""
    assert len(Workload.load(path)) == 0


@pytest.mark.parametrize(
    "record",
    [
        {},
        {"extra": 1},
        {"format_version": True, "query": {}, "pattern_id": None},
        {"format_version": 2, "query": {}, "pattern_id": None},
        {"format_version": 1, "query": "text", "pattern_id": None},
        {"format_version": 1, "query": {"query_kind": "unknown"}, "pattern_id": None},
    ],
)
def test_bad_second_record_reports_line(tmp_path, record):
    path = tmp_path / "queries.jsonl"
    sample().save(path)
    path.write_text(path.read_text() + json.dumps(record) + "\n")
    with pytest.raises(ValueError, match="Line 2"):
        Workload.load(path)


@pytest.mark.parametrize("tail", [b"\n", b"{", b"\xff", b'{"a":1,"a":2}', b'{"a":NaN}'])
def test_bad_encoding_json_blank_and_duplicates(tmp_path, tail):
    path = tmp_path / "queries.jsonl"
    sample().save(path)
    path.write_bytes(path.read_bytes() + tail)
    with pytest.raises(ValueError, match="Line 2"):
        Workload.load(path)


@pytest.mark.parametrize("field,value", [("pattern_id", True), ("pattern_id", -1)])
def test_bad_metadata(tmp_path, field, value):
    path = tmp_path / "queries.jsonl"
    sample().save(path)
    record = json.loads(path.read_text())
    record[field] = value
    path.write_text(json.dumps(record))
    with pytest.raises(ValueError, match="Line 1"):
        Workload.load(path)


def test_mixed_backends_rejected_at_offending_line(tmp_path):
    mongo, cb = tmp_path / "m.jsonl", tmp_path / "c.jsonl"
    sample().save(mongo)
    Workload([WorkloadEntry(CouchbaseQuery("SELECT 1"))]).save(cb)
    mongo.write_bytes(mongo.read_bytes() + cb.read_bytes())
    with pytest.raises(ValueError, match="Line 2.*Backend"):
        Workload.load(mongo)


def test_invalid_native_payload_reports_line(tmp_path):
    path = tmp_path / "queries.jsonl"
    sample().save(path)
    record = json.loads(path.read_text())
    record["query"]["limit"] = -1
    path.write_text(json.dumps(record))
    with pytest.raises(ValueError, match="Line 1"):
        Workload.load(path)


def test_failed_serialization_preserves_destination_and_cleans_temp(tmp_path):
    path = tmp_path / "queries.jsonl"
    sample().save(path)
    previous = path.read_bytes()
    broken = sample()
    broken.entries.append(WorkloadEntry(MongoFindQuery(TARGET, {"bad": object()})))
    with pytest.raises(ValueError, match="entry 2"):
        broken.save(path)
    assert path.read_bytes() == previous
    assert list(tmp_path.iterdir()) == [path]


def test_failed_replace_preserves_destination_and_cleans_temp(tmp_path):
    path = tmp_path / "queries.jsonl"
    path.write_text("original")
    with patch("dbrtoolkit.workload.os.replace", side_effect=OSError("failed")):
        with pytest.raises(OSError):
            sample().save(path)
    assert path.read_text() == "original"
    assert list(tmp_path.iterdir()) == [path]


def test_save_revalidates_and_does_not_truncate(tmp_path):
    path = tmp_path / "queries.jsonl"
    path.write_text("original")
    work = sample()
    work[0].pattern_id = -1
    with pytest.raises(ValueError):
        work.save(path)
    assert path.read_text() == "original"
