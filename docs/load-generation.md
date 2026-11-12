# Generating sustained load

`run_workload()` executes each workload entry once. `generate_load()` repeatedly
selects entries until its admission window ends, using the executor's concurrency,
query timeout, error policy and optional health preflight. Both MongoDB and
Couchbase provide synchronous and asynchronous methods.

```python
from bondi.load import WeightedRandom
from bondi.mongodb import MongoCollectionRef, MongoExecutor, MongoFindQuery
from bondi.workload import Workload, WorkloadEntry

collection = MongoCollectionRef("demo", "business")
workload = Workload(
    [
        WorkloadEntry(MongoFindQuery(collection, {"city": "Sydney"})),
        WorkloadEntry(MongoFindQuery(collection, {"city": "Melbourne"})),
    ]
)


def record_result(result):
    # Persist each observation here; keep this callback fast.
    print(result.attempt_id, result.workload_position, result.duration, result.stop_reason)


with MongoExecutor.from_uri(
    "mongodb://localhost:27017",
    concurrency=16,
    timeout_seconds=90,
    continue_on_error=True,
    health_check_timeout_seconds=2,
) as executor:
    results = executor.generate_load(
        workload,
        selection=WeightedRandom(weights=[1, 3], seed=42),
        warmup_seconds=60,
        measurement_seconds=180,
        drain_timeout_seconds=95,
        collect_results=False,
        return_load_results=False,
        on_result=record_result,
    )
    assert results == []  # Observations were delivered through the callback.
```

Use `await executor.generate_load(...)` with an async executor. Async callbacks
may return awaitables. Synchronous callbacks execute on the calling thread and
must not return awaitables or reenter the same executor.

