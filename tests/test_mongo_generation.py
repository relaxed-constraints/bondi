"""Public generation contracts, independent of any database."""

import json
import os
import random
import subprocess
import sys
from collections import Counter
from dataclasses import FrozenInstanceError
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from bson import Int64, ObjectId

from bondi.estimation import CardinalityEstimate
from bondi.mongodb import (
    MongoCollectionRef,
    MongoFindQuery,
    MongoGenerationConfig,
    MongoPredicateTemplate,
    MongoQueryPattern,
    MongoWorkloadGenerator,
    WorkloadGenerationError,
)
from bondi.schema import Schema
from bondi.workload import Workload

TARGET = MongoCollectionRef("test", "items")
DOCS = [{"x": i, "y": str(i % 10), "flag": bool(i % 2)} for i in range(100)]


def generator(documents=DOCS, values="distinct", estimator=None, **config):
    return MongoWorkloadGenerator(
        target=TARGET,
        schema=Schema.from_documents(documents, values=values),
        estimator=estimator,
        config=MongoGenerationConfig(**config),
    )


def fingerprints(workload):
    return [(e.query.fingerprint(), e.pattern_id) for e in workload]


def test_exact_counts_patterns_and_fixed_options():
    g = generator(
        sort_probability=1, projection_probability=1, skip_probability=1, limit_probability=0
    )
    w, patterns = g.generate(
        num_patterns=10, instances_per_pattern=50, seed=42, return_patterns=True
    )
    assert isinstance(w, Workload)
    assert len(w) == 500 and len(set(patterns)) == 10
    assert Counter(e.pattern_id for e in w) == dict.fromkeys(range(10), 50)
    assert [e.pattern_id for e in w] != sorted(e.pattern_id for e in w)
    for e in w:
        assert patterns[e.pattern_id].matches(e.query)
        assert e.query.sort and e.query.projection is not None and e.query.limit is not None
    assert g.last_stats["completed_patterns"] == 10
    stats = g.last_stats
    assert json.loads(json.dumps(stats)) == stats
    stats["completed_patterns"] = 9
    assert g.last_stats["completed_patterns"] == 10
    with pytest.raises(FrozenInstanceError):
        patterns[0].skip = 4


def test_full_distinct_reproducibility_and_no_global_rng():
    full = generator(values="full")
    distinct = generator()
    before = random.getstate()
    a = full.generate(num_patterns=10, instances_per_pattern=50, seed=42)
    b = distinct.generate(num_patterns=10, instances_per_pattern=50, seed=42)
    c = full.generate(num_patterns=10, instances_per_pattern=50, seed=42)
    assert fingerprints(a) == fingerprints(b) == fingerprints(c)
    assert before == random.getstate()
    # Frequencies do not influence either retention mode's proposals.
    skewed = generator(documents=DOCS + DOCS[:1] * 10000, values="full")
    assert fingerprints(a) == fingerprints(
        skewed.generate(num_patterns=10, instances_per_pattern=50, seed=42)
    )


def test_reproducible_across_hash_seeds():
    script = """
from bondi.mongodb import MongoCollectionRef, MongoWorkloadGenerator
from bondi.schema import Schema
s = Schema.from_documents([{'a':str(i),'b':i} for i in range(20)],values='full')
g = MongoWorkloadGenerator(target=MongoCollectionRef('d','c'),schema=s)
print([e.query.to_json() for e in g.generate(num_patterns=8,instances_per_pattern=4,seed=9)])
"""
    outputs = [
        subprocess.check_output(
            [sys.executable, "-c", script], env=os.environ | {"PYTHONHASHSEED": str(seed)}
        )
        for seed in (1, 23)
    ]
    assert outputs[0] == outputs[1]


def test_duplicates_allowed_one_instance_patterns_and_save_load(tmp_path):
    cfg = dict(
        min_predicates=1,
        max_predicates=1,
        sort_probability=0,
        limit_probability=0,
        operator_config={"types": {"bool": {"operators": ["eq"], "weights": [1]}}},
    )
    g = generator([{"flag": True}], **cfg)
    w, patterns = g.generate(num_patterns=1, instances_per_pattern=5, return_patterns=True)
    assert len(set(e.query.fingerprint() for e in w)) == 1
    with pytest.raises(WorkloadGenerationError) as error:
        g.generate(num_patterns=2, max_candidate_attempts=3)
    assert error.value.stats["completed_patterns"] == 1
    assert error.value.stats["duplicate_candidates"] == 2
    path = tmp_path / "queries.jsonl"
    w.save(path)
    restored = Workload.load(path)
    assert fingerprints(w) == fingerprints(restored)
    assert all(patterns[e.pattern_id].matches(e.query) for e in restored)
    assert len(generator().generate(num_patterns=10, seed=5)) == 10


