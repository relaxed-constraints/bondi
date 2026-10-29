# Explore Couchbase execution and profiling

**Goal:** compare normal execution, query plans and execution diagnostics for SQL++.
Install the Couchbase extra and deploy the Community database using
[Database deployment](../deployment.md#couchbase-deployments), then load the
[demo data](../deployment.md#demo-data).

```sh
uv run --extra couchbase --with jupyterlab --with ipykernel jupyter lab notebooks/couchbase_demo.ipynb
```

The notebook uses the bundled local connection and credentials by default. Override
its environment settings when connecting elsewhere; do not store private credentials
in notebooks you share.

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
