# Implementation roadmap

Each step is discussed, implemented, verified and reviewed before advancing.
This roadmap is a guide, not a commitment to speculative classes.

| Step | Scope | Acceptance criterion |
| --- | --- | --- |
| 0 | Repository foundation | Editable install, import, pytest, Ruff, documentation build and distribution build work without a database. |
| 1 | MongoCollectionRef | Identify a database and collection without storing a connection. |
| 2 | MongoFindQuery | Construct and inspect a native find query with agreed validation. |
| 3 | Persistence and identity | Save and restore queries with explicit format and fingerprint rules. |
| 4 | MongoAggregateQuery, then CouchbaseQuery | Represent each native query form independently. |
| 5 | Shared query contract | Introduce a minimal protocol justified by concrete types. |
| 6 | WorkloadEntry, then Workload | Preserve order, duplicates and integer pattern membership; save/load versioned JSONL. |
| 7 | First database interaction | Execute a MongoDB query with defined result and resource lifetimes. |
| 8 | Explain support | Collect raw explains and parse MongoDB information without losing the source. |
| 9 | Second backend | Validate shared contracts through Couchbase execution and explains. |
| 10 | Sampling and schemas | Infer document structure from small local samples. |
| 11 | Workload generation | Generate a reproducible workload from one simple pattern. |
| 12 | Research measurements | Run a small repeatable experiment through yanex. |

## Current progress

Steps 0–6 are implemented, including atomic JSONL workload saves and loading
through the native query-kind loaders. Step 7 now implements async MongoDB
find/aggregation execution and raw explains, single-query and workload operations,
bounded concurrency, configurable failure continuation, deadlines and client ownership.
Step 8 now provides an offline QuerySummary parser for standalone winning
plans and conservative aggregation summaries, with saved explain fixtures. Raw
responses remain available. Sharded and nested-read metric interpretation, warmups
and repetitions are deferred.

Step 9 is implemented: optional Docker environments, shared synthetic sample data,
async Couchbase execution and explicit explain/execution summaries. Community basic
metrics and Enterprise detailed profiles are covered by saved fixtures and live tests.
Complex Couchbase plan layouts and examination-counter interpretation remain deferred.
Step 10 (sampling and schemas) is the next discussion.

## First functional milestone

A student can install the toolkit, construct a MongoDB find query, save it, reload
it and understand every class involved, without running a database.

## Per-component workflow

1. Explain the problem with a concrete usage example.
2. Discuss fields, methods, validation, mutability and exclusions.
3. Implement the smallest useful version.
4. Test meaningful contracts, failure cases and round trips.
5. Walk through the diff and documentation; pause for discussion.

Do not implement later steps in the background. Add tutorial notebooks at coherent
milestones, keeping reusable implementations in the library.

## Second-backend implementation plan

Parsing stays explicit: executors return `ExecutionResult`, including native `raw`
data; callers invoke backend-specific `summarize()` functions to produce a
shared `QuerySummary`. There is no nested summary or summary-merging API.

| Phase | Scope | Status |
| --- | --- | --- |
| 1 | Shared result contract: introduce `QuerySummary`, rename the output count to `rows_returned`, replace `ExecutionResult.explain` with `raw`, allow arbitrary output rows and add `warnings`. Adapt MongoDB parsing, examples and tests. | Implemented |
| 2 | Split MongoDB operations into `run()`, planning-only `explain()` and instrumented `profile()`, plus the three workload methods. Keep parsing separate. | Implemented |
| 3 | Add `AsyncCouchbaseExecutor` with the same six methods, optional SDK dependency, native metadata, deadlines, concurrency and failure handling. Support Enterprise profiling and report unavailable detailed profiling explicitly. | Implemented |
| 4 | Add Couchbase offline `summarize()` parser, fixtures and student examples, using `QuerySummary` and conservative metric definitions. | Implemented |

Phase 2 separates planning from instrumented execution. Replace
`explain(..., verbosity="executionStats")` with `profile(...)`, and use
`profile_workload(...)` for workload statistics. `allPlansExecution` remains a
profile verbosity; `explain()` no longer accepts a verbosity argument.
No additional queries are issued to populate summaries. Parsing failures belong
to the explicit parser call and do not change a successful execution result.

### Phase 1 API migration

- Import `QuerySummary` from `dbrtoolkit.summary` instead of `MongoExplainSummary`
  from `dbrtoolkit.mongodb`.
- Read `summary.rows_returned` instead of `summary.documents_returned`.
- Read `result.raw` instead of `result.explain`.
- `result.row_count` still counts rows consumed by `run()`; it is independent of
  the server-reported output count extracted by a parser.

These names change directly, without compatibility aliases, while the API is young.


### Unified summary API

Each backend now exports only `summarize(raw)`. Replace the earlier
`summarize_explain()` / `summarize_execution()` calls with this function; Couchbase
selects the format internally. `None` returns an empty summary, while malformed,
unrecognized or explicitly failed responses raise. Check execution status first.
No compatibility aliases are retained.