class ThresholdEstimator:
    def __init__(self):
        self.calls = []

    def estimate(self, query):
        self.calls.append(query)
        return CardinalityEstimate(query.filter["x"]["$gte"], 100)


def test_selectivity_every_instance_before_limit_and_prepared_protocol():
    estimator = ThresholdEstimator()
    g = generator(
        estimator=estimator,
        include_fields=["x"],
        min_predicates=1,
        max_predicates=1,
        limit_probability=1,
        limit_min=1,
        limit_max=1,
        sort_probability=0,
        operator_config={"types": {"int": {"operators": ["gte"], "weights": [1]}}},
    )
    w = g.generate(
        num_patterns=1, instances_per_pattern=50, seed=1, min_selectivity=0.3, max_selectivity=0.6
    )
    assert len(estimator.calls) >= 50
    assert all(0.3 <= e.query.filter["x"]["$gte"] / 100 <= 0.6 for e in w)
    assert all(e.query.limit == 1 for e in w)
    before = len(estimator.calls)
    g.generate(num_patterns=1, seed=5)
    assert len(estimator.calls) == before  # no unnecessary estimator access


def test_callback_before_estimator_and_fixed_slot_targets():
    class Never:
        def estimate(self, query):
            pytest.fail("callback must precede estimation")

    calls = []

    def reject(pattern, previous):
        assert previous == ()
        calls.append((len(pattern.predicates), bool(pattern.sort), pattern.limit is not None))
        return False

    g = generator(estimator=Never())
    with pytest.raises(WorkloadGenerationError):
        g.generate(
            num_patterns=1,
            validate_pattern=reject,
            max_candidate_attempts=8,
            min_selectivity=0.1,
            seed=1,
        )
    assert len(calls) == 8 and len(set(calls)) == 1
    assert g.last_stats["validation_rejections"] == 8
    stats = g.last_stats
    assert json.loads(json.dumps(stats)) == stats
    stats["pending_pattern_target"]["num_predicates"] = 0
    assert g.last_stats["pending_pattern_target"]["num_predicates"] > 0


def test_discarded_group_never_returned_or_exposed_to_callback():
    class Alternating:
        def __init__(self):
            self.calls = 0

        def estimate(self, query):
            self.calls += 1
            return CardinalityEstimate(1 if self.calls % 2 else 0, 1)

    seen = []

    def validate(pattern, previous):
        seen.append(previous)
        return True

    g = generator(estimator=Alternating())
    with pytest.raises(WorkloadGenerationError):
        g.generate(
            num_patterns=2,
            instances_per_pattern=2,
            min_selectivity=1,
            max_instance_attempts=1,
            max_candidate_attempts=3,
            validate_pattern=validate,
        )
    assert seen == [(), (), ()]
    assert g.last_stats["discarded_groups"] == 3
    assert g.last_stats["completed_patterns"] == 0


def test_external_errors_and_deadline(monkeypatch):
    def fail(*args):
        raise LookupError("user callback")

    g = generator()
    with pytest.raises(LookupError, match="user callback"):
        g.generate(num_patterns=1, validate_pattern=fail)
    assert g.last_stats["candidate_attempts"] == 1
    clock = [0.0]
    monkeypatch.setattr("bondi.mongodb.generation.time.monotonic", lambda: clock[0])

    def slow(*args):
        clock[0] = 2
        return True

    with pytest.raises(WorkloadGenerationError, match="deadline"):
        g.generate(num_patterns=1, timeout_seconds=1, validate_pattern=slow)
    assert g.last_stats["elapsed_seconds"] == 2


@pytest.mark.parametrize(
    "result",
    [
        None,
        CardinalityEstimate(float("nan"), 10),
        CardinalityEstimate(11, 10),
        CardinalityEstimate(-1, 10),
    ],
)
def test_bad_estimator_results(result):
    class Estimator:
        def estimate(self, query):
            return result

    with pytest.raises((ValueError, TypeError)):
        generator(estimator=Estimator()).generate(num_patterns=1, min_selectivity=0.1)


def test_estimator_error_propagates():
    class Estimator:
        def estimate(self, query):
            raise RuntimeError("database unavailable")

    with pytest.raises(RuntimeError, match="database unavailable"):
        generator(estimator=Estimator()).generate(num_patterns=1, min_selectivity=0.1)


