# Couchbase summary parsing

::: bondi.couchbase.summarize
    options:
      show_root_heading: true
      heading_level: 2

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
