"""Offline parsing of saved Community and Enterprise responses; no SDK needed."""

import json
from copy import deepcopy
from pathlib import Path

import pytest

from bondi.couchbase import summarize
from bondi.summary import QuerySummary

FIXTURES = Path(__file__).parent / "fixtures" / "couchbase"


@pytest.mark.parametrize("path", sorted(FIXTURES.glob("*.json")), ids=lambda p: p.stem)
def test_real_server_fixtures(path):
    fixture = json.loads(path.read_text())
    before = deepcopy(fixture)
    case = path.stem.split("_", 1)[1]
    expected_rows = {
        "filtered": 1,
        "covering": 3,
        "aggregation": 3,
        "empty": 0,
        "scalar": 1,
        "sorted": 1,
    }[case]
    expected_indexes = (
        () if case == "scalar" else (("#primary",) if case == "aggregation" else ("city_stars",))
    )
    plan = summarize(fixture["explain"])
    assert plan.plan_stages[0] == "Sequence"
    assert plan.index_names == expected_indexes
    assert plan.execution_time_ms is plan.rows_returned is None
    for mode in ("run", "profile"):
        summary = summarize(fixture[mode])
        assert isinstance(summary, QuerySummary)
        assert summary.rows_returned == expected_rows
        assert summary.execution_time_ms == fixture[mode]["metrics"]["execution_ms"]
        assert summary.documents_examined is summary.keys_examined is None
        if mode == "profile" and fixture["edition"] == "enterprise":
            assert summary.plan_stages[0] == "Authorize"
            assert summary.index_names == expected_indexes
            if case == "covering":
                assert "Fetch" not in summary.plan_stages
            if case == "aggregation":
                assert "FinalGroup" in summary.plan_stages
        else:
            assert summary.plan_stages is summary.index_names is None
    assert fixture == before


def test_root_first_order_repeats_and_ignore_embedded_data():
    raw = {
        "plan": {
            "#operator": "Sequence",
            "~children": [
                {"#operator": "IndexScan3", "index": "b"},
                {
                    "#operator": "Parallel",
                    "~child": {
                        "#operator": "Sequence",
                        "~children": [
                            {"#operator": "IndexScan3", "index": "a"},
                            {"#operator": "IndexScan3", "index": "b"},
                        ],
                    },
                },
                {
                    "#operator": "InitialProject",
                    "result_terms": [{"#operator": "Fake", "index": "fake"}],
                },
            ],
        },
        "metrics": {"execution_ms": 99, "result_count": 1},
    }
    summary = summarize(raw)
    assert summary.plan_stages == (
        "Sequence",
        "IndexScan3",
        "Parallel",
        "Sequence",
        "IndexScan3",
        "IndexScan3",
        "InitialProject",
    )
    assert summary.index_names == ("b", "a")
    assert summary.execution_time_ms is summary.rows_returned is None


@pytest.mark.parametrize(
    "profile", [None, {}, {"phaseCounts": {"fetch": 30}, "phaseTimes": {"run": "9s"}}]
)
def test_basic_metrics_without_operator_tree(profile):
    assert summarize(
        {"status": "success", "metrics": {"execution_ms": 0, "result_count": 0}, "profile": profile}
    ) == QuerySummary(execution_time_ms=0.0, rows_returned=0)
    assert summarize({"metrics": None, "profile": profile}) == QuerySummary()


def test_do_not_infer_counts_or_time_from_operators():
    summary = summarize(
        {
            "profile": {
                "executionTimings": {
                    "#operator": "IndexScan3",
                    "index": "idx",
                    "#stats": {
                        "#itemsIn": 100,
                        "#itemsOut": 2,
                        "execTime": "9s",
                        "servTime": "10s",
                    },
                }
            }
        }
    )
    assert summary == QuerySummary(plan_stages=("IndexScan3",), index_names=("idx",))


@pytest.mark.parametrize(
    "root",
    [
        {},
        {"#operator": "FutureScan", "index": "unknown"},
        {"#operator": "Sequence"},
        {"#operator": "Sequence", "~children": [{"#operator": "HashJoin"}]},
        {"#operator": "Fetch", "~subqueries": []},
    ],
)
def test_unsupported_layout_keeps_basic_metrics(root):
    assert summarize({"plan": root}) == QuerySummary()
    assert summarize(
        {"metrics": {"result_count": 2}, "profile": {"executionTimings": root}}
    ) == QuerySummary(rows_returned=2)


def test_missing_index_name_is_unavailable_not_no_index():
    assert summarize({"plan": {"#operator": "PrimaryScan3"}}) == QuerySummary(
        plan_stages=("PrimaryScan3",)
    )


@pytest.mark.parametrize(
    "raw",
    [
        [],
        {},
        {"results": []},
        {"plan": []},
        {"plan": {"#operator": 1}},
        {"plan": {"#operator": ""}},
        {"plan": {"#operator": "IndexScan3", "index": 1}},
        {"plan": {"#operator": "Sequence", "~children": {}}},
        {"plan": {"#operator": "Parallel", "~child": None}},
        {"plan": {}, "status": "fatal"},
        {"plan": {}, "errors": [{"code": 1}]},
    ],
)
def test_malformed_explains(raw):
    with pytest.raises(ValueError):
        summarize(raw)


@pytest.mark.parametrize(
    "key,value",
    [
        ("execution_ms", True),
        ("execution_ms", -1),
        ("execution_ms", "1ms"),
        ("execution_ms", float("nan")),
        ("execution_ms", float("inf")),
        ("result_count", 1.5),
        ("result_count", True),
        ("result_count", -1),
        ("error_count", 1),
        ("error_count", -1),
    ],
)
def test_invalid_metrics(key, value):
    with pytest.raises(ValueError):
        summarize({"metrics": {key: value}})


@pytest.mark.parametrize(
    "raw",
    [
        [],
        {},
        {"status": "running"},
        {"status": "timeout"},
        {"metrics": []},
        {"profile": []},
        {"metrics": {"executionTime": "1ms"}},
        {"profile": {"executionTimings": []}},
        {"status": "success", "errors": [1]},
    ],
)
def test_wrong_execution_shape_or_failure(raw):
    with pytest.raises(ValueError):
        summarize(raw)


def test_cycle_is_rejected():
    root = {"#operator": "Parallel"}
    root["~child"] = root
    with pytest.raises(ValueError, match="cycle"):
        summarize({"plan": root})
