---
render_macros: true
---

# BONDI

*A Python toolkit for document database research.*

`bondi` is a Python toolkit for document database research and benchmarking with
MongoDB and Couchbase. It gives students and researchers reusable building blocks
for setting up databases, running experiments and analysing their behaviour.

## Start here

1. [Install the toolkit](installation.md).
2. [Deploy a local database](deployment.md) using the CLI or Python API, then load your data.
3. [Run your first query](quickstart.md).

Explore the [User guide](deployment.md) by task, follow a [Tutorial](tutorials.md) for a complete workflow,
or use the [API reference](api.md) to look up a particular class or method.

## What's currently supported

| Capability | MongoDB | Couchbase |
| --- | --- | --- |
| **[Local deployments via CLI & API](deployment.md)** | ✅ Supported | ✅ Supported |
| **[Dataset loading](datasets.md)** | ✅ Files, Python documents and Hugging Face datasets | ✅ Same sources, with type conversion |
| **[Native queries and workload persistence](workloads.md)** | ✅ Find and aggregation |  ✅ SQL++ |
| **[Query and workload execution, explain and profiling](executor.md)** | ✅ Supported |  ✅ Supported; detailed profiling requires enterprise edition |
| **[Load generation](load-generation.md)** | ✅ Sustained load with sync and async executors | ✅ Same API |
| **[Summary parsing](summaries.md)** | ✅ Supported |  ✅ Supported; some metrics unavailable |
| **[Schema inspection](schemas.md)** |  ✅ Python documents from either backend or files |  ✅ Same parser |
| **[Sampling estimation](mongodb-estimation.md)** | ✅ Supported | ❌ Planned/deferred |
| **[Pattern-based workload generation](workload-generation.md)** | 🟡 Flat find queries; no logical expressions or aggregation pipelines | ❌ Not implemented |

BONDI [{{ bondi_version }}](https://pypi.org/project/bondi/{{ bondi_version }}/) is available under the MIT license.
