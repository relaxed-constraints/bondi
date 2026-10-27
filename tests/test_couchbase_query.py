"""Native SQL++ representation and strict JSON contracts."""

import json
from datetime import datetime

import pytest
from bson import Int64

from bondi.couchbase import CouchbaseQuery


def test_round_trip_preserves_text_context_and_json_types():
    query = CouchbaseQuery(
        "  SELECT $x; -- café\n",
        {"x": [None, True, 1, 1.5, {"name": "é"}]},
        query_context=" default:`research`.`data` ",
    )
    restored = CouchbaseQuery.from_json(query.to_json())
    assert restored == query
    assert restored.statement == query.statement
    assert restored.query_context == query.query_context
    assert restored.fingerprint() == query.fingerprint()
    assert [type(v) for v in restored.named_parameters["x"]] == [type(None), bool, int, float, dict]


def test_positional_parameters_and_no_parameters():
    for query in (
        CouchbaseQuery("SELECT 1"),
        CouchbaseQuery("SELECT $1", positional_parameters=[2]),
    ):
        assert CouchbaseQuery.from_json(query.to_json()) == query


def test_parameters_are_copied_and_defaults_are_independent():
    named = {"x": [{"v": 1}]}
    query = CouchbaseQuery("SELECT $x", named)
    query.named_parameters["x"][0]["v"] = 2
    assert named["x"][0]["v"] == 1
    named["x"].append(3)
    assert len(query.named_parameters["x"]) == 1
    positional = [[1]]
    other = CouchbaseQuery("SELECT $1", positional_parameters=positional)
    other.positional_parameters[0].append(2)
    assert positional == [[1]]
    first, second = CouchbaseQuery("SELECT 1"), CouchbaseQuery("SELECT 1")
    first.named_parameters["x"] = 1
    assert second.named_parameters == {}
    with pytest.raises(TypeError):
        hash(query)


@pytest.mark.parametrize(
    "kwargs,error",
    [
        ({"statement": None}, TypeError),
        ({"statement": " \n"}, ValueError),
        ({"query_context": 1}, TypeError),
        ({"query_context": " "}, ValueError),
        ({"named_parameters": []}, TypeError),
        ({"positional_parameters": ()}, TypeError),
        ({"named_parameters": {"x": 1}, "positional_parameters": [2]}, ValueError),
    ],
)
def test_field_validation(kwargs, error):
    with pytest.raises(error):
        CouchbaseQuery(**({"statement": "SELECT 1"} | kwargs))


@pytest.mark.parametrize(
    "value,error",
    [
        ({1: "x"}, TypeError),
        ((1, 2), TypeError),
        (b"x", TypeError),
        (datetime(2026, 1, 1), TypeError),
        (Int64(1), TypeError),
        (float("nan"), ValueError),
        (float("inf"), ValueError),
        (float("-inf"), ValueError),
    ],
)
def test_nested_json_validation(value, error):
    with pytest.raises(error):
        CouchbaseQuery("SELECT $x", {"x": [value]})


def test_cycles_rejected_but_repeated_noncyclic_values_allowed():
    value = []
    value.append(value)
    with pytest.raises(ValueError, match="circular"):
        CouchbaseQuery("SELECT $x", {"x": value})
    shared = [1]
    query = CouchbaseQuery("SELECT $x", {"x": [shared, shared]})
    assert CouchbaseQuery.from_json(query.to_json()) == query


@pytest.mark.parametrize("method", ["validate", "to_json", "fingerprint"])
def test_invalid_mutation_is_rejected(method):
    query = CouchbaseQuery("SELECT 1")
    query.named_parameters["x"] = float("nan")
    with pytest.raises(ValueError):
        getattr(query, method)()


def test_validation_does_not_parse_sql_or_copy_parameters():
    query = CouchbaseQuery("invalid SQL++ candidate $unbound")
    original = query.named_parameters
    query.validate()
    assert original is query.named_parameters
    assert CouchbaseQuery.from_json(query.to_json()) == query


@pytest.mark.parametrize(
    "field,value",
    [
        ("statement", "SELECT 1 "),
        ("statement", "SELECT 1 -- comment"),
        ("named_parameters", {"x": 1}),
        ("positional_parameters", [1]),
        ("query_context", "default:research.data"),
    ],
)
def test_fingerprint_recomputed_for_all_fields(field, value):
    query = CouchbaseQuery("SELECT 1")
    before = query.fingerprint()
    setattr(query, field, value)
    assert before != query.fingerprint()
    assert query.fingerprint() == CouchbaseQuery.from_json(query.to_json()).fingerprint()


@pytest.mark.parametrize(
    "mutation",
    [
        lambda d: d.update(extra=1),
        lambda d: d.pop("statement"),
        lambda d: d.update(format_version=True),
        lambda d: d.update(format_version=2),
        lambda d: d.update(query_kind="mongodb.find"),
        lambda d: d.update(statement=""),
    ],
)
def test_invalid_envelope(mutation):
    raw = json.loads(CouchbaseQuery("SELECT 1").to_json())
    mutation(raw)
    with pytest.raises(ValueError):
        CouchbaseQuery.from_json(json.dumps(raw))


@pytest.mark.parametrize("token", ["NaN", "Infinity", "-Infinity", "1e999"])
def test_nonfinite_json_loading(token):
    text = CouchbaseQuery("SELECT $x", {"x": 1}).to_json().replace('"x":1', f'"x":{token}')
    with pytest.raises(ValueError):
        CouchbaseQuery.from_json(text)


def test_duplicate_nested_keys_rejected():
    text = CouchbaseQuery("SELECT $x", {"x": 1}).to_json().replace('"x":1', '"x":1,"x":2')
    with pytest.raises(ValueError, match="Duplicate"):
        CouchbaseQuery.from_json(text)


def test_envelope_formatting_does_not_change_fingerprint():
    query = CouchbaseQuery("SELECT $x", {"x": 1})
    data = dict(reversed(list(json.loads(query.to_json()).items())))
    assert query.fingerprint() == CouchbaseQuery.from_json(json.dumps(data, indent=2)).fingerprint()
