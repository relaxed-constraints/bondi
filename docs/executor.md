# MongoDB executor

`MongoExecutor` runs, explains or profiles individual MongoDB queries and complete
workloads. Its synchronous API works in scripts and notebooks; concurrent database work runs
on an internal background event loop. One `ExecutionResult`
class describes successes and captured workload failures.

## Connect and execute

```python
from dbrtoolkit.mongodb import MongoExecutor

# In a script or notebook:
with MongoExecutor.from_uri(
    uri,
    concurrency=4,
    continue_on_error=True,
    timeout_seconds=30,
    client_kwargs={"retryReads": False},
) as executor:
    results = executor.run_workload(workload)
```

The factory creates one owned client for the executor, not one per query.
The context manager closes the client and background loop. Alternatively, create
an executor directly with `from_uri()` and call `close()` when finished. Repeated
close calls are harmless. See [synchronous executors](sync-executors.md) for
notebook usage and interruption handling.
Client creation does not ping the server or exclude connection setup from the
first operation's timing. Warmups are not implemented yet.

## Single-query operations

```python
result = executor.run(query, collect_results=True)
print(result.row_count, result.elapsed_ms)

plan = executor.explain(query)
explanation = executor.profile(query)
print(explanation.raw)
```

Both find and aggregation queries are supported. Run always consumes the complete
cursor and closes it, including on error or cancellation. `collect_results=False`
is the default: documents are counted but not retained. On success, an empty
collected result is `[]`; when collection is disabled, documents is None.

`explain()` always requests `queryPlanner`: it collects a plan without executing
it for statistics. `profile()` requests `executionStats` by default, or accepts
`verbosity="allPlansExecution"` for candidate-plan trial statistics. It uses MongoDB's
explain command, not the database profiler, and issues no additional normal query.
Both return diagnostics in `raw`, with `documents` and `row_count` left as `None`.
Call `summarize(result.raw)` explicitly to extract server measurements.
Profiling timings are not interchangeable with ordinary execution timing.

Single-query methods raise driver/server exceptions. Structural validation occurs
before database operations. The executor uses input references, not snapshots:
**do not mutate queries, workloads or option contents until the call finishes**.

## Workloads and failures

```python
results = executor.run_workload(workload)
for entry, result in zip(workload, results):
    if result is None:
        print("Not started")
    elif result.status == "success":
        print(result.row_count, result.elapsed_ms)
    else:
        print(result.status, result.error)
```

`explain_workload()` and `profile_workload()` have the same scheduling/error policy. Results have exactly one
slot per input entry, in input order, including duplicate queries. There is no
separate workload result object. All entries and query types are validated before
starting. A custom Query implementation is not automatically executable here:
this executor accepts the two implemented MongoDB query classes only.

Concurrency defaults to 1 (sequential). A larger positive integer bounds in-flight
entries **per workload call**, not across unrelated calls on the same executor.
When `continue_on_error=False` (default), the first observed operation error stops
new scheduling; already-running operations finish. With True, remaining entries
are attempted. Empty workloads return an empty list.

Expected connection, server-operation and timeout failures are recorded in
ExecutionResult.error. Status is derived: success, timeout or error. It uses the
original PyMongo exception's timeout flag, not message matching. Partial documents
and counts are discarded after a failed cursor consumption. Programming/API-use
errors and caller cancellation propagate after outstanding workers are cancelled
and awaited. No extra retries are added; client retry settings still apply.

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

## Tests and next steps

Offline tests cover driver calls, cursor cleanup, concurrency, cancellation, error
policies and ownership. Opt-in integration tests create and remove a uniquely named
disposable database on an explicitly selected server:

```sh
DBRTOOLKIT_TEST_MONGODB_URI=mongodb://127.0.0.1:27017 uv run pytest tests/test_executor_mongodb.py
```

Only use that test command on a server where creating test data is allowed. It is
not a read-only check. The implementation was verified on a separate temporary
local server; no existing research datasets were modified.

Use [MongoDB explain summaries](explain.md) to parse the raw response offline.
Warmups, repetitions and execution-result persistence remain later steps. Workloads can be saved and loaded through Workload.save/load. See the [API reference](api.md) for signatures.

## Advanced: async integration and borrowed clients

`AsyncMongoExecutor` remains available when your application needs awaitable calls
or supplies its own `AsyncMongoClient`. For example:

```python
from dbrtoolkit.mongodb import AsyncMongoExecutor

async with AsyncMongoExecutor.from_uri(uri, concurrency=4) as executor:
    results = await executor.run_workload(workload)
```

Its factory is synchronous; operations and cleanup are awaited. Pass a borrowed
async client to its constructor to retain ownership of that client. Keep that
client and executor on one event loop, and close only after active calls finish.
The six operation contracts and results match the synchronous interface.
