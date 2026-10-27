"""Offline contracts tested against real MongoDB 8.0.4 explains and edge cases."""

import json
from copy import deepcopy
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest
from bson import Int64

from bondi.mongodb import summarize
from bondi.summary import QuerySummary

FIXTURES = Path(__file__).parent / "fixtures" / "explain"


def fixture(name):
    return json.loads((FIXTURES / f"{name}.json").read_text())


@pytest.mark.parametrize(
    "name,stages,indexes,returned",
    [
        ("find_collscan", ("LIMIT", "COLLSCAN"), (), 5),
        ("find_index", ("LIMIT", "FETCH", "IXSCAN"), ("_id_",), 5),
        ("aggregate_group", ("GROUP", "COLLSCAN"), (), 33),
        ("aggregate_sort", ("SORT", "COLLSCAN"), (), 5),
    ],
)
def test_real_top_level_explains(name, stages, indexes, returned):
    raw = fixture(name)
    before = deepcopy(raw)
    summary = summarize(raw)
    stats = raw["executionStats"]
    assert summary == QuerySummary(
        stats["executionTimeMillis"],
        returned,
        stats["totalDocsExamined"],
        stats["totalKeysExamined"],
        stages,
        indexes,
    )
    assert raw == before
    with pytest.raises(FrozenInstanceError):
        summary.keys_examined = 42


@pytest.mark.parametrize("name,returned", [("aggregate_facet", 1), ("aggregate_lookup", 2)])
def test_real_split_pipelines_do_not_claim_cursor_totals(name, returned):
    summary = summarize(fixture(name))
    assert summary.rows_returned == returned
    assert summary.execution_time_ms is None
    assert summary.documents_examined is None
    assert summary.keys_examined is None
    assert summary.index_names is None
    assert summary.plan_stages
    assert all(not name.startswith("$") for name in summary.plan_stages)


def test_planner_only_and_rejected_candidates():
    raw = fixture("find_collscan")
    del raw["executionStats"]
    raw["queryPlanner"]["rejectedPlans"] = [{"stage": "IXSCAN", "indexName": "rejected"}]
    summary = summarize(raw)
    assert summary == QuerySummary(plan_stages=("LIMIT", "COLLSCAN"), index_names=())


def test_branching_order_repeated_stages_and_unique_indexes():
    raw = {
        "queryPlanner": {
            "winningPlan": {
                "stage": "OR",
                "inputStages": [
                    {"stage": "IXSCAN", "indexName": "a"},
                    {"stage": "FETCH", "inputStage": {"stage": "IXSCAN", "indexName": "b"}},
                    {"stage": "IXSCAN", "indexName": "a"},
                ],
            }
        }
    }
    summary = summarize(raw)
    assert summary.plan_stages == ("OR", "IXSCAN", "FETCH", "IXSCAN", "IXSCAN")
    assert summary.index_names == ("a", "b")


def test_read_free_pipeline_final_output_and_no_time_estimate_sum():
    raw = {
        "stages": [
            {"$cursor": fixture("find_collscan"), "nReturned": 5},
            {"$group": {"_id": "$city"}, "nReturned": 2, "executionTimeMillisEstimate": 123},
        ]
    }
    summary = summarize(raw)
    assert summary.rows_returned == 2
    assert (
        summary.documents_examined
        == raw["stages"][0]["$cursor"]["executionStats"]["totalDocsExamined"]
    )
    assert summary.keys_examined == 0
    assert summary.index_names == ()
    assert summary.execution_time_ms is None
    assert summary.plan_stages == ("LIMIT", "COLLSCAN")
    del raw["stages"][1]["nReturned"]
    assert summarize(raw).rows_returned is None


def test_unknown_pipeline_prevents_false_index_and_examination_totals():
    raw = {"stages": [{"$cursor": fixture("find_index")}, {"$futureStage": {}, "nReturned": 1}]}
    summary = summarize(raw)
    assert summary.rows_returned == 1
    assert summary.index_names is None
    assert summary.keys_examined is None
    assert summary.documents_examined is None


def test_zero_missing_and_bson_integer_metrics():
    raw = {
        "queryPlanner": {"winningPlan": {"stage": "EOF"}},
        "executionStats": {"nReturned": Int64(0), "executionTimeMillis": Int64(0)},
    }
    assert summarize(raw) == QuerySummary(0.0, 0, None, None, ("EOF",), ())


@pytest.mark.parametrize(
    "raw",
    [
        {"ok": 1, "futureExplain": {}},
        {"shards": {}},
        {"stages": [{"$geoNearCursor": {}}]},
        {"queryPlanner": {"winningPlan": {"stage": "SHARD_MERGE", "shards": []}}},
        {"queryPlanner": {"winningPlan": {"futureLayout": {}}}},
    ],
)
def test_unsupported_layouts(raw):
    assert summarize(raw) == QuerySummary()


@pytest.mark.parametrize(
    "raw",
    [
        [],
        {},
        {"unrelated": 1},
        {"ok": 0},
        {"queryPlanner": []},
        {"queryPlanner": {"winningPlan": []}},
        {"queryPlanner": {"winningPlan": {"stage": 7}}},
        {"queryPlanner": {"winningPlan": {"stage": "IXSCAN", "indexName": 7}}},
        {"queryPlanner": {"winningPlan": {"stage": "FETCH", "inputStage": []}}},
        {"queryPlanner": {"winningPlan": {"stage": "OR", "inputStages": {}}}},
        {"stages": {}},
        {"stages": [None]},
        {"stages": [{"nReturned": 2}]},
        {"stages": [{"$cursor": []}]},
        {"ok": 1, "executionStats": []},
        {"ok": 1, "executionStats": {"executionSuccess": False}},
    ],
)
def test_malformed_input(raw):
    with pytest.raises(ValueError):
        summarize(raw)


@pytest.mark.parametrize(
    "key", ["executionTimeMillis", "nReturned", "totalDocsExamined", "totalKeysExamined"]
)
@pytest.mark.parametrize("value", [-1, True, "5", None, float("nan"), float("inf")])
def test_bad_metrics(key, value):
    with pytest.raises(ValueError):
        summarize({"ok": 1, "executionStats": {key: value}})


def test_incomplete_index_metadata_is_unknown_not_empty():
    summary = summarize({"queryPlanner": {"winningPlan": {"stage": "IXSCAN"}}})
    assert summary.plan_stages == ("IXSCAN",)
    assert summary.index_names is None
