import json
from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

import pytest
from bson import Binary, Int64, ObjectId, json_util
from bson.binary import UuidRepresentation
from jsonschema import SchemaError, ValidationError

from bondi.schema import Schema, validate_json_schema


@pytest.fixture
def documents():
    return [
        {"a.b": [{"[]": 1}, None, ["x"]], "value": None},
        {"a.b": [{"[]": 2.5}], "value": {"name": "x"}},
        {"a.b": [], "extra": True, "value": "x"},
    ]


def test_structure(documents, tmp_path):
    observed = Schema.from_documents(documents)
    path = tmp_path / "snapshot.json"
    observed.save(path)
    rules = observed.to_json_schema()
    assert rules == Schema.load(path).to_json_schema()
    validate_json_schema(rules, documents)
    validate_json_schema(rules, {"a.b": [{"[]": 99.5}, ["other"]], "value": None, "new": 1})
    for invalid in [
        {"a.b": []},
        {"value": None},
        {"a.b": [{}], "value": None},
        {"a.b": [[1]], "value": None},
        {"a.b": [], "value": {}},
    ]:
        with pytest.raises(ValidationError):
            validate_json_schema(rules, invalid)


@pytest.fixture
def bson_document():
    return {
        "data": [
            ObjectId(),
            datetime(1990, 2, 1),
            b"bytes",
            Binary(b"x", 128),
            UUID(int=1),
            1,
            2**40,
            Int64(1),
            2.5,
            True,
            None,
        ]
    }


def test_canonical(bson_document):
    options = json_util.CANONICAL_JSON_OPTIONS.with_options(
        uuid_representation=UuidRepresentation.STANDARD
    )
    rules = Schema.from_documents([bson_document]).to_json_schema(
        representation="canonical_extended_json"
    )
    validate_json_schema(rules, json.loads(json_util.dumps(bson_document, json_options=options)))
    for item in [
        1,
        {"$date": "2020"},
        {"$oid": 1},
        {"$numberInt": "1", "x": 1},
        {"$binary": {"base64": ""}},
    ]:
        with pytest.raises(ValidationError):
            validate_json_schema(rules, {"data": [item]})
    with pytest.raises(ValueError, match=r"ObjectId.*data\.\[\]"):
        Schema.from_documents([bson_document]).to_json_schema()


@pytest.mark.parametrize("value", [Decimal("1.0"), date(2000, 1, 1)])
@pytest.mark.parametrize("representation", ["json", "canonical_extended_json"])
def test_unsupported(value, representation):
    with pytest.raises(ValueError, match="nested"):
        Schema.from_documents([{"nested": value}]).to_json_schema(representation=representation)


def test_empty_and_incremental():
    observed = Schema()
    validate_json_schema(observed.to_json_schema(), {"new": 1})
    observed.update([{"x": []}])
    first = observed.to_json_schema()
    observed.update([{"x": [None]}])
    validate_json_schema(first, {"x": [1]})
    with pytest.raises(ValidationError):
        validate_json_schema(observed.to_json_schema(), {"x": [1]})
    with pytest.raises(ValueError, match="representation"):
        observed.to_json_schema(representation="relaxed")


def test_validate_external_schema():
    rules = {"properties": {"x": {"$ref": "#/$defs/int"}}, "$defs": {"int": {"type": "integer"}}}
    assert validate_json_schema(rules, []) is None
    with pytest.raises(ValidationError) as exc:
        validate_json_schema(rules, [{"x": 1}, {"x": False}])
    assert list(exc.value.path) == ["x"]
    assert exc.value.__notes__ == ["Batch item index: 1"]
    with pytest.raises(SchemaError):
        validate_json_schema({"type": "int"}, [])
