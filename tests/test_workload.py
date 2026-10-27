"""Reference ownership, metadata and single-backend validation contracts."""

from copy import deepcopy
from dataclasses import fields
from typing import ClassVar

import pytest

from bondi.couchbase import CouchbaseQuery
from bondi.mongodb import MongoAggregateQuery, MongoCollectionRef, MongoFindQuery
from bondi.workload import Workload, WorkloadEntry


def find():
    return MongoFindQuery(MongoCollectionRef("research", "businesses"), {})


def test_empty_workloads_are_independent():
    first, second = Workload(), Workload()
    first.entries.append(WorkloadEntry(find()))
    assert len(second) == 0
    second.validate()


def test_list_ownership_order_duplicates_and_shared_queries():
    query = find()
    entry = WorkloadEntry(query, 0)
    entries = [entry, WorkloadEntry(query, 1), entry]
    workload = Workload(entries)
    assert workload.entries is not entries
    assert list(workload) == entries
    assert workload[0] is workload[-1] is entry
    assert workload[1].query is query
    entries.clear()
    assert len(workload) == 3
    query.limit = 10
    assert all(e.query.limit == 10 for e in workload)
    entry.pattern_id = 7
    assert workload[0].pattern_id == 7
    assert workload[:1][0] is entry


def test_explicit_deepcopy_is_independent():
    original = Workload([WorkloadEntry(find())])
    copied = deepcopy(original)
    copied[0].query.filter["x"] = 1
    assert original[0].query.filter == {}


def test_mongodb_query_forms_and_named_databases_can_mix():
    Workload(
        [
            WorkloadEntry(find()),
            WorkloadEntry(
                MongoAggregateQuery(MongoCollectionRef("other_database", "other_collection"), [])
            ),
        ]
    ).validate()


def test_rejects_backend_mismatch_with_index():
    with pytest.raises(ValueError, match="entry 1.*couchbase.*mongodb"):
        Workload([WorkloadEntry(find()), WorkloadEntry(CouchbaseQuery("SELECT 1"))])


def test_revalidates_after_reference_mutation():
    entry = WorkloadEntry(find())
    workload = Workload([entry, WorkloadEntry(find())])
    entry.query = CouchbaseQuery("SELECT 1")
    with pytest.raises(ValueError, match="entry 1"):
        workload.validate()
    entry.query = find()
    entry.query.limit = -1
    with pytest.raises(ValueError, match="limit"):
        workload.validate()


@pytest.mark.parametrize(
    "value,error", [(-1, ValueError), (True, TypeError), (1.0, TypeError), ("0", TypeError)]
)
def test_pattern_id_constraints(value, error):
    with pytest.raises(error):
        WorkloadEntry(find(), value)


def test_pattern_ids_are_not_list_offsets():
    Workload([WorkloadEntry(find(), 1000), WorkloadEntry(find(), 1000)]).validate()


@pytest.mark.parametrize("entries", [None, (), [find()]])
def test_invalid_entry_container(entries):
    with pytest.raises(TypeError):
        Workload(entries)


def test_validation_does_not_replace_references():
    query = find()
    workload = Workload([WorkloadEntry(query)])
    entries = workload.entries
    workload.validate()
    assert workload.entries is entries
    assert workload[0].query is query


def test_custom_structural_query_needs_no_inheritance():
    class CustomQuery:
        backend: ClassVar[str] = "custom"

        def validate(self) -> None:
            pass

        def to_json(self) -> str:
            raise AssertionError("Workload validation must not serialize")

        def fingerprint(self) -> str:
            raise AssertionError("Workload validation must not fingerprint")

    Workload([WorkloadEntry(CustomQuery())]).validate()


def test_invalid_query_contract():
    with pytest.raises(TypeError, match="backend"):
        WorkloadEntry(object())

    class Incomplete:
        backend = "custom"

    with pytest.raises(TypeError, match="validate"):
        WorkloadEntry(Incomplete())


def test_backend_is_not_a_dataclass_field():
    for query in [find(), MongoAggregateQuery(find().target, []), CouchbaseQuery("SELECT 1")]:
        assert "backend" not in {f.name for f in fields(query)}
        assert type(query).from_json(query.to_json()).backend == query.backend
