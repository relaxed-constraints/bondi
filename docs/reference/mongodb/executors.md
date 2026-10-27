# MongoDB executors

::: bondi.mongodb.MongoExecutor
    options:
      show_root_heading: true
      heading_level: 2
      inherited_members: true

::: bondi.mongodb.AsyncMongoExecutor
    options:
      show_root_heading: true
      heading_level: 2

## Timing and deadlines


Elapsed milliseconds use a monotonic clock and represent client-observed duration,
including decoding, transfer, full cursor consumption and cleanup. Successful
operation timing excludes validation and scheduler waiting. Captured failure timing
covers the delegated call, including its small validation overhead, and excludes
scheduler waiting. It is not server processing time or total workload wall time.

`timeout_seconds` must be positive and finite, or None. A PyMongo timeout context
surrounds the operation and full cursor iteration, sharing one deadline across
batches. None leaves client defaults in effect. Cleanup happens outside an expired
operation deadline and can add time. A client timeout is not a hard interruption of
arbitrary Python computation or proof the server stopped immediately.

## Native option escape hatches

- `run(..., query_kwargs=...)` forwards native PyMongo find/aggregate keyword options.
- `explain(..., query_kwargs=...)` supplies fields inside the native find/aggregate command.
- `explain(..., command_kwargs=...)` supplies outer `Database.command` options.

```python
executor.run(query, query_kwargs={"hint": "stars_1"})
executor.profile(
    query,
    verbosity="executionStats",
    query_kwargs={"hint": "stars_1"},
    command_kwargs={"maxTimeMS": 5000},
)
```

Query fields and generated command structure cannot be overridden, nor can callers
turn off command error checking. Options use native names: find uses `batch_size`,
while aggregate uses `batchSize`. Explain inner options are server command fields,
not cursor-specific Python arguments. Workload calls apply identical options to
every entry; they do not translate options between query kinds. Unknown options
are left to the driver/server. Native options can affect execution and semantics;
the query fingerprint alone does not identify those options or the environment.

The executor imposes no read-only guard; aggregation may write through `$out` or
`$merge`. Database permissions determine access. These methods are not restricted
to read-only queries merely because they are called run or explain.