@pytest.mark.parametrize(
    "options",
    [
        {"num_patterns": 0},
        {"instances_per_pattern": False},
        {"return_patterns": 1},
        {"min_selectivity": -0.1},
        {"min_selectivity": 0.8, "max_selectivity": 0.2},
        {"timeout_seconds": 0},
        {"timeout_seconds": float("inf")},
        {"max_candidate_attempts": 0},
        {"max_instance_attempts": 0},
        {"seed": False},
    ],
)
def test_invalid_generation_options(options):
    with pytest.raises((ValueError, TypeError)):
        generator().generate(**({"num_patterns": 1} | options))


@pytest.mark.parametrize(
    "options",
    [
        {"sort_probability": 2},
        {"min_predicates": 0},
        {"min_predicates": 3, "max_predicates": 2},
        {"projection_min_fields": 0},
        {"skip_min": -1},
        {"limit_min": 0},
        {"skip_requires_limit": 1},
        {"include_fields": "x"},
        {"field_weights": {"default": 0}},
        {"field_weights": {"overrides": {"x": float("nan")}}},
        {"operator_config": {"types": {"int": {"operators": ["wat"], "weights": [1]}}}},
        {"operator_config": {"types": {"int": {"operators": ["eq"], "weights": [0]}}}},
    ],
)
def test_bad_config(options):
    with pytest.raises((ValueError, TypeError)):
        MongoGenerationConfig(**options)


def test_fields_exclusions_weights_and_disabled_retention():
    with pytest.raises(ValueError, match="retaining|values="):
        generator(values="none")
    with pytest.raises(ValueError, match="estimator"):
        generator().generate(num_patterns=1, min_selectivity=0.1)
    g = generator(include_fields=["x"], exclude_fields=["x"])
    w = g.generate(num_patterns=1, instances_per_pattern=10)
    assert all(set(e.query.filter) == {"x"} for e in w)
    g = generator(
        min_predicates=1,
        max_predicates=1,
        sort_probability=1,
        sort_on_filter_field_ratio=0,
        sort_two_field_ratio=0,
        projection_probability=1,
        projection_filter_overlap_ratio=0,
        projection_min_fields=1,
        projection_max_fields=1,
        field_weights={"default": 1, "overrides": {"*": 1, "x": 1e100}},
    )
    w = g.generate(num_patterns=1, instances_per_pattern=3, seed=2)
    assert all(
        set(e.query.filter) == {"x"} and e.query.sort[0][0] == "x" and e.query.projection["x"] == 1
        for e in w
    )


def test_unsupported_values_paths_and_schema_mutation_between_calls():
    with pytest.raises(ValueError, match="operand"):
        generator([{"bad": Decimal("1")}]).generate(num_patterns=1)
    with pytest.raises(ValueError, match="dot-path"):
        generator([{"literal.dot": 1}]).generate(num_patterns=1)
    g = generator([{"literal.dot": 1, "ok": 2}], exclude_fields=["literal\\.dot"])
    assert set(g.generate(num_patterns=1)[0].query.filter) == {"ok"}
    g = generator([{"a": 1}], min_predicates=2, max_predicates=2)
    with pytest.raises(WorkloadGenerationError, match="Insufficient"):
        g.generate(num_patterns=1)
    g.schema.update([{"a": 2, "b": 3}])
    assert len(g.generate(num_patterns=1)[0].query.filter) == 2


@pytest.mark.parametrize("operator,arity_range", [("in", (2, 10)), ("nin", (1, 10))])
def test_membership_arity_and_typed_pools(operator, arity_range):
    docs = [{"mixed": i} for i in range(12)] + [{"mixed": str(i)} for i in range(12)]
    g = generator(
        docs,
        min_predicates=1,
        max_predicates=1,
        sort_probability=0,
        limit_probability=0,
        operator_config={
            "types": {t: {"operators": [operator], "weights": [1]} for t in ("int", "str")}
        },
    )
    w, p = g.generate(num_patterns=4, instances_per_pattern=20, seed=5, return_patterns=True)
    for entry in w:
        values = entry.query.filter["mixed"]["$" + operator]
        assert arity_range[0] <= len(values) <= arity_range[1]
        assert len(set(values)) == len(values)
        assert len(set(map(type, values))) == 1
        assert p[entry.pattern_id].matches(entry.query)


@pytest.mark.parametrize(
    "operator,docs",
    [
        ("exists", [{"x": 1}, {}]),
        ("type", [{"x": 1}, {"x": "a"}]),
        ("size", [{"x": [1, 2]}, {"x": []}]),
    ],
)
def test_special_operators(operator, docs):
    types = {
        "int": {"operators": ["eq"], "weights": [1]},
        "str": {"operators": ["eq"], "weights": [1]},
    }
    g = generator(
        docs,
        min_predicates=1,
        max_predicates=1,
        sort_probability=0,
        limit_probability=0,
        operator_config={
            "types": types,
            "operators": {"$" + operator: {"enabled": True, "chance": 1}},
        },
    )
    w, p = g.generate(num_patterns=1, instances_per_pattern=20, return_patterns=True, seed=2)
    assert all("$" + operator in entry.query.filter["x"] for entry in w)
    assert all(p[0].matches(entry.query) for entry in w)
    if operator in ("type", "exists"):
        assert len({json.dumps(e.query.filter) for e in w}) == 1


