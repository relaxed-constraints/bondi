# Roadmap

This page tracks capabilities and open work, not a commitment to release dates.

## Available

- Dataset loading with explicit identity, split and write policies for MongoDB and Couchbase.

- Pattern-based load selection over saved workload instances with `ByPattern`.

- Sustained closed-loop load generation with per-client selection, warm-up,
  measurement, cooperative draining and streamed LoadResult observations.

- Bounded executor health probes and opt-in preflight checks with availability fail-fast scheduling.

- Offline MongoDB query statistics with versioned counts, structural depth/fan-out,
  and optional nested-pipeline scope.
- Explicit conversion of supported MongoDB find queries to aggregation pipelines.
- Native MongoDB find/aggregation and Couchbase SQL++ query descriptions.
- Single-backend workloads, JSONL persistence and query fingerprints.
- Synchronous and asynchronous execution, explain and profile for both backends.
- Bounded workload concurrency, error continuation, deadlines and serialized
  per-query result callbacks (caller-thread callbacks for synchronous executors).
- Offline summary parsing with conservative handling of unsupported metrics.
- Backend-independent schema inspection, optional value retention and versioned
  offline schema snapshots.
- MongoDB sampling estimation with temporary sample lifecycle management.
- Synchronous single-collection MongoDB flat-find workload generation.
- Local Docker databases and runnable teaching notebooks.
- Packaged MongoDB/Couchbase deployment API and CLI with named, persistent Docker instances.

## Deferred work

- Logical, array-expression and aggregation workload generation beyond flat find patterns.
- Couchbase sampling estimation and workload generation.
- Executor sampling helpers and bounded schema value retention.
- Schema merging.
- Experiment repetitions and orchestration remain in consumer projects.
- Broader explain-layout support and backend-specific measurement interpretation.

Research workflows can already combine these components in separate project
repositories. Future additions should follow demonstrated research needs, with a
small public contract and tests before expanding the API.
