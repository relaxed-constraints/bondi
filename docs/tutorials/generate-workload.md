# Generate and evaluate a MongoDB workload

**Goal:** connect schema inspection, sampling estimates, generation and execution.
Install the toolkit and start Docker. The first code cell deploys MongoDB and loads
the demo data; the final cell removes the deployment, its data volume and saved configuration.

```sh
uv run --with jupyterlab --with ipykernel jupyter lab notebooks/workload_generation.ipynb
```

Run the notebook's offline examples first. They generate 10 patterns with 50 instances,
inspect pattern membership, save/load JSONL and demonstrate seeded generation.
Continue through the database examples using the notebook's deployment. That example builds
a schema, prepares a temporary sample, constrains every query's selectivity and
cleans up the sample when finished. It does not modify source documents.

## Execute the generated workload

The notebook's final live section runs and profiles `live_workload` in two separate
passes. This is the workload generated from the actual demo schema, not the earlier
offline toy example. It checks outcomes and prints a few client timings and parsed
index-examination counts.

Execution elapsed time and explain-derived server time measure different things.
Keep concurrency at one for isolated query behavior; increase it only when
concurrent load is part of the experiment.

The demo sample is deliberately tiny. Try changing the selectivity bounds and
inspect `generator.last_stats`: tight bounds may make complete patterns impossible.
For full-population guarantees, add exact filter counts as a separate verification
step in your research project before publishing the workload.