def test_bson_persistence_patterns_and_projection_order(tmp_path):
    docs = [
        {"a": Int64(1), "b": ObjectId(), "c": datetime(2025, 1, 1, tzinfo=UTC), "d": None},
        {"a": Int64(2), "b": ObjectId(), "c": datetime(2025, 2, 1, tzinfo=UTC), "d": None},
    ]
    g = generator(docs, min_predicates=4, max_predicates=4)
    w, p = g.generate(num_patterns=2, instances_per_pattern=3, return_patterns=True, seed=8)
    w.save(tmp_path / "bson.jsonl")
    assert all(p[e.pattern_id].matches(e.query) for e in Workload.load(tmp_path / "bson.jsonl"))
    q = MongoFindQuery(
        TARGET, {"x": 1, "y": {"$gt": 2}}, projection={"x": 1, "y": 1}, sort=(("x", 1), ("y", -1))
    )
    pattern = MongoQueryPattern.from_query(q)
    q.filter = {"y": {"$gt": 99}, "x": 4}
    q.projection = {"y": 1, "x": 1}
    assert pattern.matches(q)
    q.sort = tuple(reversed(q.sort))
    assert not pattern.matches(q)


@pytest.mark.parametrize(
    "filter",
    [
        {"$or": [{"x": 1}, {"y": 2}]},
        {"x": {"$gte": 1, "$lte": 2}},
        {"x": {"literal": 1}},
        {"x": [1, 2]},
        {"x": {"$in": [1, "a"]}},
        {"x": {"$in": [1, 1]}},
        {"x": {"$size": -1}},
        {},
    ],
)
def test_unsupported_pattern_shapes(filter):
    with pytest.raises((ValueError, TypeError)):
        MongoQueryPattern.from_query(MongoFindQuery(TARGET, filter))


def test_invalid_template():
    with pytest.raises(ValueError):
        MongoPredicateTemplate("x", "exists", fixed_value="yes")


def test_nested_arrays_and_source_type_binding():
    docs = [{"items": [{"score": i}, {"score": str(i)}], "tags": ["a", "b"]} for i in range(10)]
    g = generator(
        docs,
        min_predicates=2,
        max_predicates=2,
        sort_probability=0,
        operator_config={
            "types": {t: {"operators": ["eq"], "weights": [1]} for t in ("int", "str")}
        },
    )
    w, p = g.generate(num_patterns=2, instances_per_pattern=20, seed=1, return_patterns=True)
    assert all(set(e.query.filter) == {"items.score", "tags"} for e in w)
    assert all(p[e.pattern_id].matches(e.query) for e in w)


def test_async_estimator_and_callback_rejected():
    class AsyncEstimator:
        async def estimate(self, query):
            return CardinalityEstimate(1, 1)

    with pytest.raises(TypeError, match="synchronous"):
        generator(estimator=AsyncEstimator())

    async def callback(*args):
        return True

    with pytest.raises(TypeError, match="synchronous"):
        generator().generate(num_patterns=1, validate_pattern=callback)


def test_successful_callback_sees_only_completed_patterns():
    previous_sizes = []

    def callback(pattern, previous):
        assert isinstance(previous, tuple)
        previous_sizes.append(len(previous))
        return True

    w, p = generator().generate(
        num_patterns=4,
        instances_per_pattern=5,
        validate_pattern=callback,
        return_patterns=True,
        seed=4,
    )
    assert previous_sizes == [0, 1, 2, 3]
    assert len(w) == 20 and len(p) == 4


def test_defaults_are_independent_and_invalid_call_clears_stats():
    a, b = MongoGenerationConfig(), MongoGenerationConfig()
    a.operator_config["types"]["int"]["weights"][0] = 99
    assert a.operator_config["types"]["Int64"]["weights"][0] == 1
    assert b.operator_config["types"]["int"]["weights"][0] == 1
    g = generator()
    g.generate(num_patterns=1)
    with pytest.raises(ValueError):
        g.generate(num_patterns=0)
    assert dict(g.last_stats) == {}


def test_error_stats_are_serializable_and_independent():
    source = {"nested": {"count": 1}}
    error = WorkloadGenerationError("exhausted", source)
    assert json.loads(json.dumps(error.stats)) == source
    error.stats["nested"]["count"] = 2
    assert source["nested"]["count"] == 1
