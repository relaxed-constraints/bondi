# MongoDB explain summaries

The executor collects raw explains. `summarize_explain()` interprets them offline;
it neither connects to MongoDB nor changes the source document.

```python
from dataclasses import asdict
from dbrtoolkit.mongodb import summarize_explain

# Inside an async function or notebook:
result = await executor.profile(query, verbosity="executionStats")
summary = summarize_explain(result.raw)
print(summary.plan_stages)
print(summary.index_names)
print(asdict(summary))  # A convenient row for a research table.
```

Keep `result.raw` for further analysis. A project can extract additional metrics
from it without subclassing the summary or changing the executor. Workload results
can be summarized individually; first check for unstarted entries (`None`) and errors.

## Field definitions

`QuerySummary` (from `dbrtoolkit.summary`) is a shared frozen dataclass.
The definitions below describe how the MongoDB parser populates it. Each field defaults to `None`, meaning
unavailable or not reliably interpretable. A reported zero stays zero; missing
values never become zero.

| Field | Meaning |
| --- | --- |
| `execution_time_ms` | Server `executionTimeMillis`, including plan selection when applicable. Not client elapsed time, ordinary query latency, or a sum of stage estimates. |
| `rows_returned` | Final query or pipeline output count. For a split pipeline, use the last stage's `nReturned`, never the cursor's input count. |
| `documents_examined` | Whole-operation document examinations, not distinct documents. |
| `keys_examined` | Whole-operation index entries examined, not distinct values. |
| `plan_stages` | Structured winning query plan stage names in root-first order, preserving repetitions. |
| `index_names` | Winning-plan index names, deduplicated in first-encounter order. Unavailable if later pipeline reads prevent complete extraction. |

An empty `index_names` tuple means no named index use was found in the supported
plan; it does not prove COLLSCAN. Rejected plans and `allPlansExecution` candidate
statistics are excluded. Planner-only explains have no execution measurements.

## Plan stages versus pipeline operators

For classic plans, traversal starts at `queryPlanner.winningPlan`; for SBE plans,
it starts at `winningPlan.queryPlan`. The textual `slotBasedPlan.stages` and
engine-specific `executionStages` trees are not used for stage names.

For example, `$match` followed by `$group` may optimize into `("GROUP", "COLLSCAN")`.
A `$facet` pipeline may instead contain a `$cursor` plan and separate pipeline
operators. Only the cursor's query plan contributes to `plan_stages` in that case.
The field does **not** describe every operation in an aggregation.

Traversal visits the root before its children, follows `inputStages` in array order,
and visits `outerStage` before `innerStage` (or `thenStage` before `elseStage`). It
is not execution order or a unique plan fingerprint. Different trees can have the
same flattened stage sequence. No pipeline operators such as `$group` or `$facet`
are appended to it.

## Supported layouts and conservative boundaries

The first implementation is tested against saved MongoDB 8.0.4 explains:

- Standalone find and fully optimized aggregation explains: use top-level
  `executionStats` totals and the winning structured query plan.
- Split aggregations beginning with `$cursor`: use the final stage's output count.
  Whole-pipeline execution time is `None` when stages follow the cursor. Stage
  `executionTimeMillisEstimate` values are never summed.
- Cursor examination totals and index names are retained only when subsequent
  stages are explicitly known not to introduce more collection reads: `$match`,
  `$project`, `$addFields`, `$set`, `$unset`, `$replaceRoot`, `$replaceWith`, `$limit`,
  `$skip`, `$sort`, `$group`, `$count`, `$unwind`, `$sample`, and `$sortByCount`.
- `$lookup`, `$facet` and unknown pipeline operators leave examination totals and
  index names as `None`. Even a facet that happens to contain no additional reads
  is treated conservatively for now. Its final output count can still be reported.
- Sharded explains and other unsupported layouts return unavailable fields rather
  than guessed totals. No cross-shard summation or nested pipeline analysis yet.

Malformed supported structures, invalid metrics and reported command/execution
failures raise `ValueError`. Validation covers fields the parser consumes, not the
entire MongoDB explain schema. No parser can reliably infer semantics for arbitrary
future server layouts; extend fixture coverage before relying on a new layout.

See MongoDB's [explain reference](https://www.mongodb.com/docs/manual/reference/explain-results/)
for the source fields. The notebook `notebooks/workload_demo.ipynb` demonstrates
planner-only and measured summaries alongside the raw response.
