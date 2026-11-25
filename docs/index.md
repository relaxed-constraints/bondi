---
render_macros: true
---

# BONDI

*A Python toolkit for document database research.*

`bondi` is a Python toolkit for document database research and benchmarking with
MongoDB, Couchbase and PostgreSQL. It gives students and researchers reusable building blocks
for setting up databases, running experiments and analysing their behaviour.

PostgreSQL support is available in the development checkout. Use the checkout installation instructions below for this backend.

## Start here

1. [Install the toolkit](installation.md).
2. [Deploy a local database](deployment.md) using the CLI or Python API, then load your data.
3. [Run your first query](quickstart.md).

Explore the [User guide](deployment.md) by task, follow a [Tutorial](tutorials.md) for a complete workflow,
or use the [API reference](api.md) to look up a particular class or method.

## What's currently supported

| Capability | MongoDB | Couchbase | PostgreSQL |
| --- | --- | --- | --- |
| **[Local deployments via CLI & API](deployment.md)** | ✅ Supported | ✅ Supported | ✅ Named Docker deployment |
| **[Dataset loading](datasets.md)** | ✅ Files, Python documents and Hugging Face datasets | ✅ Same sources, with type conversion | ✅ Same sources, JSONB tables |
| **[Native queries and workload persistence](workloads.md)** | ✅ Find and aggregation |  ✅ SQL++ | ✅ SQL with positional bindings |
| **[Query and workload execution, explain and profiling](executor.md)** | ✅ Supported |  ✅ Supported; detailed profiling requires enterprise edition | ✅ Standalone reads and instrumented plans |
| **[Index lifecycle](indexes.md)** | Ordered and MongoDB-native indexes | Ordered and SQL++ expression indexes | JSONB path B-trees, expression B-trees and GIN |
| **[Load generation](load-generation.md)** | ✅ Sustained load with sync and async executors | ✅ Same API | ✅ Same API |
| **[Summary parsing](summaries.md)** | ✅ Supported |  ✅ Supported; some metrics unavailable | ✅ Native plans and server execution metrics |
| **[Schema inspection](schemas.md)** |  ✅ Python documents from databases or files |  ✅ Same parser | ✅ Pass decoded JSONB objects |
| **[Sampling estimation](mongodb-estimation.md)** | ✅ Supported | ❌ Planned/deferred | ❌ Unavailable |
| **[Pattern-based workload generation](workload-generation.md)** | 🟡 Flat find queries; no logical expressions or aggregation pipelines | ❌ Not implemented | ❌ Unavailable |

BONDI [{{ bondi_version }}](https://pypi.org/project/bondi/{{ bondi_version }}/) is available under the MIT license.
