# Roadmap

This page tracks capabilities and open work, not a commitment to release dates.

## Available

- Native MongoDB find/aggregation and Couchbase SQL++ query descriptions.
- Single-backend workloads, JSONL persistence and query fingerprints.
- Synchronous and asynchronous execution, explain and profile for both backends.
- Bounded workload concurrency, error continuation and deadlines.
- Offline summary parsing with conservative handling of unsupported metrics.
- Backend-independent schema inspection and optional value retention.
- MongoDB sampling estimation with temporary sample lifecycle management.
- Synchronous single-collection MongoDB flat-find workload generation.
- Local Docker databases and runnable teaching notebooks.
- Packaged MongoDB deployment API with named, persistent Docker instances.

## Deferred work

- Deployment CLI and Couchbase deployment API.
- Logical, array-expression and aggregation workload generation beyond flat find patterns.
- Couchbase sampling estimation and workload generation.
- Executor sampling helpers and bounded schema value retention.
- Schema persistence and merging.
- Warmups and repetitions for experiment execution.
- Broader explain-layout support and backend-specific measurement interpretation.

Research workflows can already combine these components in separate project
repositories. Future additions should follow demonstrated research needs, with a
small public contract and tests before expanding the API.