Try the [MongoDB demo notebook](https://github.com/relaxed-constraints/bondi/blob/main/notebooks/mongodb_load_generation.ipynb)
for a complete example with a disposable database, result summaries and streamed callbacks.

## Selection and reproducibility

Policies live in `bondi.load`. Weights are not attached to workload entries.

- `WeightedRandom(weights=[1, 3], seed=42)` samples with replacement using relative
  weights. Zero excludes an entry. Weights must be finite and nonnegative, at
  least one positive, with one weight per entry.
- `UniformRandom(seed=42)` uses the same algorithm with equal weights.
- `Sequential()` starts each client at entry zero, advances in order and loops.
  Clients may initially contend on the same query. Starting positions are not staggered.

Each call creates fresh streams for client IDs `0` through `concurrency - 1`,
independent of the number of entries. Random streams use a SHA-256-derived integer
seed from the ASCII string `bondi-load-v1:<seed>:<client_id>` and a private Python
`random.Random`. No global random state or Python object hash is used. Random
policies require an integer seed (not a boolean). Match Python/BONDI versions for
replay. This is not a cross-version stream-format guarantee.

Equal seeds, weights and entry order reproduce each client's selection prefix.
Adding clients does not change the existing streams. Timings determine how far
clients progress and the order in which results arrive, so neither total counts
nor concurrent interleavings are reproducible. To compare two backends, order
corresponding queries identically. Streams continue through warm-up into
measurement: different warm-up progress can change the measurement query mix.
Each admitted attempt consumes one selection even if it fails. There is no
scheduler retry. Choose different seeds for different repetitions.

## Select patterns before query instances

`ByPattern` first selects a pattern ID, then a query from that pattern.
This gives patterns equal probability even when they contain different numbers of queries:

```python
from bondi.load import ByPattern, Sequential, UniformRandom

selection = ByPattern(
    patterns=UniformRandom(seed=42),
    instances=UniformRandom(seed=43),
)
```

Pass this policy as `selection` to `generate_load()`.
Every workload entry must have a `pattern_id`. The MongoDB workload generator already assigns these IDs.
The policy selects existing queries. It does not generate new values during the run.

Without `pattern_ids`, patterns follow ascending ID order. Use an explicit list to select a subset or specify another order:

```python
selection = ByPattern(
    pattern_ids=[0, 3, 7],
    patterns=WeightedRandom(weights=[5, 2, 1], seed=42),
    instances=Sequential(),
)
```

The weights correspond to IDs 0, 3 and 7. Each requested ID must have at least one query.
Missing IDs, duplicate IDs and entries without IDs raise errors before execution.
Instance policies support `UniformRandom` and `Sequential`. The default is `UniformRandom(seed=0)`.
Sequential instances follow workload order within each pattern. Duplicate entries remain separate choices.

Each client has its own pattern stream and separate instance streams for each pattern.
Streams continue across warm-up and measurement. A new call starts fresh streams.
Instance seeds include the client ID and pattern ID, so visits to other patterns do not advance that instance stream.
The same reproducibility limits as ordinary selection apply.
Use `workload[result.workload_position].pattern_id` to group observations by pattern.

## Phases and observations

Before the run, BONDI checks the arguments and every query in the workload.
It then starts one monotonic clock for all clients. This clock does not depend on changes to the system time.

An admission is the point when a client selects a query and starts an attempt.
The phases use these time intervals:

- Warm-up admits attempts in `[0, warmup_seconds)`.
- Measurement admits attempts in `[warmup_seconds, warmup_seconds + measurement_seconds)`.
- Drain admits no new attempts. It gives existing attempts time to finish.

Clients do not wait for other clients at a phase boundary.
A warm-up query can finish during measurement. A measurement query can finish during drain.
An attempt starts before its health check, if health checks are enabled.

Each finished or drain-expired attempt produces a `LoadResult`.
It records the attempt ID, client ID, client sequence, workload position and phase at admission.
It also records times relative to the shared clock, an optional `ExecutionResult`, and a `stop_reason`.
IDs and sequence numbers start at zero.
`query_started` means the attempt passed its health check. It does not prove that the server received the query.

`duration` is a derived property: `ended_seconds - admitted_seconds`, in seconds.
It includes scheduling time after admission and the health check. It excludes callback time.
`result.elapsed_ms` measures the database query in milliseconds and excludes the health check.
At drain expiry, `ended_seconds` records when BONDI observed expiry. It does not record when the database stopped the query.

Your experiment code calculates publication metrics, repeats runs, saves results and profiles queries.
An observation with `result=None` is neither a successful query nor a normal query timeout.

## Retention and callbacks

`collect_results=False` reads every database row but does not store the documents in `ExecutionResult`.
`return_load_results=True` stores the observations and returns them in callback order.
Set it to False for long runs to avoid storing an ever-growing list. The method then returns `[]`.

`on_result` receives observations from all phases, including errors, timeouts and drain expiry.
Both retention settings leave callbacks enabled.
BONDI calls one callback at a time. Each client waits for its callback before it starts another attempt.
Slow callbacks can therefore reduce the query rate. BONDI does not use an unbounded queue for background logging.

A completed query can wait for its callback. Drain expiry does not change that query's outcome to a drain timeout.
Callbacks and cleanup can continue past the drain deadline.
If a callback raises an exception, BONDI cancels the workers and waits for cleanup before it raises the exception.
After an exception or caller cancellation, BONDI does not guarantee delivery of the remaining callbacks.
Treat callback arguments as read-only.

## Failures, health checks and drain expiry

See [bounded health checks](executor.md#bounded-health-checks) for probe behavior
and failure classification, and [backend timing and native options](executor.md#backend-timing-and-native-options)
for driver deadlines and `query_kwargs`. These executor settings also apply to
each query admitted by `generate_load()`.

`generate_load()` uses the executor's `continue_on_error` setting, which defaults to False.
With False, a captured database error or query timeout stops new attempts. With True, clients can start more attempts.
When health checks are enabled, an observed availability or access failure stops new attempts regardless of this setting.
The result that triggers the stop has `stop_reason="query_error"` or `"database_unavailable"`.
Queries already in progress can finish during drain. Their results do not need a stop reason.
The health check has its own deadline, separate from the query deadline.
BONDI does not monitor health in the background or restart the database.

Drain starts when admissions stop, including early stops.
When drain expires, BONDI requests cancellation of the remaining operations.
Each unfinished attempt produces exactly one `LoadResult` with `result=None` and `stop_reason="drain_timeout"`.
BONDI first waits for worker cleanup and callbacks for completed queries.
It then delivers the drain-expired results in attempt-ID order. Drain expiry does not raise an exception.
If a driver ignores cancellation and returns later, BONDI does not produce a second result for that attempt.

Cancellation requires the driver and callbacks to cooperate.
Cleanup, a blocking driver or a blocking callback can delay the method's return.
The drain deadline does not guarantee when the method returns or when the server stops a query.
Use an external process supervisor if your unattended experiment needs a hard deadline.
Programming errors and callback errors raise exceptions instead of producing query outcomes.
Caller cancellation also propagates after cleanup.

You must supply positive, finite measurement and drain durations.
Warm-up defaults to zero. Its duration must be finite and cannot be negative.
A finite query timeout is recommended but not required.
Normally, allow enough drain time for the health check, query timeout and cleanup.
You can use a shorter drain period if you intend to record unfinished attempts.
