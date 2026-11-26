# Adding a new database backend

Start with a workflow that a researcher can repeat. For example, load a dataset
with two related collections, reopen it, run a parameterized read, and inspect
how the engine found the matching records. This exercises identity, persistence,
query results and diagnostics before you commit to a public API.

BONDI shares operations across backends and keeps each engine's native query
language. Start from the [architecture](architecture.md) and agree on the
public contract before implementing it. Deliver each supported capability in a
separate, reviewable stage.

## 1. Test the fit

Keep a short spike report under `planning/`. Record the engine and driver
versions, dataset, commands, observed results and open questions. Mark each
capability **supported**, **limited** or **deferred** and describe what the
caller can rely on. Use a small real dataset for the workflow and a synthetic
fixture for cases the dataset misses.

| Question | Evidence to collect |
| --- | --- |
| What identifies the destination? | Map a dataset, collection and document ID to native names. Try the same collection name in two datasets. |
| What constitutes one document? | Write and read back nested objects, arrays, missing fields, nulls, dates and exact decimals. Compare values and types. |
| What constitutes one result? | Inspect the driver's output for a document, a scalar projection and an empty result. For graph reads, also inspect nodes, relationships and paths. |
| What does the engine measure? | Capture a native estimated plan and a measured execution if available. Record units, scope and engine settings. |
| Who owns persistent state? | Close and reopen the database. Check which data survive and which resources a caller can safely remove. |

For a graph engine, decide whether importing two related documents preserves
them independently or requires an explicit mapping to nodes and relationships.
For an embedded engine, test file-backed and in-memory connections separately.
Opening a second connection can affect database identity, visibility or locking.
Resolve these questions before promising the same loader or concurrency semantics.

## 2. Establish deployment and connection

Keep connection settings immutable and separate from the collection reference.
A caller should be able to open an existing database without asking BONDI to
provision it. Define how executors obtain a client, who closes it, and how to
keep credentials out of logs and saved workloads.

For a managed server, follow the existing Docker deployment API and CLI. Cover
image selection, readiness, port conflicts and persistent storage. Test the
full lifecycle, including reopening data after removal with `keep_data=True`.
For a file-backed engine, define path resolution, file ownership and cleanup.
If managed deployment has no useful meaning, document how to open the database
directly and mark that part of the deployment API as unsupported.

Keep native drivers optional where possible. Test import, query construction
and artifact loading in an environment without the driver. Identify the extra
when an operation requires it. See [connections](connections.md) and
[deployment](deployment.md).

## 3. Load documents through the existing readers

Add the destination writer in `bondi.data` so file, iterable, demo, Hugging Face
and AptMQL sources share identity and conversion rules. Specify how single
collections and whole datasets map to native namespaces. Record any generated
key separately from the user's document where the storage model requires it.

Test repeated loads in create, upsert and replace modes. Include duplicate IDs,
missing IDs, IDs of different types with the same printed value, and a failure
after one successful batch. Compare stored documents directly with the source
and verify that the loader reports acknowledged writes. For replacement, check
the destination layout before clearing data and verify that unrelated
collections survive. See [dataset loading](datasets.md).

## 4. Implement native queries and shared execution

Give the backend a stable identifier and its own query representation when
syntax, parameter binding or persistence differs. Implement the `Query`
protocol and connect its versioned envelope to workload loading. Round-trip
a saved workload offline and check bindings, fingerprints, order and pattern
IDs. Define which statements the executor accepts and how it handles writes
or multiple statements. See [workloads](workloads.md).

Use the existing execution results, workload scheduling, callback and
synchronous adapter code where they fit. Define how a native row becomes a
returned document and what the row count means. Run the same query with
collection enabled and disabled. Check empty results, bounded memory when
streaming, early failure and client reuse. If the driver serializes reads or
blocks during cancellation, document the resulting concurrency and timeout
limits. Exercise the synchronous and asynchronous entry points you expose.
See [execution](executor.md) and [load generation](load-generation.md).

## 5. Verify diagnostics against the query that actually runs

For `run()`, capture the result and client observations. For `explain()`,
identify which information the engine can obtain without executing the read.
For `profile()`, establish whether the engine executes the read and which
measurements it returns. A cursor wrapper, rewritten statement or different
parameter type can change the plan. Compare BONDI with the native driver using
the same statement, bindings and session settings. Choose a query for which
a plan change would be visible.

Preserve native diagnostics in `ExecutionResult.raw`. Where the backend exposes
diagnostics, implement offline `summarize()` against saved native responses.
Map a metric to `QuerySummary` only when its units and meaning match. A planner
estimate, observed row count and client elapsed time answer different questions.
Leave unavailable measurements unknown. Test an empty result, an unfamiliar
plan operator and a missing metric. See [profiling](profiling.md) and
[summaries](summaries.md).

## 6. Add index lifecycle where the semantics fit

Map `FieldIndex` only for paths and directions the engine can represent. Test
nested fields, arrays, missing values and nulls. Use a native index definition
for capabilities such as expressions or specialized access methods. Verify the
definition in the engine's catalog and inspect a plan for a representative
predicate that can use it.

Connect creation and removal to the shared connection-based dispatch. Define
name scope, quoting, protected indexes and transaction boundaries. Test single
and batch operations, name collisions, repeated removal, explicit replacement
and failure partway through a batch. Check the reported progress against the
catalog. See [index definitions](indexes.md).

## 7. Verify and document the supported surface

Follow one operation from the public import or CLI command through dispatch
to the driver. Useful starting points under `src/bondi/` include `connection.py`,
`deployment/`, `data/`, `query.py`, `workload.py`, `execution.py`,
`summary.py`, `indexes.py`, `_index_dispatch.py` and `_cli.py`. Check package
exports, optional dependencies and CLI help alongside the backend module.

Pair offline tests for validation, persistence and summary parsing with live
tests against a disposable database for each supported operation. Run the
opening workflow through public entry points in a clean environment. Keep a
small fixture and record any engine-version or edition limits needed to
reproduce the result. Estimation and workload generation can follow separately
when their native semantics and use cases are established.

Update the backend comparison, installation instructions, shared guides,
topic-based API reference, roadmap, BONDI skill and unreleased changelog.
State which features are available and give one runnable example. Complete the
checks in [Contributing](contributing.md) and the
[strict documentation build](documentation.md) before review.
