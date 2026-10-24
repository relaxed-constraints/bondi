"""Offline interpretation of Couchbase plans and toolkit execution metadata."""

import math
from typing import Any

from dbrtoolkit.summary import QuerySummary

# Restrict interpretation to tested shapes. Unknown operators may hide additional
# branches or index references, so never report a partial traversal as complete.
_BRANCHES = {"Sequence": "~children", "Parallel": "~child", "Authorize": "~child"}
_LEAVES = {
    "IndexScan3",
    "PrimaryScan3",
    "Fetch",
    "Filter",
    "InitialProject",
    "InitialGroup",
    "IntermediateGroup",
    "FinalGroup",
    "Stream",
    "DummyScan",
    "Order",
    "Limit",
    "Offset",
}
_INDEXES = {"IndexScan3", "PrimaryScan3"}


def _document(value: Any, name: str) -> dict:
    if not isinstance(value, dict):
        raise ValueError(f"{name} must be a document")
    return value


def _name(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{name} must be a nonempty string")
    return value


def _plan(root: dict) -> tuple[tuple[str, ...] | None, tuple[str, ...] | None]:
    stages, indexes = [], []
    complete = index_complete = True
    active = set()

    def visit(node):
        nonlocal complete, index_complete
        node = _document(node, "operator")
        identity = id(node)
        if identity in active:
            raise ValueError("Plan contains a cycle")
        active.add(identity)
        try:
            if "#operator" not in node:
                complete = False
                return
            operator = _name(node["#operator"], "#operator")
            if operator not in _BRANCHES and operator not in _LEAVES:
                complete = False
                return
            stages.append(operator)
            if operator in _INDEXES:
                if "index" not in node:
                    index_complete = False
                else:
                    name = _name(node["index"], "index")
                    if name not in indexes:
                        indexes.append(name)
            edge = _BRANCHES.get(operator)
            # Unknown structural fields may encode subqueries or distributed plans.
            if any(
                isinstance(k, str) and k.startswith("~") and k not in (edge, "~versions")
                for k in node
            ):
                complete = False
            if edge is None:
                return
            if edge not in node:
                complete = False
                return
            children = node[edge]
            if edge == "~children":
                if not isinstance(children, list):
                    raise ValueError("~children must be a list")
            else:
                children = [children]
            for child in children:
                visit(child)
        finally:
            active.remove(identity)

    visit(root)
    return (
        tuple(stages) if complete else None,
        tuple(indexes) if complete and index_complete else None,
    )


def _metric(metrics: dict, key: str, *, duration: bool = False) -> int | float | None:
    value = metrics.get(key)
    if value is None:
        return None
    valid = type(value) in (int, float) if duration else type(value) is int
    if not valid or value < 0:
        raise ValueError(f"{key} must be a nonnegative {'number' if duration else 'integer'}")
    if duration:
        try:
            value = float(value)
        except OverflowError as error:
            raise ValueError(f"{key} must be finite") from error
        if not math.isfinite(value):
            raise ValueError(f"{key} must be finite")
    return value


def _successful(raw: dict) -> None:
    if "status" in raw and raw["status"] not in ("success", "completed"):
        raise ValueError("Couchbase request did not succeed")
    if raw.get("errors"):
        raise ValueError("Couchbase response reports errors")


def summarize_explain(explain: dict[str, Any]) -> QuerySummary:
    """Extract native operators and index names from a Couchbase EXPLAIN result row.

    Args:
        explain: ExecutionResult.raw from AsyncCouchbaseExecutor.explain(), containing
            a plan document. Pass the result row, not a REST envelope or list of rows.

    Returns:
        A QuerySummary with plan fields only. All execution measurements remain None,
        even if the input includes metrics for the EXPLAIN request itself. Traversal
        is root-first and preserves repeated operators; index names are deduplicated
        in encounter order. Unknown operators/layouts leave both plan fields None.

    Raises:
        ValueError: Wrong input shape, reported failure, or malformed consumed fields.

    No SDK, connection, source mutation or automatic execution is involved. Supported
    shapes are the simple scan/filter/projection/group plans captured in our fixtures;
    joins, unions, nested subqueries and distributed interpretation are deferred.
    """
    raw = _document(explain, "explain")
    _successful(raw)
    if "plan" not in raw:
        raise ValueError("Expected a Couchbase EXPLAIN result row containing plan")
    stages, indexes = _plan(_document(raw["plan"], "plan"))
    return QuerySummary(plan_stages=stages, index_names=indexes)


def summarize_execution(metadata: dict[str, Any]) -> QuerySummary:
    """Summarize run/profile metadata produced by AsyncCouchbaseExecutor.

    Args:
        metadata: ExecutionResult.raw from run() or profile(), using the toolkit's
            JSON-compatible SDK metadata representation, not HTTP duration strings.

    Returns:
        Server execution_ms and result_count become execution_time_ms and
        rows_returned. An executionTimings profile supplies native plan fields when
        its layout is supported. Community/ordinary execution or phases-only metadata
        still provides basic metrics. Missing fields remain None; zero stays zero.
        documents_examined and keys_examined are always None: operator input/output
        counters do not establish comparable whole-query examination totals.

    Raises:
        ValueError: Wrong input shape, failed request, invalid metrics or malformed
            supported operator structures.

    Does not sum phase/operator times or counts, infer rows from operator output,
    merge separate explains, require the SDK, or modify the source.
    """
    raw = _document(metadata, "metadata")
    if "plan" in raw or not any(k in raw for k in ("metrics", "profile", "status")):
        raise ValueError("Expected toolkit Couchbase run/profile metadata")
    _successful(raw)
    metrics = {} if raw.get("metrics") is None else _document(raw["metrics"], "metrics")
    if "executionTime" in metrics or "resultCount" in metrics:
        raise ValueError("Expected toolkit SDK metrics, not a REST response")
    if _metric(metrics, "error_count") not in (None, 0):
        raise ValueError("Couchbase execution reports errors")
    elapsed = _metric(metrics, "execution_ms", duration=True)
    returned = _metric(metrics, "result_count")
    profile = {} if raw.get("profile") is None else _document(raw["profile"], "profile")
    stages = indexes = None
    if profile.get("executionTimings") is not None:
        stages, indexes = _plan(_document(profile["executionTimings"], "executionTimings"))
    return QuerySummary(
        execution_time_ms=elapsed, rows_returned=returned, plan_stages=stages, index_names=indexes
    )
