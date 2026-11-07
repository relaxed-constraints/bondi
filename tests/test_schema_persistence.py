"""Schema snapshots preserve observations and remain incrementally usable."""

import json
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from uuid import UUID

import pytest
from bson import Binary, Int64, ObjectId

from bondi.schema import Schema


def observations(schema):
    return {
        path: (
            f.count,
            f.parent_count,
            f.missing_count,
            f.has_missing,
            [
                (
                    name,
                    t.count,
                    t.values,
                    list(t.value_counts.items()) if t.value_counts is not None else None,
                    list(t.fields),
                )
                for name, t in f.types.items()
            ],
        )
        for path, f in schema.flat_fields.items()
    }


@pytest.mark.parametrize("mode", ["none", "distinct", "full"])
def test_roundtrip_and_update(tmp_path, mode):
    docs = [
        {"a": {}, "b": 1, "[]": None, "a.b": True, "": [], "\\": {}},
        {"a": {"x": 2}, "b": [[], [{"$date": 3}, {}], None]},
        {"a": [1, False, 1.0], "b": "x"},
        {},
    ]
    original = Schema.from_documents(docs, values=mode)
    path = tmp_path / "schema.json"
    original.save(str(path))
    restored = Schema.load(path)
    assert restored.document_count == original.document_count
    assert restored.value_mode == mode
    assert list(restored.fields) == list(original.fields)
    assert observations(restored) == observations(original)
    assert set(restored.primitive_fields) == set(original.primitive_fields)
    assert restored["a.x"] is restored["a"].types["object"].fields["x"]
    more = [{"a": {"x": None, "new": 3}, "b": [4, {"y": 1}]}]
    original.update(more)
    restored.update(more)
    assert observations(restored) == observations(original)
    assert restored.document_count == original.document_count


@pytest.mark.parametrize("mode", ["none", "distinct", "full"])
@pytest.mark.parametrize("docs", [[], [{}, {}], [{"x": [], "y": {}}]])
def test_empty(tmp_path, mode, docs):
    s = Schema.from_documents(docs, values=mode)
    s.save(tmp_path / "s")
    r = Schema.load(tmp_path / "s")
    assert r.document_count == len(docs)
    assert observations(r) == observations(s)


SCALARS = [
    None,
    True,
    1,
    2**100,
    Int64(4),
    1.2,
    -0.0,
    "héllo",
    b"abc",
    Binary(b"abc", 0),
    Binary(b"abc", 128),
    Binary(bytes(16), 4),
    ObjectId(),
    UUID(int=1),
    date(1, 1, 1),
    date(2024, 2, 29),
    Decimal("1.50"),
    Decimal("-0.00"),
    Decimal("1.23456789012345678901234567890123456789"),
    Decimal("1e10000"),
    datetime(2020, 1, 1, 0, 0, 0, 123456),
    datetime(2020, 1, 1, 0, 0, 0, 123456, tzinfo=timezone(timedelta(hours=11)), fold=1),
]


@pytest.mark.parametrize("mode", ["distinct", "full"])
@pytest.mark.parametrize("value", SCALARS)
def test_scalar_fidelity(tmp_path, mode, value):
    s = Schema.from_documents([{"x": value}, {"x": value}], values=mode)
    s.save(tmp_path / "s")
    r = Schema.load(tmp_path / "s")
    name = "null" if value is None else type(value).__name__
    actual = next(iter(r["x"].types[name].values))
    assert type(actual) is type(value)
    assert actual == value
    if type(value) is Decimal:
        assert actual.as_tuple() == value.as_tuple()
    if type(value) is datetime:
        assert actual.isoformat() == value.isoformat() and actual.fold == value.fold
    if type(value) is float:
        assert actual.hex() == value.hex()
    if type(value) is Binary:
        assert actual.subtype == value.subtype
    r.update([{"x": value}])
    assert r["x"].types[name].count == 3
    if mode == "full":
        assert r["x"].types[name].value_counts[value] == 3


def test_extended_json_and_decimal_fallback(tmp_path):
    s = Schema.from_documents(
        [{"day": date(2020, 1, 1), "d": Decimal("1.50"), "big": Decimal("1e10000")}], values="full"
    )
    s.save(tmp_path / "s")
    fields = json.loads((tmp_path / "s").read_text())["fields"]
    values = [f["types"][0]["values"][0]["value"] for f in fields]
    assert values == [
        {"$date": {"$numberLong": "1577836800000"}},
        {"$numberDecimal": "1.50"},
        "1E+10000",
    ]


