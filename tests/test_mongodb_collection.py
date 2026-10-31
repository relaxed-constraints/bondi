"""Contract tests for logical MongoDB collection references."""

from dataclasses import FrozenInstanceError

import pytest

from bondi.mongodb import MongoCollectionRef


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


@pytest.mark.parametrize(
    ("namespace", "database", "collection"),
    [
        ("research.businesses", "research", "businesses"),
        ("research.businesses.archive", "research", "businesses.archive"),
        (" Research .Business.Archive ", " Research ", "Business.Archive "),
        (" . ", " ", " "),
    ],
)
def test_from_namespace_preserves_names(namespace, database, collection):
    assert MongoCollectionRef.from_namespace(namespace) == MongoCollectionRef(database, collection)


@pytest.mark.parametrize("namespace", [None, 42, b"research.businesses"])
def test_from_namespace_rejects_non_strings(namespace):
    with pytest.raises(TypeError, match="namespace must be a string"):
        MongoCollectionRef.from_namespace(namespace)


@pytest.mark.parametrize("namespace", ["", "research"])
def test_from_namespace_requires_separator(namespace):
    with pytest.raises(ValueError, match="namespace must contain a dot"):
        MongoCollectionRef.from_namespace(namespace)


@pytest.mark.parametrize(
    ("namespace", "field"),
    [
        (".businesses", "database"),
        ("research.", "collection"),
        (".", "database"),
        ("bad\0name.businesses", "database"),
        ("research.bad\0name", "collection"),
    ],
)
def test_from_namespace_validates_parsed_names(namespace, field):
    with pytest.raises(ValueError, match=field):
        MongoCollectionRef.from_namespace(namespace)
