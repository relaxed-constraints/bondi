"""Offline summaries for PostgreSQL JSON plans."""

import math

from bondi.summary import QuerySummary

# These native scan types expose index identity via Index Name. Keep unsupported
# nodes conservative: a custom or foreign scan can hide its access path.
_INDEXED = {"Bitmap Index Scan", "Index Scan", "Index Only Scan"}
_KNOWN = _INDEXED | {
    "Seq Scan",
    "Bitmap Heap Scan",
    "Aggregate",
    "Sort",
    "Limit",
    "Result",
    "Group",
    "Gather",
    "Gather Merge",
    "Nested Loop",
    "Hash Join",
    "Hash",
    "Merge Join",
    "Append",
    "Merge Append",
    "Materialize",
    "Memoize",
    "Unique",
    "Subquery Scan",
    "CTE Scan",
    "Values Scan",
    "BitmapAnd",
    "BitmapOr",
}


def summarize(raw: dict | None) -> QuerySummary:
    """Interpret a BONDI PostgreSQL explain/profile response without database access."""
    if raw is None:
        return QuerySummary()
    if (
        not isinstance(raw, dict)
        or not isinstance(raw.get("explain"), list)
        or len(raw["explain"]) != 1
    ):
        raise ValueError("Expected one PostgreSQL JSON explain document")
    report = raw["explain"][0]
    if not isinstance(report, dict) or not isinstance(report.get("Plan"), dict):
        raise ValueError("Missing PostgreSQL plan")
    root = report["Plan"]
    pending = [root]
    stages = []
    names = []
    complete = True
    seen = set()
    while pending:
        node = pending.pop()
        if not isinstance(node, dict) or id(node) in seen:
            raise ValueError("Invalid PostgreSQL plan tree")
        seen.add(id(node))
        stage = node.get("Node Type")
        if not isinstance(stage, str) or not stage:
            raise ValueError("Invalid Node Type")
        stages.append(stage)
        complete &= stage in _KNOWN
        if stage in _INDEXED:
            index = node.get("Index Name")
            if not isinstance(index, str) or not index:
                complete = False
            elif index not in names:
                names.append(index)
        children = node.get("Plans", [])
        if not isinstance(children, list):
            raise ValueError("Invalid Plans")
        pending.extend(reversed(children))
    elapsed = report.get("Execution Time")
    if elapsed is not None and (
        type(elapsed) not in (int, float) or not math.isfinite(elapsed) or elapsed < 0
    ):
        raise ValueError("Invalid Execution Time")
    rows = (
        root.get("Actual Rows")
        if type(root.get("Actual Loops")) is int and root["Actual Loops"] == 1
        else None
    )
    if rows is not None and (type(rows) is not int or rows < 0):
        raise ValueError("Invalid Actual Rows")
    return QuerySummary(
        execution_time_ms=elapsed,
        rows_returned=rows,
        plan_stages=tuple(stages),
        index_names=tuple(names) if complete else None,
    )
