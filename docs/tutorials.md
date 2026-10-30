# Tutorials

These five notebooks introduce common BONDI workflows through runnable examples.
Each is self-contained; choose a topic below and run its cells from top to bottom.

## Run the notebooks

Get the BONDI source checkout described in [Installation](installation.md), which
includes the `notebooks/` directory. From the repository root, prepare the Python
environment for all five notebooks:

```sh
uv sync --locked --extra couchbase
uv pip install --python .venv/bin/python ipykernel
```

Start Docker before running a database notebook. Its first code cell creates a
named deployment and loads the demo data; its final cell removes the deployment,
including its data volume and saved configuration. If you interrupt execution,
run that cleanup cell manually. The schema notebook needs no database or Docker.

### VS Code (recommended for students)

1. Open the BONDI repository folder in VS Code and install Microsoft's **Python**
   and **Jupyter** extensions.
2. Open an `.ipynb` file from `notebooks/` in the Explorer.
3. Click **Select Kernel** in the notebook toolbar and choose the repository's
   `.venv` Python environment. If needed, use **Select Another Kernel → Python
   Environments** to find it.
4. Run cells in order with **Shift+Enter**, or use **Run All**.

VS Code runs the notebook directly; you do not need to start a separate Jupyter
server. See the [VS Code notebook guide](https://code.visualstudio.com/docs/datascience/jupyter-notebooks)
for more on editing cells and selecting a kernel.

### JupyterLab alternative

If you prefer a browser interface, run this from the repository root:

```sh
uv run --extra couchbase --with jupyterlab --with ipykernel jupyter lab
```

Open a notebook from `notebooks/` in the browser interface and run its cells in order.

## Inspect a dataset

[Open `schema_demo.ipynb`](https://github.com/relaxed-constraints/bondi/blob/main/notebooks/schema_demo.ipynb)

Explore nested Python dictionaries without connecting to a database. Learn how
BONDI represents field types, nulls, missing values and array elements, then compare
value-retention modes and update a schema with another batch of documents.

## Execute and inspect MongoDB queries

[Open `workload_demo.ipynb`](https://github.com/relaxed-constraints/bondi/blob/main/notebooks/workload_demo.ipynb)

Describe find and aggregation queries, execute them individually or as a workload,
and inspect returned documents and timings. Compare explain with profile, summarise
native diagnostics, handle deliberate query failures, and save and restore workloads.
The examples also demonstrate sequential and concurrent execution without treating
their timings as a controlled benchmark.

## Estimate cardinality and selectivity

[Open `mongodb_estimation.ipynb`](https://github.com/relaxed-constraints/bondi/blob/main/notebooks/mongodb_estimation.ipynb)

Compare full-population counts with fresh samples and a reusable persisted sample.
Learn how cardinality differs from selectivity, why query limits do not affect these
estimates, and how context managers clean up temporary samples. The small dataset
makes sampling behaviour easy to inspect.

## Generate and evaluate a workload

[Open `workload_generation.ipynb`](https://github.com/relaxed-constraints/bondi/blob/main/notebooks/workload_generation.ipynb)

Generate query patterns and instances from observed schema values, check pattern
membership, and save and reload a workload. Then constrain queries using a sample
of the deployed demo data, execute the generated workload, and inspect profiling
summaries. Learn the distinction between seeded generation and database sampling,
and why sample-based selectivity bounds are not full-population guarantees.

## Explore Couchbase execution and profiling

[Open `couchbase_demo.ipynb`](https://github.com/relaxed-constraints/bondi/blob/main/notebooks/couchbase_demo.ipynb)

Run parameterised SQL++ queries and workloads against a Couchbase Community
deployment, then compare execution, explain plans and profiling metadata. Learn
how to interpret row counts, index consistency and common summaries, including
which detailed diagnostics are unavailable in Community edition.
