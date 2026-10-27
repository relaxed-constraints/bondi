# Inspect a dataset

**Goal:** understand field types, missing values and retained values before choosing
workload-generation settings. No database is required.

Start Jupyter from the repository root:

```sh
uv run --with jupyterlab --with ipykernel jupyter lab notebooks/schema_demo.ipynb
```

The notebook is the executable companion to the [schema guide](../schemas.md).
Work through it from top to bottom:

1. Construct a small dataset with nested objects, arrays and missing fields.
2. Inspect field and type counts; distinguish missing values from nulls.
3. Compare `none`, `distinct` and `full` retention.
4. Inspect nested paths and add another batch of documents.

Try removing a nested field from one object. Predict which `count` and
`missing_count` values will change, then rerun the cells. Missingness is relative
to immediate parent objects, not automatically the number of root documents.

When moving to real data, replace the toy dictionaries with a bounded query result
or cursor. Use `values="distinct"` if the next step is workload generation.
