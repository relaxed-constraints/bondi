# BONDI

*A Python toolkit for document database research.*

`bondi` provides Python building blocks for students and researchers studying
database queries, query optimization and index selection. Use it to describe native
queries, run experiments against databases, inspect data, and generate workloads.
Research models and experiment tracking belong in your project; the toolkit supplies
the shared database components.

## Two common workflows

- **Describe queries → execute or profile → summarize results.** Compare query behavior
  while retaining native diagnostic responses for deeper analysis.
- **Inspect data → estimate selectivity → generate workloads.** Build groups of queries
  with fixed patterns and varying values, then save them for repeatable experiments.

| Capability | MongoDB | Couchbase |
| --- | --- | --- |
| Native queries and workload persistence | Find and aggregation | SQL++ |
| Execution, explain and profile | Supported | Detailed profiling depends on server support |
| Summary parsing | Supported | Supported; unavailable metrics remain `None` |
| Schema inspection | Python documents from either backend or files | Same parser |
| Sampling estimation | Supported | Planned/deferred |
| Pattern-based workload generation | Flat find queries | Not implemented |

BONDI [0.1.3](https://pypi.org/project/bondi/0.1.3/) is available under the MIT license.

## Start here

1. [Install the toolkit](installation.md).
2. [Deploy a local database](deployment.md) using the CLI or Python API, then load your data.
3. [Run your first query](quickstart.md).

Explore the **User guide** by task, follow a **Tutorial** for a complete workflow,
or use the [API reference](api.md) to look up a particular class or method.
