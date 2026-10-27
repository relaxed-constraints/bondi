# MongoDB summary parsing

::: bondi.mongodb.summarize
    options:
      show_root_heading: true
      heading_level: 2

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


