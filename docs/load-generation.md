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
may return awaitables; synchronous callbacks execute on the calling thread and
must not return awaitables or reenter the same executor.

## Selection and reproducibility

Policies live in `bondi.load`; weights are not attached to workload entries.

- `WeightedRandom(weights=[1, 3], seed=42)` samples with replacement using relative
  weights. Zero excludes an entry; weights must be finite and nonnegative, at
  least one positive, with one weight per entry.
- `UniformRandom(seed=42)` uses the same algorithm with equal weights.
- `Sequential()` starts each client at entry zero, advances in order and loops.
  Clients may initially contend on the same query; starting positions are not staggered.

Each call creates fresh streams for client IDs `0` through `concurrency - 1`,
independent of the number of entries. Random streams use a SHA-256-derived integer
seed from the ASCII string `bondi-load-v1:<seed>:<client_id>` and a private Python
`random.Random`. No global random state or Python object hash is used. Random
policies require an integer seed (not a boolean). Match Python/BONDI versions for
replay; this is not a cross-version stream-format guarantee.

Equal seeds, weights and entry order reproduce each client's selection prefix.
Adding clients does not change the existing streams. Timings determine how far
clients progress and the order in which results arrive, so neither total counts
nor concurrent interleavings are reproducible. To compare two backends, order
corresponding queries identically. Streams continue through warm-up into
measurement: different warm-up progress can change the measurement query mix.
Each admitted attempt consumes one selection even if it fails; there is no
scheduler retry. Choose different seeds for different repetitions.

## Phases and observations

Preparation validates arguments and the entire workload before starting a shared
monotonic clock. Warm-up admits queries in `[0, warmup_seconds)`; measurement
admits queries in `[warmup_seconds, warmup_seconds + measurement_seconds)`.
There is no phase barrier: a warm-up query can finish during measurement, and a
measurement query can finish during drain. No new invocations are admitted once
admissions stop. Existing invocations include any time spent in health preflight.

Every terminal observation is a `LoadResult` with the invocation and client IDs,
per-client sequence, workload position, admission phase, offsets from the common
origin, an optional `ExecutionResult`, and `stop_reason`. IDs and sequence numbers
start at zero. `query_started` means execution passed preflight, not proof the
server received the request.

`duration` is a derived property: `ended_seconds - admitted_seconds`, in seconds.
It includes scheduling after admission and health preflight, but excludes callback
delivery. `result.elapsed_ms` describes the underlying query, in milliseconds,
excluding health preflight. At drain expiry, `ended_seconds` records the expiry
observation, not when the database actually stopped working.

Publication metrics, repetitions, persistence and profiling remain separate from
load generation. In particular, an observation with `result=None` is not a
successful completion or a normal query timeout.

## Retention and callbacks

`collect_results=False` still fully consumes database rows but does not keep the
documents in `ExecutionResult`. `return_load_results=True` retains observations
and returns a list in callback-delivery order; set it to False for long runs to
avoid an ever-growing list. The latter returns `[]`.

`on_result` receives warm-up, measurement, error, timeout and drain-expiry
observations regardless of either flag. Callbacks are serialized. Each client
waits for its callback before another admission, so slow logging can limit load.
There is no unbounded background logging queue. A completed result waiting for
callback delivery is not converted into a drain timeout. Delivery and cleanup
can extend past the drain deadline. Callback errors propagate after worker
cancellation and cleanup; remaining deliveries are not guaranteed on exceptional
termination or caller cancellation. Treat callback arguments as read-only.

## Failures, health checks and drain expiry

See [bounded health checks](executor.md#bounded-health-checks) for probe behavior
and failure classification, and [backend timing and native options](executor.md#backend-timing-and-native-options)
for driver deadlines and `query_kwargs`. These executor settings also apply to
each query admitted by `generate_load()`.

`continue_on_error` is inherited from the executor and defaults to False. An
ordinary captured database error or query timeout stops admissions when False;
True allows continued execution. Enabled health checks stop admissions on observed
availability/access failures regardless of that setting. The triggering result
has `stop_reason="query_error"` or `"database_unavailable"`; in-flight queries
still drain and can deliver later results without a stop reason. Database health
preflight time is separate from the query deadline. There is no background health
monitor or automatic database restart.

Draining starts when admissions stop, including early stops. At expiry, remaining
operations receive cancellation requests and produce exactly one unresolved
`LoadResult` each, with `result=None` and `stop_reason="drain_timeout"`.
After worker cleanup and completed-result callbacks, these observations are
delivered in attempt-ID order. They do not raise a drain-expiry exception.
A driver that suppresses cancellation and later returns cannot produce a second
terminal result for the same invocation.

Cancellation is cooperative: cleanup, a blocking native driver or a blocking
callback can delay return. There is no hard wall-clock or server-side termination
guarantee. Use an external process supervisor if an unattended experiment requires
one. Programming errors and callback errors propagate rather than becoming query
outcomes. Caller cancellation also propagates after cleanup.

Measurement and drain durations are required, positive and finite; warm-up
defaults to zero and must be nonnegative and finite. A finite query timeout is
recommended but not mandatory. Normally choose a drain allowance greater than
the health-preflight allowance plus query timeout and cleanup margin. A shorter
drain allowance is permitted when unresolved observations are intentional.