@pytest.mark.parametrize(
    "mutate",
    [
        lambda r: r.update(format_version=2),
        lambda r: r.update(format_version=True),
        lambda r: r.update(document_count=-1),
        lambda r: r.update(value_mode=[]),
        lambda r: r.update(extra=1),
        lambda r: r["fields"].append(r["fields"][0]),
        lambda r: r["fields"][0].update(count=2),
        lambda r: r["fields"][0]["types"].append(r["fields"][0]["types"][0]),
        lambda r: r["fields"][0]["types"][0].update(name="unsupported"),
        lambda r: r["fields"][0]["types"][0]["values"][0].update(count=0),
        lambda r: r["fields"][0]["types"][0]["values"][0].update(value=True),
        lambda r: r["fields"][0]["types"][0]["values"].append(
            r["fields"][0]["types"][0]["values"][0]
        ),
    ],
)
def test_invalid_records(tmp_path, mutate):
    path = tmp_path / "s"
    Schema.from_documents([{"x": 1}], values="full").save(path)
    record = json.loads(path.read_text())
    mutate(record)
    path.write_text(json.dumps(record))
    with pytest.raises(ValueError, match="Invalid schema snapshot"):
        Schema.load(path)


@pytest.mark.parametrize("data", [b"", b"{", b"\xff", b'{"x":1,"x":2}', b"NaN"])
def test_invalid_json(tmp_path, data):
    path = tmp_path / "s"
    path.write_bytes(data)
    with pytest.raises(ValueError):
        Schema.load(path)


def test_failed_save_preserves_destination(tmp_path, monkeypatch):
    from bondi import _schema_persistence

    path = tmp_path / "s"
    path.write_text("old")
    s = Schema.from_documents([{"x": 1}])

    def fail(*args):
        raise OSError("replacement failed")

    monkeypatch.setattr(_schema_persistence.os, "replace", fail)
    with pytest.raises(OSError):
        s.save(path)
    assert path.read_text() == "old"
    assert list(tmp_path.iterdir()) == [path]
    s["x"].count = 100
    with pytest.raises(ValueError):
        s.save(path)
    assert path.read_text() == "old"


def test_filesystem_errors(tmp_path):
    with pytest.raises(OSError):
        Schema.load(tmp_path / "missing")
    with pytest.raises(OSError):
        Schema().save(tmp_path / "missing" / "s")


@pytest.mark.parametrize("leaf", [1, {}, []])
def test_maximum_document_depth(tmp_path, leaf):
    document = leaf
    for _ in range(128):
        document = {"x": document}
    s = Schema.from_documents([document])
    s.save(tmp_path / "s")
    assert observations(Schema.load(tmp_path / "s")) == observations(s)


def test_global_order_is_rebuilt(tmp_path):
    s = Schema.from_documents([{"a": {}, "b": 1}, {"a": {"x": 2}}])
    assert list(s.flat_fields) == ["a", "b", "a.x"]
    s.save(tmp_path / "s")
    restored = Schema.load(tmp_path / "s")
    assert list(restored.flat_fields) == ["a", "a.x", "b"]
    assert observations(s) == observations(restored)


def test_datetime_uses_fixed_offset(tmp_path):
    from zoneinfo import ZoneInfo

    value = datetime(2026, 11, 8, 12, tzinfo=ZoneInfo("Australia/Melbourne"))
    s = Schema.from_documents([{"x": value}], values="full")
    s.save(tmp_path / "s")
    actual = next(iter(Schema.load(tmp_path / "s")["x"].types["datetime"].values))
    assert actual.isoformat() == value.isoformat()
    assert type(actual.tzinfo) is timezone


def test_reject_nonmidnight_date(tmp_path):
    path = tmp_path / "s"
    Schema.from_documents([{"x": date(2020, 1, 1)}], values="full").save(path)
    record = json.loads(path.read_text())
    record["fields"][0]["types"][0]["values"][0]["value"]["$date"]["$numberLong"] = "1"
    path.write_text(json.dumps(record))
    with pytest.raises(ValueError, match="midnight"):
        Schema.load(path)


def test_partial_write_failure_preserves_destination(tmp_path, monkeypatch):
    from bondi import _schema_persistence

    path = tmp_path / "s"
    path.write_text("previous snapshot")

    def fail(record, stream, **kwargs):
        stream.write('{"partial":')
        raise OSError("disk full")

    monkeypatch.setattr(_schema_persistence.json, "dump", fail)
    with pytest.raises(OSError, match="disk full"):
        Schema().save(path)
    assert path.read_text() == "previous snapshot"
    assert list(tmp_path.iterdir()) == [path]


@pytest.mark.parametrize("name", ["date", "Decimal", "Binary", "UUID", "ObjectId", "float"])
@pytest.mark.parametrize("payload", [{"$date": {}}, {"$binary": {}}, [], {"unknown": 1}])
def test_malformed_scalar_payloads(tmp_path, name, payload):
    path = tmp_path / "s"
    Schema.from_documents([{"x": 1}], values="full").save(path)
    record = json.loads(path.read_text())
    variant = record["fields"][0]["types"][0]
    variant["name"] = name
    variant["values"][0]["value"] = payload
    path.write_text(json.dumps(record))
    with pytest.raises(ValueError):
        Schema.load(path)
