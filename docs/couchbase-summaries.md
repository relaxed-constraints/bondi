# Couchbase query summaries

Parsing is an explicit, offline step. `summarize()` detects the response format and returns the shared frozen
`QuerySummary`, without the SDK, a connection, or source mutation.

```python
from dbrtoolkit.couchbase import summarize

# Inside an executor context:
plan = await executor.explain(query)
measured = await executor.profile(query)

plan_summary = summarize(plan.raw)
execution_summary = summarize(measured.raw)
print(plan_summary.index_names)
print(execution_summary.execution_time_ms, execution_summary.rows_returned)
```

`summarize()` also accepts `run().raw`. Basic metrics are useful on
Community; a detailed Enterprise profile adds operator and index information.
Keep `.raw` for research-specific counters. There is no automatic summary creation,
second query, or merge of separately collected explain and profile results.

## Field meanings

| Field | EXPLAIN | Run / profile |
| --- | --- | --- |
| `execution_time_ms` | `None` | SDK metadata `metrics.execution_ms`, already in milliseconds. |
| `rows_returned` | `None` | SDK metadata `metrics.result_count`, including scalar or array rows. |
| `documents_examined` | `None` | `None`: fetch input/output counts do not establish a comparable whole-query total. |
| `keys_examined` | `None` | `None`: index output items do not establish internal index entries examined. |
| `plan_stages` | Native `#operator` names under `plan`. | Native names under `profile.executionTimings`, when available and supported. |
| `index_names` | Native scan `index` names, including `#primary`. | Names from the supported execution tree. |

Missing values remain `None`; reported zero remains zero. EXPLAIN request timing
and result count describe plan generation, so the explain parser never presents
them as underlying-query measurements. Server execution time differs from the
client's `ExecutionResult.elapsed_ms`. Phase and operator times are never added.

Traversal is root-first, follows `~child` and `~children` in list order, and preserves
repeated operators. Index names are deduplicated in first-encounter order. This is
a flat description, not execution order or a unique plan fingerprint. Index names
are unqualified and may coincide across collections. An empty tuple means no named
index was found in the supported tree; missing scan names produce `None` instead.

EXPLAIN and execution profiles need not have identical trees. For example, a profile
can add `Authorize` and `Stream` and omit EXPLAIN's `Parallel` wrapper. Preserve these
native differences when comparing experiments.

## Supported inputs and limits

- `summarize()` accepts the single result row returned as `explain().raw`,
  containing a `plan` object. It does not accept a list of rows or an HTTP envelope.
- `summarize()` accepts the toolkit's JSON-compatible SDK metadata from
  `run().raw` / `profile().raw`, including restored JSON. It does not parse raw REST
  duration strings such as `executionTime: "1ms"`.
- Fixtures cover Community and Enterprise 7.6.2 using SDK 4.6.3: filtered and covering
  index scans, primary scans, grouping, empty results, scalars, sorting and limits.
- Supported operators are `Sequence`, `Parallel`, `Authorize`, `IndexScan3`,
  `PrimaryScan3`, `Fetch`, `Filter`, `InitialProject`, `InitialGroup`,
  `IntermediateGroup`, `FinalGroup`, `Stream`, `DummyScan`, `Order`, `Limit`, `Offset`.
- Unknown operators, missing tree structure and unknown structural `~` fields leave
  both plan fields `None`, while valid execution metrics remain available. Joins,
  unions, nested subqueries and distributed interpretation are deferred. The parser
  does not inspect SQL++ expressions or embedded user data for hidden index access.
- No operator tree (Community, ordinary execution or phases-only profiling) means
  no plan summary. No index use is inferred from phase names or counts.

Wrong input types, failed request statuses, reported errors, invalid consumed metrics,
malformed supported children and cyclic trees raise `ValueError`. Validation covers
consumed fields, not the complete server schema. A parser failure does not modify
the successful execution result. Extend fixture coverage before relying on a new
operator layout.

Couchbase defines `#itemsIn` and `#itemsOut` as operator input/output counts. See the
[Query Service response reference](https://docs.couchbase.com/server/current/n1ql-rest-query/index.html)
and [profiling documentation](https://docs.couchbase.com/server/7.6/n1ql/n1ql-manage/monitoring-n1ql-query.html).
The notebook `notebooks/couchbase_demo.ipynb` shows automatic format detection alongside raw metadata.


## No diagnostics and failures

`summarize(None)` returns an empty `QuerySummary`. Check `result.status` before
summarizing workload results: failures also have `raw=None`, so an empty summary
alone does not imply success. Unrecognized or malformed dictionaries raise
`ValueError`; they are not silently treated as absent diagnostics.

A top-level `plan` selects EXPLAIN interpretation, even when request metrics are
attached. Otherwise the parser reads toolkit execution metadata. It does not merge
both shapes or infer execution statistics from EXPLAIN request timing.
