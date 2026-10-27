"""Shared public summary contract and backend-specific format selection."""

import pytest

from bondi.couchbase import summarize as couchbase_summary
from bondi.mongodb import summarize as mongodb_summary
from bondi.summary import QuerySummary


@pytest.mark.parametrize("summarize", [mongodb_summary, couchbase_summary])
def test_absent_diagnostics_are_distinct_from_unrecognized_data(summarize):
    assert summarize(None) == QuerySummary()
    for raw in ({}, {"unrelated": 1}, [], False):
        with pytest.raises(ValueError):
            summarize(raw)


def test_couchbase_dispatch_does_not_confuse_planning_metrics_with_execution():
    plan = {"plan": {"#operator": "DummyScan"}, "metrics": {"execution_ms": 7, "result_count": 1}}
    assert couchbase_summary(plan) == QuerySummary(plan_stages=("DummyScan",), index_names=())
    assert couchbase_summary({"metrics": plan["metrics"]}) == QuerySummary(
        execution_time_ms=7, rows_returned=1
    )
    with pytest.raises(ValueError):
        couchbase_summary({**plan, "status": "fatal"})
    # A malformed plan cannot silently fall back to otherwise valid execution metadata.
    with pytest.raises(ValueError):
        couchbase_summary({**plan, "plan": []})


def test_backend_formats_are_not_interchangeable():
    with pytest.raises(ValueError):
        mongodb_summary({"plan": {"#operator": "DummyScan"}})
    with pytest.raises(ValueError):
        couchbase_summary({"queryPlanner": {"winningPlan": {"stage": "COLLSCAN"}}})
