"""Contract tests for logical MongoDB collection references."""

from dataclasses import FrozenInstanceError

import pytest

from dbrtoolkit.mongodb import MongoCollectionRef


@pytest.mark.parametrize("field", ["database", "collection"])
@pytest.mark.parametrize("value", [None, 42, b"name"])
def test_rejects_non_string_names(field, value):
    names = {"database": "research", "collection": "businesses", field: value}
    with pytest.raises(TypeError, match=field):
        MongoCollectionRef(**names)


@pytest.mark.parametrize("field", ["database", "collection"])
@pytest.mark.parametrize("value", ["", "bad\0name"])
def test_rejects_empty_names_and_null_characters(field, value):
    names = {"database": "research", "collection": "businesses", field: value}
    with pytest.raises(ValueError, match=field):
        MongoCollectionRef(**names)


def test_preserves_names_without_normalization():
    target = MongoCollectionRef(" Research ", "Business.Archive ")
    assert target.database == " Research "
    assert target.collection == "Business.Archive "
    assert MongoCollectionRef(" ", " ").database == " "


def test_value_identity_uses_both_names():
    target = MongoCollectionRef("research", "businesses")
    duplicate = MongoCollectionRef("research", "businesses")
    assert target == duplicate
    assert {target: "sample"}[duplicate] == "sample"
    assert target != MongoCollectionRef("other", "businesses")
    assert target != MongoCollectionRef("research", "other")


@pytest.mark.parametrize("field", ["database", "collection"])
def test_names_cannot_be_reassigned(field):
    target = MongoCollectionRef("research", "businesses")
    with pytest.raises(FrozenInstanceError):
        setattr(target, field, "other")
