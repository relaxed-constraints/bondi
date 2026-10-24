"""Conservative, offline summaries of MongoDB explain documents."""

import math
from typing import Any

from dbrtoolkit.summary import QuerySummary

# These stages do not introduce additional collection reads. Unknown stages (including
# nested pipelines) conservatively prevent reporting cursor counts as operation totals.
_CURSOR_ONLY_READS = {
    "$match",
    "$project",
    "$addFields",
    "$set",
    "$unset",
    "$replaceRoot",
    "$replaceWith",
    "$limit",
    "$skip",
    "$sort",
    "$group",
    "$count",
    "$unwind",
    "$sample",
    "$sortByCount",
}
_CHILDREN = ("inputStage", "inputStages", "outerStage", "innerStage", "thenStage", "elseStage")
_INDEX_STAGES = {
    "IXSCAN",
    "DISTINCT_SCAN",
    "COUNT_SCAN",
    "EXPRESS_IXSCAN",
    "GEO_NEAR_2D",
    "GEO_NEAR_2DSPHERE",
    "TEXT_MATCH",
}


def _document(value: Any, name: str) -> dict:
    if not isinstance(value, dict):
        raise ValueError(f"{name} must be a document")
    return value


def _metric(stats: dict, key: str, *, time: bool = False) -> int | float | None:
    if key not in stats:
        return None
    value = stats[key]
    valid = isinstance(value, (int, float)) if time else isinstance(value, int)
    if isinstance(value, bool) or not valid or value < 0 or (time and not math.isfinite(value)):
        raise ValueError(f"{key} must be a finite nonnegative {'number' if time else 'integer'}")
    return float(value) if time else value


def _plan(planner: dict) -> tuple[tuple[str, ...] | None, tuple[str, ...] | None]:
    if "winningPlan" not in planner:
        return None, None
    root = _document(planner["winningPlan"], "winningPlan")
    if "queryPlan" in root:
        root = _document(root["queryPlan"], "queryPlan")
    stages, indexes = [], []
    complete, index_complete = True, True

    def visit(node: dict) -> None:
        nonlocal complete, index_complete
        if "shards" in node or "stage" not in node:
            complete = False
            return
        stage = node["stage"]
        if not isinstance(stage, str) or not stage:
            raise ValueError("plan stage must be a nonempty string")
        stages.append(stage)
        if "indexName" in node:
            name = node["indexName"]
            if not isinstance(name, str) or not name:
                raise ValueError("indexName must be a nonempty string")
            if name not in indexes:
                indexes.append(name)
        elif stage in _INDEX_STAGES:
            index_complete = False
        for key in _CHILDREN:
            if key not in node:
                continue
            children = node[key]
            if key == "inputStages":
                if not isinstance(children, list):
                    raise ValueError("inputStages must be a list")
            else:
                children = [children]
            for child in children:
                visit(_document(child, key))

    visit(root)
    return (
        tuple(stages) if complete else None,
        tuple(indexes) if complete and index_complete else None,
    )


def summarize_explain(explain: dict[str, Any]) -> QuerySummary:
    """Summarize a successful MongoDB explain without a connection or source mutation.

    Supports standalone classic/SBE structured winning plans, top-level execution
    statistics, and aggregation stages beginning with $cursor. For split pipelines,
    final-stage nReturned is used; execution time is unavailable. Cursor examination
    totals and index names are retained only for explicitly supported stages that
    introduce no additional reads. Facets, lookups and unknown pipeline stages leave
    those fields unavailable. Sharded explains currently return an empty summary.

    Planner-only explains have no execution metrics. Unsupported layouts return None
    fields; malformed supported structures/metrics and failed commands raise ValueError.
    This is structural validation of the fields consumed, not the entire MongoDB schema.

    Args:
        explain: Raw explain document, for example ExecutionResult.raw.

    Returns:
        A frozen summary; keep the raw document for project-specific analysis.

    Raises:
        ValueError: Input is not an explain document, reports failure, or contains
            malformed fields in a supported layout.
    """
    raw = _document(explain, "explain")
    if not raw or not any(k in raw for k in ("queryPlanner", "stages", "shards", "ok")):
        raise ValueError("Expected a MongoDB explain document")
    if "ok" in raw and raw["ok"] != 1:
        raise ValueError("Explain command did not succeed")
    if "shards" in raw:
        return QuerySummary()

    source = raw
    pipeline = None
    safe_reads = True
    if "stages" in raw:
        pipeline = raw["stages"]
        if not isinstance(pipeline, list):
            raise ValueError("stages must be a list")
        for stage in pipeline:
            _document(stage, "pipeline stage")
            if len([k for k in stage if k.startswith("$")]) != 1:
                raise ValueError("pipeline stage must contain one operator")
        if not pipeline or "$cursor" not in pipeline[0]:
            return QuerySummary()
        source = _document(pipeline[0]["$cursor"], "$cursor")
        safe_reads = all(
            next(k for k in stage if k.startswith("$")) in _CURSOR_ONLY_READS
            for stage in pipeline[1:]
        )

    planner = _document(source.get("queryPlanner", {}), "queryPlanner")
    stages, indexes = _plan(planner)
    # Distributed plan statistics have different scope; do not interpret them as local totals.
    if stages is None and "winningPlan" in planner:
        return QuerySummary()
    stats = _document(source.get("executionStats", {}), "executionStats")
    if stats.get("executionSuccess") is False:
        raise ValueError("Explained execution did not succeed")
    elapsed = _metric(stats, "executionTimeMillis", time=True)
    returned = _metric(stats, "nReturned")
    documents = _metric(stats, "totalDocsExamined")
    keys = _metric(stats, "totalKeysExamined")
    if pipeline is not None and len(pipeline) > 1:
        elapsed = None
        returned = _metric(pipeline[-1], "nReturned")
    if not safe_reads:
        documents, keys, indexes = None, None, None
    return QuerySummary(elapsed, returned, documents, keys, stages, indexes)
