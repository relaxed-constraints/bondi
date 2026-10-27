# Generate and evaluate a MongoDB workload

**Goal:** connect schema inspection, sampling estimates, generation and execution.
Install the toolkit and initialize [MongoDB demo data](../local-databases.md) first.

```sh
uv run --with jupyterlab --with ipykernel jupyter lab notebooks/workload_generation.ipynb
```

Run the notebook's offline examples first. They generate 10 patterns with 50 instances,
inspect pattern membership, save/load JSONL and demonstrate seeded generation.
Enable its `RUN_LIVE` cell to use `demo.business` on port 27017. That example builds
a schema, prepares a temporary sample, constrains every query's selectivity and
cleans up the sample when finished. It does not modify source documents.

## Execute the generated workload

After the notebook has produced the live `workload`, run:

```python
from bondi.mongodb import MongoExecutor, summarize

with MongoExecutor.from_uri("mongodb://127.0.0.1:27017", concurrency=1) as executor:
    results = executor.run_workload(workload)
    profiles = executor.profile_workload(workload)

for entry, result, profile in zip(workload, results, profiles):
    if result is None or profile is None:
        continue
    if result.error is not None or profile.error is not None:
        print(result.error, profile.error)
        continue
    summary = summarize(profile.raw)
    print(entry.pattern_id, result.elapsed_ms, summary.keys_examined)
```

These are two separate passes. Execution elapsed time and explain-derived server
time measure different things. Keep concurrency at one for isolated query behavior;
increase it only when concurrent load is part of the experiment.

The demo sample is deliberately tiny. Try changing the selectivity bounds and
inspect `generator.last_stats`: tight bounds may make complete patterns impossible.
For full-population guarantees, add exact filter counts as a separate verification
step in your research project before publishing the workload.
