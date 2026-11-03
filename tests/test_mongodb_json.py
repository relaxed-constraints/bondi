"""Public query input decoding contract and persistence interoperability."""

from datetime import datetime

import pytest
from bson import Binary, Decimal128, Int64, ObjectId, Regex, json_util

from bondi.mongodb import MongoCollectionRef, MongoFindQuery, loads_query_json


@pytest.mark.parametrize(
    "text,expected",
    [
        ("null", None),
        ("true", True),
        ("42", 42),
        ("1.5", 1.5),
        ('"hello"', "hello"),
        ('[1, {"x": 2}]', [1, {"x": 2}]),
        (
            '{"tags":{"$elemMatch":{"$regex":"^python$","$options":"i"}}}',
            {"tags": {"$elemMatch": {"$regex": "^python$", "$options": "i"}}},
        ),
    ],
)
def test_plain_json_and_regex_operator(text, expected):
    assert loads_query_json(text) == expected


@pytest.mark.parametrize(
    "value",
    [
        ObjectId("0123456789abcdef01234567"),
        datetime(2026, 1, 1),
        Regex("python", "i"),
        Int64(42),
        Binary(b"ab", 128),
        Decimal128("1.25"),
    ],
)
@pytest.mark.parametrize(
    "options", [json_util.CANONICAL_JSON_OPTIONS, json_util.RELAXED_JSON_OPTIONS]
)
def test_bson_decoding(value, options):
    decoded = loads_query_json(json_util.dumps({"x": value}, json_options=options))
    assert decoded["x"] == value
    # Relaxed JSON intentionally does not retain int32 versus int64 identity.
    if not isinstance(value, Int64):
        assert type(decoded["x"]) is type(value)


@pytest.mark.parametrize(
    "text",
    [
        "{",
        '{"a":1,"a":2}',
        '{"x":[{"a":1,"a":2}]}',
        "NaN",
        "Infinity",
        "-Infinity",
        "1e999",
        '{"x":NaN}',
        '{"$oid":"bad"}',
        '{"$date":"bad"}',
        '{"$regularExpression":{"pattern":"a"}}',
        '{"$numberLong":"bad"}',
        '{"$date":{"$numberLong":"9999999999999999999"}}',
    ],
)
def test_invalid_inputs_raise_value_error(text):
    with pytest.raises(ValueError):
        loads_query_json(text)


@pytest.mark.parametrize("value", [None, {}, b"{}", 42])
def test_non_string_raises_type_error(value):
    with pytest.raises(TypeError, match="string"):
        loads_query_json(value)


def test_nesting_error_normalized():
    with pytest.raises(ValueError):
        loads_query_json("[" * 2000 + "0" + "]" * 2000)


def test_order_and_nested_regex_bson_value():
    text = (
        '{"z":1,"a":{"$regex":{"$regularExpression":{"pattern":"x","options":"i"}},"$options":"i"}}'
    )
    decoded = loads_query_json(text)
    assert list(decoded) == ["z", "a"]
    assert list(decoded["a"]) == ["$regex", "$options"]
    assert isinstance(decoded["a"]["$regex"], Regex)


def test_query_persistence_uses_same_rules():
    payload = loads_query_json("""
    {"filter":{"tags":{"$elemMatch":{"$regex":"python","$options":"i"}}},
      "projection":{"x":{"$literal":{"$date":"2026-01-01T00:00:00Z"}},
                    "y":{"$literal":{"$oid":"0123456789abcdef01234567"}}}}""")
    query = MongoFindQuery(MongoCollectionRef("test", "posts"), **payload)
    restored = MongoFindQuery.from_json(query.to_json())
    assert restored == query
    assert isinstance(restored.filter["tags"]["$elemMatch"], dict)


def test_no_operator_validation_or_literal_escape():
    assert loads_query_json('{"$madeUp":1}') == {"$madeUp": 1}
    assert isinstance(
        loads_query_json('{"$literal":{"$oid":"0123456789abcdef01234567"}}')["$literal"], ObjectId
    )
