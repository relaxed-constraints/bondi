# Explore Couchbase execution and profiling

**Goal:** compare normal execution, query plans and execution diagnostics for SQL++.
Install the Couchbase extra and start Docker. The first code cell deploys Community,
loads the demo data, and creates its primary index. The final cell stops the deployment
while retaining its data.

```sh
uv run --extra couchbase --with jupyterlab --with ipykernel jupyter lab notebooks/couchbase_demo.ipynb
```

The notebook obtains connection details and credentials from its deployment handle.
Run all cells in order; no environment variables or manual database setup are needed.

Work through the single-query and workload examples:

1. Execute a parameterized SQL++ query and inspect returned rows.
2. Explain it and inspect the plan without collecting execution statistics.
3. Profile it, inspect `warnings`, and summarize the metadata.
4. Compare input-order workload results and error handling.

Community supports basic execution metrics. Detailed profile trees require server
support; use the optional Enterprise evaluation environment only under applicable
license terms. Missing detail is not a failed query: unavailable summary fields
remain `None`.

Compare `SELECT RAW b` with `SELECT b` to see how row shape affects schema inspection.
See [summary interpretation](../summaries.md) before comparing MongoDB and Couchbase
metrics directly.
