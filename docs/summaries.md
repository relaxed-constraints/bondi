# Understanding query summaries

Both backends expose `summarize(raw)`. Import it from the backend that produced the
response. The parser operates offline and returns the shared `QuerySummary` class.

```python
from dbrtoolkit.mongodb import summarize

# profile is an ExecutionResult from executor.profile(query).
summary = summarize(profile.raw)
print(summary.plan_stages, summary.index_names)
print(summary.documents_examined, summary.keys_examined)
```

| Field | Meaning |
| --- | --- |
| `execution_time_ms` | Server-reported execution time, when available |
| `rows_returned` | Server-reported output count |
| `documents_examined` | Whole-operation document examinations, not unique documents |
| `keys_examined` | Whole-operation index entries examined |
| `plan_stages` | Native structured stage names, retaining traversal order and repetitions |
| `index_names` | Unique index names in encounter order |

**`None` means unavailable, not zero.** An empty index tuple means no named index
was found within a supported plan; it does not alone prove a collection scan.
The plan-stage tuple is a convenient description, not a complete plan tree.

MongoDB structured plan stages such as `IXSCAN` and `GROUP` differ from aggregation
pipeline operators such as `$group`. The parser does not conflate them. Couchbase
operator output counts are not automatically document/index examination counts;
unsupported totals remain `None`.

Use `result.elapsed_ms` for client-observed duration and the summary for server
measurements. Check workload result errors before parsing. `summarize(None)` returns
an empty summary; malformed or failed responses are not silently accepted.

See [shared fields](reference/results.md), [MongoDB parsing](reference/mongodb/summaries.md)
and [Couchbase parsing](reference/couchbase/summaries.md) for supported layouts and boundaries.
