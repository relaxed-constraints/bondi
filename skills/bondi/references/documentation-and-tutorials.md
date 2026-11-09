# Documentation and tutorials

Use these online links in explanations when relevant. In a BONDI checkout, the
corresponding Markdown lives under `docs/`; public contracts come from source
docstrings rendered through mkdocstrings. Prefer local source matching the installed
version if published documentation differs.

| Task | Online guide |
| --- | --- |
| Install or choose extras | https://relaxed-constraints.github.io/bondi/installation/ |
| First end-to-end workflow | https://relaxed-constraints.github.io/bondi/quickstart/ |
| Deploy, load demo data, inspect or clean up | https://relaxed-constraints.github.io/bondi/deployment/ |
| MongoDB find and aggregation descriptions | https://relaxed-constraints.github.io/bondi/find-query/ |
| Couchbase SQL++ descriptions | https://relaxed-constraints.github.io/bondi/couchbase-query/ |
| Workloads and persistence | https://relaxed-constraints.github.io/bondi/workloads/ |
| Run queries, concurrency, errors | https://relaxed-constraints.github.io/bondi/executor/ |
| Explain versus profile | https://relaxed-constraints.github.io/bondi/profiling/ |
| Interpret diagnostic metrics | https://relaxed-constraints.github.io/bondi/summaries/ |
| Schema and retained values | https://relaxed-constraints.github.io/bondi/schemas/ |
| Cardinality and selectivity estimation | https://relaxed-constraints.github.io/bondi/mongodb-estimation/ |
| Patterns and workload generation | https://relaxed-constraints.github.io/bondi/workload-generation/ |
| Public API reference index | https://relaxed-constraints.github.io/bondi/api/ |
| Available and deferred capabilities | https://relaxed-constraints.github.io/bondi/roadmap/ |

For precise signatures, follow the API index to `reference/deployment/`,
`reference/queries/`, `reference/results/`, `reference/schema/`,
`reference/estimation/`, or backend pages under `reference/mongodb/` and
`reference/couchbase/`. Do not guess object anchors without checking the page.

## Runnable tutorials

Start with the [tutorial setup guide](https://relaxed-constraints.github.io/bondi/tutorials/).
Notebooks are in GitHub source, not the installed wheel:

- [Schema inspection](https://github.com/relaxed-constraints/bondi/blob/main/notebooks/schema_demo.ipynb):
  no database required.
- [MongoDB execution and profiling](https://github.com/relaxed-constraints/bondi/blob/main/notebooks/workload_demo.ipynb).
- [MongoDB estimation](https://github.com/relaxed-constraints/bondi/blob/main/notebooks/mongodb_estimation.ipynb).
- [Workload generation](https://github.com/relaxed-constraints/bondi/blob/main/notebooks/workload_generation.ipynb).
- [Couchbase execution](https://github.com/relaxed-constraints/bondi/blob/main/notebooks/couchbase_demo.ipynb).

These links show development source. For an older installed release, select its
matching Git tag (for example, replace `main` with `v0.1.9`). Database notebooks
create named deployments and load demo data; their cleanup cells delete the
deployment's data. Read setup and cleanup before running against existing state.
Notebook timings illustrate the API, not controlled benchmark results.
