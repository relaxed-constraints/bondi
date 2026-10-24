"""Public schema inspection, incremental counts and retention semantics."""

from copy import deepcopy
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

import pytest
from bson import Binary, Int64, ObjectId

from dbrtoolkit.schema import ARRAY_ELEMENT, Schema

DOCUMENTS = [
    {"city": "Sydney", "rating": 4, "items": [{"price": 10}, {"price": 20}]},
    {"city": "Sydney", "rating": None, "items": [{"price": 10}, {}]},
    {"city": "Melbourne"},
]


@pytest.mark.parametrize("mode", ["none", "distinct", "full"])
def test_public_inspection_and_missingness(mode):
    before = deepcopy(DOCUMENTS)
    s = Schema.from_documents(iter(DOCUMENTS), values=mode)
    assert s.document_count == 3
    assert list(s.fields) == ["city", "rating", "items"]
    assert s["city"].count == s["city"].parent_count == 3
    assert s["rating"].missing_count == 1 and s["rating"].has_missing
    assert s["rating"].is_multi_type
    assert list(s["rating"].types) == ["int", "null"]
    assert s["items.[]"].count == 4
    assert s["items.[]"].parent_count is s["items.[]"].missing_count is None
    assert s["items.[]"].has_missing is None
    price = s["items.[].price"]
    assert (price.count, price.parent_count, price.missing_count) == (3, 4, 1)
    assert s["items"].types["array"].elements.types["object"].fields["price"] is price
    assert s["city"].types["str"].values == (
        None if mode == "none" else frozenset({"Sydney", "Melbourne"})
    )
    counts = s["city"].types["str"].value_counts
    assert counts == ({"Sydney": 2, "Melbourne": 1} if mode == "full" else None)
    assert s["items"].types["array"].values is None
    assert s["items.[]"].types["object"].value_counts is None
    assert DOCUMENTS == before


def test_missing_is_relative_to_parent_objects():
    s = Schema.from_documents(
        [
            {"a": {"x": 1}, "items": [{"x": 1}, {}, {"x": None}]},
            {"a": 42, "items": []},
            {},
            {"a": {}},
        ]
    )
    assert (s["a.x"].count, s["a.x"].parent_count, s["a.x"].missing_count) == (1, 2, 1)
    assert (s["items.[].x"].count, s["items.[].x"].parent_count) == (2, 3)
    assert s["items.[].x"].types["null"].count == 1
    assert s["items"].missing_count == 2
    assert s["items.[]"].count == 3


@pytest.mark.parametrize("mode", ["none", "distinct", "full"])
def test_incremental_matches_batch_and_views_remain_live(mode):
    s = Schema(values=mode)
    s.update(DOCUMENTS[:1])
    city = s["city"]
    fields = s.fields
    counts = city.types["str"].value_counts
    values = city.types["str"].values
    s.update(DOCUMENTS[1:])
    s.update([{"new": 1}])
    assert city.count == 3 and city.parent_count == 4 and city.missing_count == 1
    assert "new" in fields
    batch = Schema.from_documents([*DOCUMENTS, {"new": 1}], values=mode)
    assert list(s.flat_fields) == list(batch.flat_fields)
    for path, f in s.flat_fields.items():
        other = batch[path]
        assert (f.count, f.parent_count, f.missing_count) == (
            other.count,
            other.parent_count,
            other.missing_count,
        )
        for name, t in f.types.items():
            assert (t.count, t.values, t.value_counts) == (
                other.types[name].count,
                other.types[name].values,
                other.types[name].value_counts,
            )
    if mode == "full":
        assert counts == {"Sydney": 2, "Melbourne": 1}
    if mode != "none":
        assert values == frozenset({"Sydney"})  # Immutable snapshot.
    with pytest.raises(AttributeError):
        s.value_mode = "full"


