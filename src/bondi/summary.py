"""Common query measurements produced by explicit, backend-specific parsers."""

from dataclasses import dataclass


@dataclass(frozen=True)
class QuerySummary:
    """Describe observed query metrics and plan information, independently of execution.

    Backend parsers define which fields can be populated for a particular response.
    Executors do not construct or attach summaries automatically. A shared field name
    does not imply identical measurement procedures across databases.

    Attributes:
        execution_time_ms: Server-reported execution duration in milliseconds. Backend
            semantics apply; not client elapsed time or a sum of operator estimates.
        rows_returned: Final query output count, including scalar or array rows.
            Not the number of plan documents returned by an explain operation.
        documents_examined: Whole-operation document examinations, not distinct
            documents. Unavailable when the backend only reports a different counter.
        keys_examined: Whole-operation index entries examined, not distinct values
            or simply the number of items emitted by an index operator.
        plan_stages: Native structured plan stage names in root-first traversal order,
            preserving repetitions. A flattened description, not a complete plan tree.
        index_names: Unique index names in first-encounter order; unavailable when
            the parser cannot determine complete index usage for its supported scope.

    None means unavailable or unsupported, never zero. An empty index_names tuple
    means no named index use was found in a supported plan; it does not prove a
    collection scan. Keep the raw response separately for backend-specific analysis.
    This frozen value object provides no merging or automatic validation.

    Examples:
        >>> QuerySummary(rows_returned=0).rows_returned
        0
        >>> QuerySummary().keys_examined is None
        True
    """

    execution_time_ms: float | None = None
    rows_returned: int | None = None
    documents_examined: int | None = None
    keys_examined: int | None = None
    plan_stages: tuple[str, ...] | None = None
    index_names: tuple[str, ...] | None = None
