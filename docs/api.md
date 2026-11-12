# API reference

The reference documents public constructors, methods, parameters and return values
from source docstrings. Start with the [user guide](workloads.md) for examples.

| Area | Reference |
| --- | --- |
| Database deployment | [Deployment API](reference/deployment.md) |
| Shared data | [Queries and workloads](reference/queries.md), [results and summaries](reference/results.md) |
| Dataset loading | [Dataset API](reference/data.md) |
| Data inspection | [Schemas](reference/schema.md) |
| Estimation contracts | [Estimator interfaces](reference/estimation.md) |
| MongoDB | [Queries](reference/mongodb/queries.md), [query statistics](reference/mongodb/statistics.md), [executors](reference/mongodb/executors.md), [estimation](reference/mongodb/estimation.md), [generation](reference/mongodb/generation.md), [summary parsing](reference/mongodb/summaries.md) |
| Couchbase | [Queries](reference/couchbase/queries.md), [executors](reference/couchbase/executors.md), [summary parsing](reference/couchbase/summaries.md) |

Synchronous classes are the default for scripts and notebooks. Async classes remain
available for applications that already use an event loop.