def test_typed_values_and_primitive_fields_include_mixed_containers():
    s = Schema.from_documents(
        [{"a": True}, {"a": 1}, {"a": 1.0}, {"a": {"x": 2}}, {"a": [3]}], values="full"
    )
    assert set(s.primitive_fields) == {"a", "a.x", "a.[]"}
    assert s["a"].types["bool"].value_counts == {True: 1}
    assert s["a"].types["int"].value_counts == {1: 1}
    assert s["a"].types["float"].value_counts == {1.0: 1}
    assert len(s["a"].types) == 5


def test_paths_do_not_collide_and_display_roundtrips():
    s = Schema.from_documents(
        [{"a.b": 1, "a": {"b": 2}, "[]": 3, "": 4, "slash\\": {"x.y": 5}, "arr": [[1]]}]
    )
    assert s[("a.b",)] is not s["a.b"]
    assert s[("[]",)].types["int"].count == 1
    assert s[("",)].count == 1
    assert s[("arr", ARRAY_ELEMENT, ARRAY_ELEMENT)] is s["arr.[].[]"]
    for display, f in s.flat_fields.items():
        assert s[display] is f
        assert s[f.path] is f
    with pytest.raises(KeyError):
        s["missing"]
    with pytest.raises(ValueError):
        s["broken\\"]


def test_empty_objects_and_arrays():
    s = Schema.from_documents([{}, {"a": [], "b": {}}])
    assert s.document_count == 2
    assert s["a"].missing_count == 1
    assert s["a.[]"].count == 0 and not s["a.[]"].types
    assert not s["b"].types["object"].fields
    assert not s.primitive_fields
    assert Schema.from_documents([]).document_count == 0


def test_read_only_views_and_no_source_container_retention():
    doc = {"a": [1, 1]}
    s = Schema.from_documents([doc], values="full")
    doc["a"].append(2)
    assert s["a.[]"].count == 2
    for mapping in (s.fields, s.flat_fields, s["a"].types, s["a.[]"].types["int"].value_counts):
        with pytest.raises(TypeError):
            mapping["new"] = 1


@pytest.mark.parametrize("value", [float("nan"), float("inf"), Decimal("NaN"), (1,), {1}, object()])
def test_invalid_document_is_atomic(value):
    s = Schema(values="full")
    with pytest.raises((TypeError, ValueError)):
        s.update([{"ok": 1}, {"before": 1, "bad": value}])
    assert s.document_count == 1
    assert list(s.fields) == ["ok"]
    assert s["ok"].parent_count == 1


def test_cycles_and_invalid_keys_but_shared_subobjects_are_allowed():
    cycle = {}
    cycle["self"] = cycle
    s = Schema()
    for doc in (cycle, {1: "value"}, [1]):
        with pytest.raises((TypeError, ValueError)):
            s.update([doc])
        assert s.document_count == 0
    shared = {"x": 1}
    s.update([{"a": shared, "b": shared}])
    assert s["a.x"].count == s["b.x"].count == 1


@pytest.mark.parametrize(
    "value",
    [
        ObjectId(),
        Int64(5),
        Binary(b"x", 4),
        b"x",
        datetime(2020, 1, 1, tzinfo=UTC),
        Decimal("1.5"),
        UUID(int=1),
    ],
)
def test_native_scalar_retention(value):
    s = Schema.from_documents([{"x": value}, {"x": value}], values="full")
    variant = s["x"].types[type(value).__name__]
    assert variant.count == 2 and variant.value_counts[value] == 2


def test_invalid_mode_and_iterator_failure():
    with pytest.raises(ValueError):
        Schema(values="sample")

    def source():
        yield {"x": 1}
        raise RuntimeError("source failed")

    s = Schema()
    with pytest.raises(RuntimeError):
        s.update(source())
    assert s.document_count == 1


def test_excessive_nesting_is_rejected_before_accumulation():
    doc = {}
    for _ in range(140):
        doc = {"nested": doc}
    s = Schema()
    with pytest.raises(ValueError, match="128"):
        s.update([doc])
    assert s.document_count == 0 and not s.fields
